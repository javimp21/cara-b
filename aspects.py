"""Espacios por aspecto (voz, estilo, ritmo, producción) para que los motivos del "no" y del
"me gusta" actúen sobre lo que el usuario dice, y no sobre el sonido en general.

Cada espacio sale de una señal distinta y se valida contra una referencia externa:

  voz / timbre : MERT capas 3-6      -> mejor reconocimiento de artista (identidad vocal/instrumental)
  estilo       : MERT capas 9-11     -> pierde identidad pero conserva género; además se le restan
                                        los 4 ejes principales de voz (así "estilo" no es solo "voz")
  ritmo        : BPM, pegada, energía (librosa)  -> diferencia de BPM entre vecinos
  producción   : MERT capas 0-2 + contraste/brillo/energía -> SIN validar (sin señal externa fiable)

Orden del pipeline:  build_deck.py -> genres.py -> features.py -> mert_embed.py
                     -> finalize_deck.py -> aspects.py
"""
import json

import numpy as np

DIMS = 32
VOICE_AXES = 4
RNG = np.random.default_rng(0)


def norm(x):
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-8)


def z(x):
    return (x - x.mean(0)) / (x.std(0) + 1e-8)


def pca(x, k):
    x = x - x.mean(0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    return norm(x @ vt[:min(k, vt.shape[0])].T)


def main():
    deck = json.load(open("cache/deck.json", encoding="utf-8"))
    mert = dict(np.load("cache/mert.npz"))
    feats = np.load("cache/features.npz"); fi = {i: k for k, i in enumerate(feats["ids"])}
    genres = json.load(open("cache/genres.json", encoding="utf-8"))
    T = [t for t in deck["tracks"] if str(t["id"]) in mert and str(t["id"]) in fi]
    ix = [fi[str(t["id"])] for t in T]
    A = np.stack([mert[str(t["id"])] for t in T])           # [N, 12, 768]
    layers = lambda ls: np.hstack([norm(A[:, L] - A[:, L].mean(0)) for L in ls])

    voice_raw = layers(range(3, 7))
    style_raw = layers(range(9, 12))
    voice = pca(voice_raw, DIMS)
    # estilo = capas profundas sin los 4 ejes principales de la voz. En MERT género y voz están
    # entrelazados: quitar más ejes separa más del todo la voz pero destruye el género (0.253 -> 0.217).
    Xv = voice_raw - voice_raw.mean(0); Ys = style_raw - style_raw.mean(0)
    _, _, Vt = np.linalg.svd(Xv, full_matrices=False)
    scores = Xv @ Vt[:VOICE_AXES].T
    style = pca(Ys - scores @ np.linalg.lstsq(scores, Ys, rcond=None)[0], DIMS)
    f = lambda k: feats[k][ix]
    rhythm = norm(z(np.hstack([f("tempo"), f("rhythm"), f("energy")])))
    low = norm(z(np.hstack([f("timbre")[:, 40:], f("energy")])))
    prod = pca(np.hstack([layers(range(0, 3)), 0.7 * low * np.sqrt(layers(range(0, 3)).shape[1] / low.shape[1])]), DIMS)
    spaces = {"voice": voice, "style": style, "rhythm": rhythm, "prod": prod}

    # estadísticos de similitud por espacio: la app los usa para comparar aspectos en la misma escala (z)
    stats, sims = {}, {}
    iu = np.triu_indices(len(T), 1)
    for name, X in spaces.items():
        S = X @ X.T
        sims[name] = S[iu]
        stats[name] = {"mu": round(float(sims[name].mean()), 4), "sigma": round(float(sims[name].std()), 4)}

    # --------------------------------------------------------------- validación
    aid = np.array([t["artist_id"] for t in T])
    gs = [set(genres[str(t["id"])]["genres"]) for t in T]
    bpm = np.array([f("tempo")[i, 0] for i in range(len(T))])
    jac = lambda a, b: len(a & b) / len(a | b) if (a | b) else 0
    has = [i for i in range(len(T)) if (aid == aid[i]).sum() > 1]

    def neighbours(X, same_artist=True):
        S = X @ X.T; np.fill_diagonal(S, -9)
        if not same_artist:
            S[aid[:, None] == aid[None, :]] = -9
        return np.argsort(-S, 1)[:, :5]

    print("\nValidación de cada espacio (referencias externas):")
    base_g = np.mean([jac(gs[i], gs[j]) for i in range(len(T)) for j in range(len(T)) if aid[i] != aid[j]])
    base_b = np.mean([np.mean(np.abs(bpm[i] - bpm)) for i in range(len(T))])
    print(f"  azar: mismo artista top5 {5 / len(T):.2f} | género {base_g:.2f} | dif. BPM (log2) {base_b:.2f}")
    for name, X in spaces.items():
        o = neighbours(X); ox = neighbours(X, same_artist=False)
        same = np.mean([any(aid[o[i]] == aid[i]) for i in has])
        gen = np.mean([np.mean([jac(gs[i], gs[j]) for j in ox[i]]) for i in range(len(T))])
        bp = np.mean([np.mean(np.abs(bpm[i] - bpm[ox[i]])) for i in range(len(T))])
        print(f"  {name:7s} mismo artista top5 {same:.2f} | género {gen:.2f} | dif. BPM {bp:.2f}")
    print("\nCorrelación entre las similitudes de cada par de espacios (más baja = aspectos más distintos):")
    names = list(spaces)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            print(f"  {a:6s} ~ {b:6s} {np.corrcoef(sims[a], sims[b])[0, 1]:+.2f}")

    # --------------------------------------------------------------- guardar
    for k, t in enumerate(T):
        t["a"] = {name: [round(float(x), 3) for x in X[k]] for name, X in spaces.items()}
    deck["tracks"] = T
    deck["aspects"] = stats
    json.dump(deck, open("cache/deck.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("\naspectos guardados en cache/deck.json:", stats)


if __name__ == "__main__":
    main()
