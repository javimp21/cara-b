"""Paso final del mazo: sustituye los vectores CLAP por MERT (capas 4-7, mucho mejor para
parecido entre canciones) y añade medidas interpretables para explicar el parecido.

Orden del pipeline:  build_deck.py -> features.py -> mert_embed.py -> finalize_deck.py
"""
import json
import numpy as np

DIMS = 128
# build_deck.py escribe cache/deck.json (con vectores CLAP). Este paso lo reescribe con MERT, así que
# antes guarda el original; si ya se ejecutó, parte siempre de esa copia para poder repetirlo.
import os, shutil
if not os.path.exists("cache/deck_clap.json") or "embedding" not in json.load(open("cache/deck.json", encoding="utf-8")):
    shutil.copy("cache/deck.json", "cache/deck_clap.json")
d = json.load(open("cache/deck_clap.json", encoding="utf-8"))
M = dict(np.load("cache/mert.npz"))
F = np.load("cache/features.npz"); fi = {i: k for k, i in enumerate(F["ids"])}
tracks = [t for t in d["tracks"] if str(t["id"]) in M and str(t["id"]) in fi]

def norm(x): return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-8)
A = np.stack([M[str(t["id"])] for t in tracks])
X = norm(np.hstack([norm(A[:, L] - A[:, L].mean(0)) for L in range(4, 8)]))
X = X - X.mean(0)
_, _, Vt = np.linalg.svd(X, full_matrices=False)
R = norm(X @ Vt[:DIMS].T)

ix = [fi[str(t["id"])] for t in tracks]
pct = lambda v: np.argsort(np.argsort(v)) / (len(v) - 1)   # percentil 0-1 dentro del mazo
bpm = 2 ** F["tempo"][ix, 0]
energy = pct(F["energy"][ix, 0])          # RMS medio
bright = pct(F["timbre"][ix, 54])         # centroide espectral medio
pulse = pct(F["rhythm"][ix, 0])           # fuerza de los ataques (percusivo vs. suave)

for t, r, b, e, br, p in zip(tracks, R, bpm, energy, bright, pulse):
    t["emb"] = [round(float(x), 4) for x in r]
    t.update(bpm=round(float(b)), energy=round(float(e), 2), bright=round(float(br), 2), pulse=round(float(p), 2))
d["tracks"] = tracks
d["embedding"] = "MERT-v1-95M capas 4-7, PCA %d" % DIMS
json.dump(d, open("cache/deck.json", "w", encoding="utf-8"), ensure_ascii=False)
print(len(tracks), "canciones; bpm", int(bpm.min()), "-", int(bpm.max()))

# distribución de similitudes semilla -> candidata (para calibrar el bonus de novedad)
seeds = [i for i, t in enumerate(tracks) if t["seed"]]; cands = [i for i, t in enumerate(tracks) if not t["seed"]]
S = R[cands] @ R[seeds].T
best = S.max(1)
print("mejor similitud con una semilla: min %.2f  p25 %.2f  mediana %.2f  p75 %.2f  max %.2f" % (best.min(), *np.percentile(best, [25, 50, 75]), best.max()))
