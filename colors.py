"""Color dominante de cada portada, para teñir la pantalla con el color de la canción.

Se calcula una vez al generar el mazo (no en el navegador: las portadas vienen de otro dominio y
leer sus píxeles exige permisos CORS que no están garantizados). Escribe `color` en cache/deck.json.
Debe ejecutarse DESPUÉS de finalize_deck.py y aspects.py, que regeneran el mazo.
"""
import colorsys
import io
import json
import os

import requests
from PIL import Image


def dominant(img, k=8):
    """Color más 'vivo' entre los k dominantes: prioriza saturación sin ignorar cuánto ocupa."""
    small = img.convert("RGB").resize((64, 64))
    q = small.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:k * 3]
    counts = sorted(q.getcolors(), reverse=True)           # [(n, índice)]
    total = sum(n for n, _ in counts)
    best, best_score = None, -1
    for n, i in counts:
        r, g, b = pal[i * 3:i * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < .18 or (v > .96 and s < .1):                 # casi negro o casi blanco: no tiñe
            continue
        score = (n / total) ** .5 * (.25 + s) * (1 - abs(v - .65) * .6)
        if score > best_score:
            best, best_score = (r, g, b), score
    if best is None:                                        # portada casi monocroma: el más frecuente
        i = counts[0][1]; best = tuple(pal[i * 3:i * 3 + 3])
    return "#%02x%02x%02x" % best


def main():
    deck = json.load(open("cache/deck.json", encoding="utf-8"))
    cache = json.load(open("cache/colors.json", encoding="utf-8")) if os.path.exists("cache/colors.json") else {}
    for i, t in enumerate(deck["tracks"], 1):
        url = t["cover"]
        if url not in cache:
            print(f"\r{i}/{len(deck['tracks'])}", end="", flush=True)
            try:
                cache[url] = dominant(Image.open(io.BytesIO(requests.get(url, timeout=15).content)))
            except Exception:
                cache[url] = "#6b6258"                      # gris cálido neutro si falla la descarga
        t["color"] = cache[url]
    json.dump(cache, open("cache/colors.json", "w", encoding="utf-8"))
    json.dump(deck, open("cache/deck.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n{len(set(cache.values()))} colores distintos en {len(cache)} portadas")


if __name__ == "__main__":
    main()
