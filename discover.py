"""Prototipo: ¿encuentran los embeddings de audio canciones que suenan parecido
a lo que te gusta, sin limitarse a los artistas de siempre?

Pipeline:
  1. Artistas semilla -> sus canciones top (Deezer).
  2. Grafo de "artistas relacionados" de Deezer a 2 saltos -> pool de candidatos.
  3. Se descartan los artistas muy famosos (nb_fan > --max-fans) y las semillas.
  4. Cada preview de 30 s se convierte en un vector con CLAP (modelo audio-texto).
  5. Ranking = similitud de sonido con tus semillas + un pequeño bonus de novedad.
  6. CLAP también puntúa etiquetas de texto ("voz femenina", "guitarras con reverb"...)
     para explicar POR QUÉ se parecen dos canciones.

Uso:
  python discover.py --seeds "Slowdive, Beach House, Cocteau Twins"
"""
import argparse
import html
import json
import math
import time
from collections import deque
from pathlib import Path

import librosa
import numpy as np
import requests
import torch
from transformers import ClapModel, ClapProcessor

API = "https://api.deezer.com"
CACHE = Path("cache")
AUDIO = CACHE / "audio"
MODEL_ID = "laion/larger_clap_music"
SR = 48_000

# Vocabulario para explicar similitudes (y, en la app, para los chips de "no me gusta porque...")
TAGS = {
    "voz femenina": "a song with female vocals",
    "voz masculina": "a song with male vocals",
    "instrumental": "an instrumental track with no vocals",
    "guitarras distorsionadas": "loud distorted electric guitars",
    "guitarras con reverb": "dreamy guitars drenched in reverb",
    "acústico": "acoustic guitar folk song",
    "sintetizadores": "synthesizers and electronic sounds",
    "piano": "a song led by piano",
    "lo-fi": "lo-fi bedroom recording",
    "producción pulida": "polished professional studio production",
    "rápido / enérgico": "fast energetic upbeat music",
    "lento / calmado": "slow calm relaxing music",
    "oscuro / melancólico": "dark melancholic sad music",
    "alegre / luminoso": "happy bright cheerful music",
    "bailable": "danceable music with a strong beat",
    "atmosférico": "ambient atmospheric soundscape",
    "agresivo": "aggressive heavy intense music",
    "hip hop / rap": "hip hop rap vocals",
}


# ---------------------------------------------------------------- Deezer
_API_CACHE_FILE = CACHE / "api_cache.json"
_api_cache = json.loads(_API_CACHE_FILE.read_text(encoding="utf-8")) if _API_CACHE_FILE.exists() else {}


def dz(path, **params):
    # /track no se cachea: lo usamos para renovar URLs de preview, que caducan
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    cacheable = not path.startswith("/track/")
    if cacheable and key in _api_cache:
        return _api_cache[key]
    for attempt in range(5):
        try:
            data = requests.get(f"{API}{path}", params=params, timeout=15).json()
        except (requests.RequestException, ValueError):
            time.sleep(2 * (attempt + 1))
            continue
        if isinstance(data, dict) and data.get("error", {}).get("code") == 4:  # quota
            time.sleep(1 + attempt)
            continue
        if cacheable and "error" not in data:
            _api_cache[key] = data
            if len(_api_cache) % 20 == 0:
                save_api_cache()
        return data
    raise RuntimeError(f"Deezer no responde: {path}")


def save_api_cache():
    CACHE.mkdir(exist_ok=True)
    _API_CACHE_FILE.write_text(json.dumps(_api_cache), encoding="utf-8")


def find_artist(name):
    res = dz("/search/artist", q=name, limit=1).get("data", [])
    if not res:
        raise SystemExit(f"No encuentro el artista: {name}")
    a = res[0]
    return {"id": a["id"], "name": a["name"], "nb_fan": a.get("nb_fan", 0)}


def top_tracks(artist_id, n):
    out = []
    for t in dz(f"/artist/{artist_id}/top", limit=n * 2).get("data", []):
        if t.get("preview"):
            out.append({
                "id": t["id"], "title": t["title"], "artist": t["artist"]["name"],
                "artist_id": t["artist"]["id"], "preview": t["preview"],
                "link": t["link"], "cover": t["album"].get("cover_medium", ""),
            })
        if len(out) == n:
            break
    return out


def crawl_related(seeds, hops, per_artist):
    """BFS por el grafo de relacionados. Devuelve {id: artista + distancia}."""
    seen = {s["id"]: {**s, "hop": 0} for s in seeds}
    queue = deque((s["id"], 0) for s in seeds)
    while queue:
        aid, hop = queue.popleft()
        if hop >= hops:
            continue
        for a in dz(f"/artist/{aid}/related", limit=per_artist).get("data", []):
            if a["id"] not in seen:
                seen[a["id"]] = {"id": a["id"], "name": a["name"],
                                 "nb_fan": a.get("nb_fan", 0), "hop": hop + 1}
                queue.append((a["id"], hop + 1))
    return seen


# ---------------------------------------------------------------- Audio / CLAP
# Una preview de 30 s pesa ~480 KB: por debajo de esto es una descarga truncada (había una de 15 KB)
MIN_PREVIEW_BYTES = 100_000


def download(track):
    """Descarga la preview. Las URLs firmadas de Deezer caducan a los ~15 min, así que
    si falla se pide una nueva a /track/{id} y se valida que de verdad sea audio."""
    path = AUDIO / f"{track['id']}.mp3"
    if path.exists() and path.stat().st_size > MIN_PREVIEW_BYTES:
        return path
    for url in (track["preview"], None):
        if url is None:
            url = dz(f"/track/{track['id']}").get("preview")
            if not url:
                break
        try:
            r = requests.get(url, timeout=30)
        except requests.RequestException:
            continue
        if r.ok and r.headers.get("content-type", "").startswith("audio") and len(r.content) > MIN_PREVIEW_BYTES:
            path.write_bytes(r.content)
            return path
    path.unlink(missing_ok=True)
    raise RuntimeError("preview no disponible")


def _feats(out):
    # transformers >= 5 devuelve un objeto de salida en vez del tensor directamente
    return out if isinstance(out, torch.Tensor) else out.pooler_output


class Embedder:
    def __init__(self):
        print(f"Cargando {MODEL_ID} (la primera vez descarga ~800 MB)...")
        self.model = ClapModel.from_pretrained(MODEL_ID).eval()
        self.proc = ClapProcessor.from_pretrained(MODEL_ID)
        self.cache_file = CACHE / "embeddings.npz"
        self.cache = dict(np.load(self.cache_file)) if self.cache_file.exists() else {}

    @torch.no_grad()
    def audio(self, track):
        key = str(track["id"])
        if key not in self.cache:
            y, _ = librosa.load(download(track), sr=SR, mono=True)
            if len(y) < 20 * SR:   # Deezer sirve a veces previews de ~1 s: no sirven para votar
                raise RuntimeError(f"preview demasiado corta ({len(y) / SR:.1f} s)")
            # 3 ventanas de 10 s -> media: más robusto que un solo fragmento
            chunks = [y[i:i + 10 * SR] for i in range(0, max(len(y) - 5 * SR, 1), 10 * SR)]
            chunks = [c for c in chunks if len(c) > 5 * SR] or [y]
            inp = self.proc(audio=chunks, sampling_rate=SR, return_tensors="pt")
            e = _feats(self.model.get_audio_features(**inp))
            e = torch.nn.functional.normalize(e, dim=-1).mean(0)
            self.cache[key] = torch.nn.functional.normalize(e, dim=0).numpy()
        return self.cache[key]

    @torch.no_grad()
    def text(self, prompts):
        inp = self.proc(text=prompts, return_tensors="pt", padding=True)
        e = _feats(self.model.get_text_features(**inp))
        return torch.nn.functional.normalize(e, dim=-1).numpy()

    def save(self):
        np.savez(self.cache_file, **self.cache)


def tag_profiles(tracks, tag_embs):
    """Cuánto destaca cada canción en cada etiqueta respecto al resto de canciones.
    (Comparar contra las demás canciones, no contra las demás etiquetas, evita que
    las mismas etiquetas "ganen" siempre por sesgos del texto.)"""
    raw = np.stack([t["emb"] for t in tracks]) @ tag_embs.T
    z = (raw - raw.mean(0)) / (raw.std(0) + 1e-8)
    for t, row in zip(tracks, z):
        t["tags"] = row


# ---------------------------------------------------------------- Ranking
def rank(seed_tracks, candidates, novelty_weight, max_fans):
    # CLAP mete toda la música en un "cono" estrecho (cosenos ~0.99 para todo).
    # Restar la media del pool y renormalizar hace que las diferencias se noten.
    mu = np.stack([t["emb"] for t in seed_tracks + candidates]).mean(0)
    center = lambda e: (e - mu) / (np.linalg.norm(e - mu) + 1e-8)
    S = np.stack([center(t["emb"]) for t in seed_tracks])
    for c in candidates:
        sims = S @ center(c["emb"])
        best = int(sims.argmax())
        # media de las 3 semillas más parecidas: premia parecerse a "tu gusto", no a una sola canción
        c["sim"] = float(np.sort(sims)[-3:].mean())
        c["nearest"] = seed_tracks[best]
        c["nearest_sim"] = float(sims[best])
        fans = max(c["nb_fan"], 1)
        c["novelty"] = 1 - math.log10(fans) / math.log10(max_fans)
        c["score"] = c["sim"] + novelty_weight * c["novelty"]
    candidates.sort(key=lambda c: c["score"], reverse=True)
    # diversidad: 1 canción por artista
    out, used = [], set()
    for c in candidates:
        if c["artist_id"] not in used:
            out.append(c)
            used.add(c["artist_id"])
    return out


# ---------------------------------------------------------------- Informe
def shared_tags(a, b, k=3):
    names = list(TAGS)
    both = np.minimum(a["tags"], b["tags"])
    return [names[i] for i in np.argsort(both)[::-1][:k] if both[i] > 0.25]


def fmt_fans(n):
    return f"{n / 1e6:.1f} M" if n >= 1e6 else f"{n / 1e3:.0f} k" if n >= 1e3 else str(n)


def card(c, i, seeds_by_id):
    why = shared_tags(c, c["nearest"])
    why_txt = ", ".join(why) if why else "parecido general de sonido"
    return f"""
    <article class="card">
      <div class="rank">{i}</div>
      <img src="{html.escape(c['cover'])}" alt="" loading="lazy">
      <div class="body">
        <h3>{html.escape(c['title'])}</h3>
        <p class="artist">{html.escape(c['artist'])} · <span class="muted">{fmt_fans(c['nb_fan'])} fans · salto {c['hop']}</span></p>
        <audio controls preload="none" src="audio/{c['id']}.mp3"></audio>
        <p class="why">Suena a <b>{html.escape(c['nearest']['artist'])} – {html.escape(c['nearest']['title'])}</b>
           ({c['nearest_sim']:.2f}) · en común: {html.escape(why_txt)}</p>
        <div class="bars">
          <span title="Similitud de sonido">sonido <i style="--v:{max(c['sim'], 0):.2f}"></i>{c['sim']:.2f}</span>
          <span title="Cuanto menos conocido, más alto">novedad <i style="--v:{max(c['novelty'], 0):.2f}"></i>{c['novelty']:.2f}</span>
        </div>
        <a href="{html.escape(c['link'])}" target="_blank" rel="noopener">Abrir en Deezer ↗</a>
      </div>
    </article>"""


def write_report(seeds, seed_tracks, ranked, args):
    seeds_by_id = {s["id"]: s for s in seeds}
    daily = ranked[:5]
    rest = ranked[5:args.show]
    bottom = ranked[-5:]
    seeds_html = "".join(
        f'<li><audio controls preload="none" src="audio/{t["id"]}.mp3"></audio> '
        f'{html.escape(t["artist"])} – {html.escape(t["title"])}</li>' for t in seed_tracks)
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prueba de recomendaciones</title>
<style>
:root{{--bg:#f6f5f2;--fg:#1d1d1f;--muted:#6b6b70;--card:#fff;--line:#e3e1dc;--acc:#3a6df0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141416;--fg:#ececef;--muted:#9a9aa2;--card:#1e1e22;--line:#2e2e34;--acc:#7c9cff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:860px;margin:auto;padding:24px 16px 64px}}h1{{margin:0 0 4px}}h2{{margin:36px 0 12px}}
.muted{{color:var(--muted)}}details{{margin:12px 0}}li{{margin:4px 0}}li audio{{height:28px;vertical-align:middle;width:180px}}
.card{{display:grid;grid-template-columns:28px 96px 1fr;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:10px 0}}
.rank{{font-weight:700;color:var(--muted)}}.card img{{width:96px;height:96px;border-radius:8px;object-fit:cover}}
h3{{margin:0;font-size:16px}}.artist{{margin:0 0 6px}}audio{{width:100%;height:34px}}.why{{margin:6px 0;font-size:14px}}
.bars{{display:flex;gap:18px;font-size:12px;color:var(--muted);flex-wrap:wrap}}.bars span{{display:flex;align-items:center;gap:6px}}
.bars i{{display:inline-block;width:70px;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--acc) calc(var(--v)*100%),var(--line) 0)}}
a{{color:var(--acc);font-size:13px}}
@media (max-width:560px){{.card{{grid-template-columns:64px 1fr}}.rank{{display:none}}.card img{{width:64px;height:64px}}}}
</style></head><body><main>
<h1>Tus 5 de hoy</h1>
<p class="muted">Semillas: {html.escape(', '.join(s['name'] for s in seeds))} · {len(ranked)} artistas candidatos
 (máx. {fmt_fans(args.max_fans)} fans, {args.hops} saltos) · peso novedad {args.novelty}</p>
<details><summary>Canciones semilla ({len(seed_tracks)})</summary><ul>{seeds_html}</ul></details>
{''.join(card(c, i + 1, seeds_by_id) for i, c in enumerate(daily))}
<h2>Siguientes del ranking</h2>
{''.join(card(c, i + 6, seeds_by_id) for i, c in enumerate(rest))}
<h2>Control: las 5 que el modelo ve <em>menos</em> parecidas</h2>
<p class="muted">Si estas te gustan tanto como las de arriba, el modelo no está aportando nada.</p>
{''.join(card(c, len(ranked) - 4 + i, seeds_by_id) for i, c in enumerate(bottom))}
</main></body></html>"""
    out = CACHE / "report.html"
    out.write_text(page, encoding="utf-8")
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True, help="artistas separados por comas")
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--related", type=int, default=12, help="relacionados por artista")
    ap.add_argument("--max-fans", type=int, default=150_000, help="por encima = demasiado conocido")
    ap.add_argument("--min-fans", type=int, default=300)
    ap.add_argument("--max-candidates", type=int, default=80)
    ap.add_argument("--novelty", type=float, default=0.08, help="peso del bonus de novedad")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()
    AUDIO.mkdir(parents=True, exist_ok=True)

    seeds = [find_artist(n.strip()) for n in args.seeds.split(",") if n.strip()]
    print("Semillas:", ", ".join(f"{s['name']} ({fmt_fans(s['nb_fan'])})" for s in seeds))

    graph = crawl_related(seeds, args.hops, args.related)
    seed_ids = {s["id"] for s in seeds}
    pool = [a for a in graph.values()
            if a["id"] not in seed_ids and args.min_fans <= a["nb_fan"] <= args.max_fans]
    # prioriza cercanía en el grafo, luego menos fans
    pool.sort(key=lambda a: (a["hop"], a["nb_fan"]))
    pool = pool[:args.max_candidates]
    print(f"Grafo: {len(graph)} artistas -> {len(pool)} candidatos tras filtrar por fans")

    emb = Embedder()
    tag_embs = emb.text(list(TAGS.values()))

    seed_tracks = [t for s in seeds for t in top_tracks(s["id"], 3)]
    candidates = []
    for a in pool:
        for t in top_tracks(a["id"], 2):
            candidates.append({**t, "nb_fan": a["nb_fan"], "hop": a["hop"]})

    all_tracks = seed_tracks + candidates
    for i, t in enumerate(all_tracks, 1):
        print(f"\rEmbeddings {i}/{len(all_tracks)}", end="", flush=True)
        try:
            t["emb"] = emb.audio(t)
        except Exception as e:  # preview roto / caducado
            print(f"\n  salto {t['artist']} – {t['title']}: {e}")
    print()
    emb.save()
    seed_tracks = [t for t in seed_tracks if "emb" in t]
    candidates = [t for t in candidates if "emb" in t]
    tag_profiles(seed_tracks + candidates, tag_embs)

    ranked = rank(seed_tracks, candidates, args.novelty, args.max_fans)
    out = write_report(seeds, seed_tracks, ranked, args)
    print("\nTop 5 del día:")
    for c in ranked[:5]:
        print(f"  {c['score']:.3f}  {c['artist']} – {c['title']}  ({fmt_fans(c['nb_fan'])} fans)"
              f"  ~ {c['nearest']['artist']}")
    json.dump([{k: v for k, v in c.items() if k not in ("emb", "tags", "nearest")} | {"nearest": c["nearest"]["artist"]}
               for c in ranked], open(CACHE / "ranking.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nInforme: {out.resolve()}")


if __name__ == "__main__":
    main()
