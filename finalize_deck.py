"""Paso final del mazo: une el catálogo con los vectores de audio MERT (capas 4-7, PCA a 128 dimensiones),
las medidas interpretables (BPM, energía, brillo, pegada) y la novedad de cada artista, y escribe
cache/deck.json, que es lo que lee la app.

Se recalcula entero cada vez (tarda segundos): lo único lento, los vectores MERT y las características,
ya está en caché y solo se calcula para las canciones nuevas.

Orden:  build_deck.py -> genres.py -> features.py -> mert_embed.py -> finalize_deck.py -> aspects.py -> colors.py
        (o simplemente: python pipeline.py)
"""
import json

import numpy as np

DIMS = 128
cat = json.load(open("cache/catalog.json", encoding="utf-8"))
M = dict(np.load("cache/mert.npz"))
F = np.load("cache/features.npz"); fi = {i: k for k, i in enumerate(F["ids"])}
tracks = [dict(t) for t in cat["tracks"] if str(t["id"]) in M and str(t["id"]) in fi]
dropped = len(cat["tracks"]) - len(tracks)
if dropped:
    print(f"{dropped} canciones sin vectores (preview que falló): se omiten del mazo")


def norm(x): return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-8)


A = np.stack([M[str(t["id"])] for t in tracks])
X = norm(np.hstack([norm(A[:, L] - A[:, L].mean(0)) for L in range(4, 8)]))
X = X - X.mean(0)
_, _, Vt = np.linalg.svd(X, full_matrices=False)
R = norm(X @ Vt[:DIMS].T)

ix = [fi[str(t["id"])] for t in tracks]
pct = lambda v: np.argsort(np.argsort(v)) / max(len(v) - 1, 1)   # percentil 0-1 dentro del mazo
bpm = 2 ** F["tempo"][ix, 0]
energy = pct(F["energy"][ix, 0])          # RMS medio
bright = pct(F["timbre"][ix, 54])         # centroide espectral medio
pulse = pct(F["rhythm"][ix, 0])           # fuerza de los ataques (percusivo vs. suave)

# novedad = 1 - percentil de fans del artista entre todos los artistas del catálogo (relativo, no absoluto:
# los fans de Deezer no son comparables entre países)
artist_fans = {t["artist_id"]: t["fans"] for t in tracks if not t["seed"]}
order = {a: p for a, p in zip(artist_fans, pct(np.array(list(artist_fans.values()), dtype=float)))}

for t, r, b, e, br, p in zip(tracks, R, bpm, energy, bright, pulse):
    t["emb"] = [round(float(x), 4) for x in r]
    t["novelty"] = round(1 - order.get(t["artist_id"], 1.0), 3)
    t.update(bpm=round(float(b)), energy=round(float(e), 2), bright=round(float(br), 2), pulse=round(float(p), 2))

deck = {"seeds": cat["seeds"], "tracks": tracks, "embedding": "MERT-v1-95M capas 4-7, PCA %d" % DIMS}
json.dump(deck, open("cache/deck.json", "w", encoding="utf-8"), ensure_ascii=False)
print(len(tracks), "canciones de", len({t["artist_id"] for t in tracks}), "artistas; bpm", int(bpm.min()), "-", int(bpm.max()))

# distribución de similitudes semilla -> candidata
seeds = [i for i, t in enumerate(tracks) if t["seed"]]; cands = [i for i, t in enumerate(tracks) if not t["seed"]]
best = (R[cands] @ R[seeds].T).max(1)
print("mejor similitud con una semilla: min %.2f  p25 %.2f  mediana %.2f  p75 %.2f  max %.2f" % (best.min(), *np.percentile(best, [25, 50, 75]), best.max()))
