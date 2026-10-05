"""Crea y AMPLÍA el catálogo de Cara B (cache/catalog.json).

El catálogo es la lista de canciones candidatas con sus datos básicos (artista, portada, enlace, idioma).
Es incremental: cada ejecución con --extend añade artistas nuevos sin tocar ni recalcular lo ya hecho.
Después, `python pipeline.py` calcula (también de forma incremental) los vectores de audio y genera el
mazo que lee la app.

Uso:
  # primera vez: grafo de artistas relacionados a partir de unas semillas
  python build_deck.py --seeds "Barry B, Sanguijuelas del Guadiana, Venturi"

  # ampliar desde las semillas actuales: más lejos en el grafo (3 saltos) y hasta 500 artistas nuevos
  python build_deck.py --extend --hops 3 --max-artists 500

  # ampliar a partir de lo que te ha gustado (archivo exportado desde la app con ?dev)
  python build_deck.py --extend --votes votos.json

  # añadir nuevos gustos declarados (sus canciones pasan a ser semillas del mazo)
  python build_deck.py --extend --seeds "Cala Vento, Hinds"

Idioma de cada canción, por orden de fiabilidad: letra (LRCLIB) > idioma del artista (por sus otras
letras) > audio (Whisper) + pistas del título. Whisper solo se ejecuta para los artistas sin letras.
"""
import argparse
import json
import re

import librosa
import numpy as np
import requests

from discover import AUDIO, CACHE, crawl_related, download, find_artist, save_api_cache, top_tracks

CATALOG = CACHE / "catalog.json"
WHISPER_ID = "openai/whisper-small"
# Solo idiomas plausibles en música: evita que Whisper "invente" jemer o latín cuando duda
LANGS = ["es", "en", "pt", "fr", "it", "de", "ca", "gl", "eu", "ja", "ko", "zh",
         "ru", "nl", "sv", "pl", "tr", "ar", "hi"]
MIN_CONF = 0.45       # por debajo -> "?" (instrumental, mucha reverb, poca voz...)
MIN_SECONDS = 20      # Deezer sirve a veces previews de ~1 s: no sirven para votar


# ---------------------------------------------------------------- idioma por audio (solo si no hay letra)
class LangDetector:
    def __init__(self):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        print(f"Cargando {WHISPER_ID}...")
        self.proc = WhisperProcessor.from_pretrained(WHISPER_ID)
        self.model = WhisperForConditionalGeneration.from_pretrained(WHISPER_ID).eval()
        tok = self.proc.tokenizer
        self.ids = [tok.convert_tokens_to_ids(f"<|{c}|>") for c in LANGS]
        self.sot = tok.convert_tokens_to_ids("<|startoftranscript|>")
        self.cache_file = CACHE / "langs.json"
        self.cache = json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}

    def __call__(self, track):
        key = str(track["id"])
        if key not in self.cache:
            torch = self.torch
            y, _ = librosa.load(download(track), sr=16_000)
            # 3 ventanas de 10 s: la voz puede no entrar hasta mitad de la preview
            segs = [y[o * 16_000:(o + 10) * 16_000] for o in (0, 10, 20)]
            segs = [s for s in segs if len(s) > 16_000] or [y]
            feats = self.proc(segs, sampling_rate=16_000, return_tensors="pt").input_features
            dec = torch.full((len(segs), 1), self.sot)
            with torch.no_grad():
                logits = self.model(input_features=feats, decoder_input_ids=dec).logits[:, -1, self.ids]
            p = torch.softmax(logits, -1)
            w = p.max(-1).values ** 2          # las ventanas sin voz dan probabilidades "planas": pesan menos
            p = (p * w[:, None]).sum(0) / w.sum()
            self.cache[key] = [round(float(x), 4) for x in p]
        return np.array(self.cache[key])

    def save(self):
        self.cache_file.write_text(json.dumps(self.cache))


ES_HINT = re.compile(r"[ñáéíóú¿¡]|\b(el|la|los|las|de|del|que|mi|tu|te|me|yo|no|en|con|por|para|una?|y|amor|noche|corazón|sin|como|vida)\b", re.I)
EN_HINT = re.compile(r"\b(the|you|your|my|love|of|and|is|i'm|don't|me|it|in|on|night|baby)\b", re.I)


def text_prior(title):
    """Pista barata a partir del título."""
    prior = np.ones(len(LANGS))
    es, en = len(ES_HINT.findall(title)), len(EN_HINT.findall(title))
    prior[LANGS.index("es")] *= 1 + 1.5 * min(es, 2)
    prior[LANGS.index("en")] *= 1 + 1.5 * min(en, 2)
    return prior


# Palabras muy frecuentes por idioma: con unas pocas líneas de letra basta para distinguirlos
STOPWORDS = {
    "es": "que de no la el en y los se me mi tu te lo por con para una pero yo como más sin hay qué está eres soy todo cuando nunca también donde quiero ahora siempre nada nadie contigo conmigo ella esto eso estoy tengo puedo hoy ya muy bien hasta desde porque mejor algo vez otra",
    "en": "the you i to and a me my it is in that of your we on don't i'm for be all love can know just like what so",
    "ca": "que de i la el em et amb per és els les meu teu no què una sóc ara molt tot com hi avui del al ens jo tu",
    "pt": "que de não o a e eu você meu minha é em um uma com para mais se tudo quando nunca também onde estou",
    "fr": "je de la le et tu que les pas des un une est moi toi mon ma pour dans qui sur ce avec plus",
    "it": "che di non la il e io tu un una mi ti per con sono come più ma questo quando sei anche",
    "gl": "que de non a o e eu ti meu miña é en un unha coma para máis se todo cando nunca tamén onde",
    "eu": "eta da ez ba ere bat dut duzu nire zure baina gaur bihotz zer non nola",
    "de": "ich du und die der das nicht ist ein eine mich dich mein dein mit für auf wir sie es",
}
_ALL = [set(w.split()) for w in STOPWORDS.values()]
# solo cuentan las palabras exclusivas de cada idioma ("que", "de", "en"... no distinguen nada)
_SW = {lang: {w for w in set(ws.split()) if sum(w in a for a in _ALL) == 1}
       for lang, ws in STOPWORDS.items()}
LYRICS_CACHE = CACHE / "lyrics_text.json"


def lyrics_lang(text):
    words = re.findall(r"[\w']+", text.lower())
    if len(words) < 15:
        return None
    hits = {lang: sum(w in sw for w in words) / len(words) for lang, sw in _SW.items()}
    best = max(hits, key=hits.get)
    second = sorted(hits.values())[-2]
    return best if hits[best] > 0.03 and hits[best] > 1.5 * second else None


def fetch_lyrics_langs(tracks):
    """Idioma de la letra vía LRCLIB (gratis, sin clave). Cachea por canción."""
    cache = json.loads(LYRICS_CACHE.read_text(encoding="utf-8")) if LYRICS_CACHE.exists() else {}
    for i, t in enumerate(tracks, 1):
        key = str(t["id"])
        if key not in cache:
            print(f"\rLetras {i}/{len(tracks)}", end="", flush=True)
            try:
                r = requests.get("https://lrclib.net/api/search", timeout=10,
                                 params={"artist_name": t["artist"], "track_name": t["title"]},
                                 headers={"User-Agent": "cara-b-prototype"}).json()
            except (requests.RequestException, ValueError):
                continue  # sin caché: se reintentará en la próxima ejecución
            r = r if isinstance(r, list) else []
            lyr = next((x["plainLyrics"] for x in r if x.get("plainLyrics")), None)
            cache[key] = lyr[:2000] if lyr else None
        t["lyrics_lang"] = lyrics_lang(cache[key]) if cache.get(key) else None
    print()
    LYRICS_CACHE.write_text(json.dumps(cache), encoding="utf-8")


def assign_languages(tracks):
    """Prioridad: letra > idioma del artista (por sus otras letras) > audio + título + resto del artista.
    Whisper solo se carga y ejecuta para los artistas que no tienen ninguna letra disponible."""
    fetch_lyrics_langs(tracks)
    artist_lyrics = {}
    for t in tracks:
        if t["lyrics_lang"]:
            artist_lyrics.setdefault(t["artist_id"], []).append(t["lyrics_lang"])
    need_audio = [t for t in tracks if t["artist_id"] not in artist_lyrics]
    if need_audio:
        detector = LangDetector()
        for i, t in enumerate(need_audio, 1):
            print(f"\rIdioma por audio {i}/{len(need_audio)}", end="", flush=True)
            try:
                p = detector(t) * text_prior(t["title"])
                t["lang_p"] = p / p.sum()
            except Exception as e:
                print(f"\n  sin idioma {t['artist']} – {t['title']}: {e}")
                t["lang_p"] = np.ones(len(LANGS)) / len(LANGS)
            if i % 25 == 0:
                detector.save()
        detector.save()
        print()
    by_artist = {}
    for t in need_audio:
        by_artist.setdefault(t["artist_id"], []).append(t["lang_p"])
    for t in tracks:
        if t["lyrics_lang"]:
            t["lang"], t["lang_conf"], t["lang_src"] = t["lyrics_lang"], 1.0, "letra"
        elif t["artist_id"] in artist_lyrics:
            langs = artist_lyrics[t["artist_id"]]
            t["lang"], t["lang_conf"], t["lang_src"] = max(set(langs), key=langs.count), 0.8, "artista"
        else:
            p = 0.6 * t["lang_p"] + 0.4 * np.mean(by_artist[t["artist_id"]], axis=0)
            i = int(p.argmax())
            t["lang"], t["lang_conf"], t["lang_src"] = LANGS[i], round(float(p[i]), 2), "audio"
        if t["lang_conf"] < MIN_CONF:
            t["lang"] = "?"


# ---------------------------------------------------------------- catálogo
def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else {"seeds": [], "tracks": []}


def save_catalog(cat):
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")


def usable_preview(track):
    """Descarga la preview y comprueba que dura lo que debe. Devuelve False si no sirve."""
    try:
        path = download(track)
        if librosa.get_duration(path=str(path)) < MIN_SECONDS:
            path.unlink(missing_ok=True)
            return False
        return True
    except Exception as e:
        print(f"\n  sin preview {track['artist']} – {track['title']}: {e}")
        return False


def votes_to_seeds(path, cat):
    """Artistas de las canciones que te han gustado (archivo exportado desde la app con ?dev)."""
    log = json.loads(open(path, encoding="utf-8").read()).get("log", [])
    liked = {e["id"] for e in log if e["kind"] in ("like", "known-like")}
    by_id = {t["id"]: t for t in cat["tracks"]}
    artists = {}
    for i in liked:
        t = by_id.get(i)
        if t:
            artists[t["artist_id"]] = {"id": t["artist_id"], "name": t["artist"], "nb_fan": t["fans"]}
    return list(artists.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="", help="artistas separados por comas")
    ap.add_argument("--extend", action="store_true", help="añadir al catálogo existente")
    ap.add_argument("--votes", help="votos exportados desde la app: sus artistas favoritos amplían el grafo")
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--related", type=int, default=15)
    ap.add_argument("--max-artists", type=int, default=140)
    ap.add_argument("--tracks", type=int, default=2, help="canciones por artista")
    ap.add_argument("--min-fans", type=int, default=300)
    ap.add_argument("--max-fans", type=int, help="por encima = demasiado conocido (por defecto, como el catálogo actual)")
    ap.add_argument("--drop-popular", type=float, default=0.12,
                    help="solo en la primera creación: descarta este %% de artistas más conocidos del grafo")
    args = ap.parse_args()
    AUDIO.mkdir(parents=True, exist_ok=True)

    cat = load_catalog() if args.extend else {"seeds": [], "tracks": []}
    if args.extend and not cat["tracks"]:
        raise SystemExit("No hay catálogo todavía: ejecuta primero sin --extend y con --seeds.")
    known_artists = {t["artist_id"] for t in cat["tracks"]}
    known_tracks = {t["id"] for t in cat["tracks"]}

    named = [find_artist(n.strip()) for n in args.seeds.split(",") if n.strip()]          # gustos declarados
    crawl_seeds = list(named)
    if args.votes:
        liked = votes_to_seeds(args.votes, cat)
        print(f"{len(liked)} artistas con canciones que te gustaron: {', '.join(a['name'] for a in liked[:8])}...")
        crawl_seeds += [a for a in liked if a["id"] not in {n["id"] for n in crawl_seeds}]
    if not crawl_seeds and args.extend:      # sin indicar nada: se sigue desde las semillas actuales del catálogo
        seen = {}
        for t in cat["tracks"]:
            if t["seed"]:
                seen[t["artist_id"]] = {"id": t["artist_id"], "name": t["artist"], "nb_fan": t["fans"]}
        crawl_seeds = list(seen.values())
    if not crawl_seeds:
        raise SystemExit("Indica --seeds o --votes.")
    print("Semillas del grafo:", ", ".join(f"{s['name']} ({s['nb_fan']} fans)" for s in crawl_seeds[:12]))

    graph = crawl_related(crawl_seeds, args.hops, args.related)
    skip = known_artists | {s["id"] for s in crawl_seeds}
    pool = [a for a in graph.values() if a["id"] not in skip and a["nb_fan"] >= args.min_fans]

    if args.extend:       # mismo criterio de "no demasiado conocido" que el catálogo actual
        cap = args.max_fans or max(t["fans"] for t in cat["tracks"] if not t["seed"])
    else:
        fans = np.array([a["nb_fan"] for a in pool])
        cap = args.max_fans or float(np.percentile(fans, 100 * (1 - args.drop_popular)))
    famous = [a["name"] for a in pool if a["nb_fan"] > cap]
    print(f"Grafo: {len(graph)} artistas; nuevos candidatos: {len(pool)}; "
          f"fuera por conocidos (>{int(cap)} fans): {len(famous)}")
    pool = sorted((a for a in pool if a["nb_fan"] <= cap), key=lambda a: (a["hop"], -a["nb_fan"]))[:args.max_artists]

    new = []
    if not args.extend:   # primera creación: las semillas y sus canciones son las anclas de gusto
        cat["seeds"] = [s["name"] for s in named]
    for s in named:       # gustos declarados nuevos: sus canciones pasan a ser semillas del mazo
        if s["id"] not in known_artists:
            cat["seeds"] = list(dict.fromkeys(cat["seeds"] + [s["name"]]))
            for t in top_tracks(s["id"], 3):
                if t["id"] not in known_tracks:
                    new.append({**t, "seed": True, "fans": s["nb_fan"], "hop": 0})
                    known_tracks.add(t["id"])
    for a in pool:
        for t in top_tracks(a["id"], args.tracks):
            if t["id"] not in known_tracks:
                new.append({**t, "seed": False, "fans": a["nb_fan"], "hop": a["hop"]})
                known_tracks.add(t["id"])
    save_api_cache()
    print(f"{len(pool)} artistas nuevos, {len(new)} canciones candidatas")

    ok = []
    for i, t in enumerate(new, 1):
        print(f"\rPreviews {i}/{len(new)}", end="", flush=True)
        if usable_preview(t):
            ok.append(t)
    print(f"\n{len(ok)} con preview válida")
    assign_languages(ok)

    keep = ("id", "title", "artist", "artist_id", "cover", "link", "fans", "hop", "seed", "lang", "lang_conf", "lang_src")
    cat["tracks"] += [{k: t[k] for k in keep} for t in ok]
    save_catalog(cat)
    langs = {}
    for t in cat["tracks"]:
        langs[t["lang"]] = langs.get(t["lang"], 0) + 1
    print("Idiomas:", dict(sorted(langs.items(), key=lambda x: -x[1])))
    print(f"Catálogo: {len(cat['tracks'])} canciones de {len({t['artist_id'] for t in cat['tracks']})} artistas -> {CATALOG}")
    print("Siguiente paso: python pipeline.py")


if __name__ == "__main__":
    main()
