"""Características de audio clásicas (tempo, timbre, energía) para cada preview del catálogo.
Incremental: solo calcula las canciones que aún no están en cache/features.npz."""
import json, os, sys
from multiprocessing import Pool
import librosa, numpy as np

SR = 22050

def feats(path):
    y, _ = librosa.load(path, sr=SR, mono=True)
    onset = librosa.onset.onset_strength(y=y, sr=SR)
    tempo = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=onset, sr=SR))[0])
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=20)
    chroma = librosa.feature.chroma_stft(S=S, sr=SR)
    contrast = librosa.feature.spectral_contrast(S=S, sr=SR)
    cent = librosa.feature.spectral_centroid(S=S, sr=SR)
    bw = librosa.feature.spectral_bandwidth(S=S, sr=SR)
    roll = librosa.feature.spectral_rolloff(S=S, sr=SR)
    zcr = librosa.feature.zero_crossing_rate(y)
    rms = librosa.feature.rms(S=S)
    ms = lambda a: np.concatenate([a.mean(1), a.std(1)])
    return {
        "tempo": np.array([np.log2(tempo)]),
        "rhythm": np.array([onset.mean(), onset.std()]),
        "energy": ms(np.vstack([rms, zcr])),
        "timbre": np.concatenate([ms(mfcc), ms(contrast), ms(np.vstack([cent, bw, roll]))]),
        "harmony": chroma.mean(1),
    }

def work(a):
    tid, path = a
    try: return tid, feats(path)
    except Exception as e: return tid, None

if __name__ == "__main__":
    d = json.load(open("cache/catalog.json", encoding="utf-8"))
    out = {}
    if os.path.exists("cache/features.npz"):
        z = np.load("cache/features.npz")
        out = {str(i): {b: z[b][k] for b in z.files if b != "ids"} for k, i in enumerate(z["ids"])}
    jobs = [(str(t["id"]), f"cache/audio/{t['id']}.mp3") for t in d["tracks"]
            if str(t["id"]) not in out and os.path.exists(f"cache/audio/{t['id']}.mp3")]
    print(f"{len(out)} ya calculadas, {len(jobs)} nuevas")
    if not jobs:
        raise SystemExit(0)
    with Pool(6) as p:
        for i, (tid, f) in enumerate(p.imap_unordered(work, jobs), 1):
            if f: out[tid] = f
            print(f"\r{i}/{len(jobs)}", end="", flush=True)
    blocks = list(next(iter(out.values())))
    np.savez("cache/features.npz", ids=np.array(list(out)), **{b: np.stack([out[i][b] for i in out]) for b in blocks})
    print("\nlisto", len(out))
