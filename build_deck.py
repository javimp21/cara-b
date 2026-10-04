"""Genera el mazo (cache/deck.json) que usa la app de tarjetas (cache/app.html).

Reutiliza discover.py (Deezer + CLAP) y añade:
  - Idioma cantado de cada canción, detectado con Whisper sobre la preview.
  - Popularidad RELATIVA (percentil de fans dentro del pool): en España casi todo
    el mundo usa Spotify y los fans de Deezer no son comparables entre países.
  - Embeddings centrados y reducidos a 64 dimensiones para que la app pueda
    recalcular las recomendaciones en el navegador tras cada swipe.

Uso:
  python build_deck.py --seeds "Barry B, Sanguijuelas del Guadiana, Venturi"
"""
import argparse
import json
import re

import librosa
import numpy as np
import requests
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

from discover import save_api_cache, AUDIO, CACHE, Embedder, crawl_related, download, find_artist, top_tracks

WHISPER_ID = "openai/whisper-small"
# Solo idiomas plausibles en música: evita que Whisper "invente" jemer o latín cuando duda
LANGS = ["es", "en", "pt", "fr", "it", "de", "ca", "gl", "eu", "ja", "ko", "zh",
         "ru", "nl", "sv", "pl", "tr", "ar", "hi"]
MIN_CONF = 0.45  # por debajo -> "?" (instrumental, mucha reverb, poca voz...)


class LangDetector:
    def __init__(self):
        print(f"Cargando {WHISPER_ID}...")
        self.proc = WhisperProcessor.from_pretrained(WHISPER_ID)
        self.model = WhisperForConditionalGeneration.from_pretrained(WHISPER_ID).eval()
        tok = self.proc.tokenizer
        self.ids = [tok.convert_tokens_to_ids(f"<|{c}|>") for c in LANGS]
        self.sot = tok.convert_tokens_to_ids("<|startoftranscript|>")
        self.cache_file = CACHE / "langs.json"
        self.cache = json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}

    @torch.no_grad()
    def __call__(self, track):
        key = str(track["id"])
        if key not in self.cache:
            y, _ = librosa.load(download(track), sr=16_000)
            # 3 ventanas de 10 s: la voz puede no entrar hasta mitad de la preview
            segs = [y[o * 16_000:(o + 10) * 16_000] for o in (0, 10, 20)]
            segs = [s for s in segs if len(s) > 16_000] or [y]
            feats = self.proc(segs, sampling_rate=16_000, return_tensors="pt").input_features
            dec = torch.full((len(segs), 1), self.sot)
            logits = self.model(input_features=feats, decoder_input_ids=dec).logits[:, -1, self.ids]
            p = torch.softmax(logits, -1)
            # las ventanas sin voz dan probabilidades "planas": pesan menos
            w = p.max(-1).values ** 2
            p = (p * w[:, None]).sum(0) / w.sum()
            self.cache[key] = [round(float(x), 4) for x in p]
        return np.array(self.cache[key])

    def save(self):
        self.cache_file.write_text(json.dumps(self.cache))


ES_HINT = re.compile(r"[ñáéíóú¿¡]|(el|la|los|las|de|del|que|mi|tu|te|me|yo|no|en|con|por|para|una?|y|amor|noche|corazón|sin|como|vida)", re.I)
EN_HINT = re.compile(r"(the|you|your|my|love|of|and|is|i'm|don't|me|it|in|on|night|baby)", re.I)


def text_prior(title):
    """Pista barata a partir del título (en la app real: letras vía API o metadatos)."""
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
                                 headers={"User-Agent": "music-discovery-prototype"}).json()
            except (requests.RequestException, ValueError):
                continue  # sin caché: se reintentará en la próxima ejecución
            r = r if isinstance(r, list) else []
            lyr = next((x["plainLyrics"] for x in r if x.get("plainLyrics")), None)
            cache[key] = lyr[:2000] if lyr else None
        t["lyrics_lang"] = lyrics_lang(cache[key]) if cache.get(key) else None
    print()
    LYRICS_CACHE.write_text(json.dumps(cache), encoding="utf-8")


def assign_languages(tracks):
    """Prioridad: idioma de la letra > idioma del artista (por sus otras letras) >
    audio (Whisper) + pistas del título + resto de canciones del artista."""
    fetch_lyrics_langs(tracks)
    for t in tracks:
        p = t["lang_p"] * text_prior(t["title"])
        t["lang_p"] = p / p.sum()
    by_artist, artist_lyrics = {}, {}
    for t in tracks:
        by_artist.setdefault(t["artist_id"], []).append(t["lang_p"])
        if t["lyrics_lang"]:
            artist_lyrics.setdefault(t["artist_id"], []).append(t["lyrics_lang"])
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


def percentile(values):
    order = np.argsort(np.argsort(values))
    return order / max(len(values) - 1, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--related", type=int, default=15)
    ap.add_argument("--max-artists", type=int, default=140)
    ap.add_argument("--tracks", type=int, default=2, help="canciones por artista")
    ap.add_argument("--drop-popular", type=float, default=0.12,
                    help="descarta este %% de artistas más conocidos del pool")
    ap.add_argument("--dims", type=int, default=64)
    args = ap.parse_args()
    AUDIO.mkdir(parents=True, exist_ok=True)

    seeds = [find_artist(n.strip()) for n in args.seeds.split(",") if n.strip()]
    print("Semillas:", ", ".join(f"{s['name']} ({s['nb_fan']} fans)" for s in seeds))
    graph = crawl_related(seeds, args.hops, args.related)
    seed_ids = {s["id"] for s in seeds}
    pool = [a for a in graph.values() if a["id"] not in seed_ids and a["nb_fan"] > 0]

    pct = percentile(np.array([a["nb_fan"] for a in pool]))
    for a, p in zip(pool, pct):
        a["pop_pct"] = float(p)
    too_famous = [a["name"] for a in pool if a["pop_pct"] > 1 - args.drop_popular]
    print(f"Grafo: {len(graph)} artistas. Fuera por demasiado conocidos: {', '.join(too_famous)}")
    pool = [a for a in pool if a["pop_pct"] <= 1 - args.drop_popular]
    pool.sort(key=lambda a: (a["hop"], -a["nb_fan"]))
    pool = pool[:args.max_artists]

    seed_tracks = [{**t, "seed": True, "nb_fan": s["nb_fan"], "hop": 0, "pop_pct": 1.0}
                   for s in seeds for t in top_tracks(s["id"], 3)]
    cands = [{**t, "seed": False, "nb_fan": a["nb_fan"], "hop": a["hop"], "pop_pct": a["pop_pct"]}
             for a in pool for t in top_tracks(a["id"], args.tracks)]
    # fuera colaboraciones de las semillas y canciones repetidas entre tops de artistas
    seen_ids = {t["id"] for t in seed_tracks}
    cands = [t for t in cands if t["artist_id"] not in seed_ids
             and not (t["id"] in seen_ids or seen_ids.add(t["id"]))]
    tracks = seed_tracks + cands
    save_api_cache()
    print(f"{len(pool)} artistas, {len(tracks)} canciones")

    emb, lang = Embedder(), LangDetector()
    ok = []
    for i, t in enumerate(tracks, 1):
        print(f"\rAudio {i}/{len(tracks)}", end="", flush=True)
        try:
            t["emb"] = emb.audio(t)
            t["lang_p"] = lang(t)
            ok.append(t)
        except Exception as e:
            print(f"\n  salto {t['artist']} – {t['title']}: {e}")
        if i % 25 == 0:
            emb.save(), lang.save()
    emb.save(), lang.save()
    print()
    assign_languages(ok)

    # centrar (CLAP vive en un cono estrecho) + PCA -> vectores pequeños para el navegador
    E = np.stack([t["emb"] for t in ok])
    E = E - E.mean(0)
    _, _, Vt = np.linalg.svd(E, full_matrices=False)
    R = E @ Vt[:args.dims].T
    R /= np.linalg.norm(R, axis=1, keepdims=True) + 1e-8

    deck = {
        "seeds": [s["name"] for s in seeds],
        "tracks": [{
            "id": t["id"], "title": t["title"], "artist": t["artist"], "artist_id": t["artist_id"],
            "cover": t["cover"], "link": t["link"], "fans": t["nb_fan"], "hop": t["hop"],
            "novelty": round(1 - t["pop_pct"], 3), "seed": t["seed"],
            "lang": t["lang"] if t["lang_conf"] >= MIN_CONF else "?", "lang_conf": t["lang_conf"],
            "lang_src": t["lang_src"],
            "emb": [round(float(x), 4) for x in r],
        } for t, r in zip(ok, R)],
    }
    (CACHE / "deck.json").write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    langs = {}
    for t in deck["tracks"]:
        langs[t["lang"]] = langs.get(t["lang"], 0) + 1
    print("Idiomas:", dict(sorted(langs.items(), key=lambda x: -x[1])))
    print(f"Mazo: {CACHE / 'deck.json'} ({len(deck['tracks'])} canciones)")


if __name__ == "__main__":
    main()
