"""Géneros y año de lanzamiento de Deezer por canción (vía su álbum). Son referencias externas para
validar qué representación del audio captura el 'estilo' y la 'producción' (la época marca el sonido).
Cachea en cache/genres.json."""
import json
from pathlib import Path

from discover import dz, save_api_cache

OUT = Path("cache/genres.json")


def main():
    deck = json.load(open("cache/catalog.json", encoding="utf-8"))
    genres = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    albums = {}
    for i, t in enumerate(deck["tracks"], 1):
        key = str(t["id"])
        if isinstance(genres.get(key), dict):
            continue
        print(f"\r{i}/{len(deck['tracks'])}", end="", flush=True)
        album = dz(f"/track/{t['id']}").get("album", {}).get("id")
        if album not in albums:
            a = dz(f"/album/{album}") if album else {}
            albums[album] = {"genres": [g["name"] for g in a.get("genres", {}).get("data", [])],
                             "year": int(a["release_date"][:4]) if a.get("release_date") else None}
        genres[key] = albums[album]
        if i % 50 == 0:
            OUT.write_text(json.dumps(genres, ensure_ascii=False), encoding="utf-8")
    OUT.write_text(json.dumps(genres, ensure_ascii=False), encoding="utf-8")
    print()
    from collections import Counter
    print(Counter(g for v in genres.values() for g in v["genres"]).most_common(12))


if __name__ == "__main__":
    main()
