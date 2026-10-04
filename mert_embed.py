"""Embeddings MERT-v1-95M (modelo de música) de cada preview: media por capa y por tiempo."""
import json, sys, numpy as np, torch, librosa
from transformers import AutoModel, Wav2Vec2FeatureExtractor
M = "m-a-p/MERT-v1-95M"
model = AutoModel.from_pretrained(M, trust_remote_code=True).eval()
proc = Wav2Vec2FeatureExtractor.from_pretrained(M, trust_remote_code=True)
sr = proc.sampling_rate
d = json.load(open("cache/deck.json", encoding="utf-8"))
out = {}
caps = []
for l in model.encoder.layers:   # el código remoto de MERT no devuelve hidden_states con transformers 5
    l.register_forward_hook(lambda m, i, o: caps.append(o[0] if isinstance(o, tuple) else o))
for i, t in enumerate(d["tracks"], 1):
    y, _ = librosa.load(f"cache/audio/{t['id']}.mp3", sr=sr, mono=True)
    inp = proc(y, sampling_rate=sr, return_tensors="pt")
    caps.clear()
    with torch.no_grad():
        model(**inp)
    out[str(t["id"])] = torch.stack(caps).squeeze(1).mean(1).numpy()    # [12, 768]
    print(f"\r{i}/{len(d['tracks'])}", end="", flush=True)
    if i % 40 == 0: np.savez("cache/mert.npz", **out)
np.savez("cache/mert.npz", **out); print("\nlisto")
