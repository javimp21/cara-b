"""Ejecuta, en orden, todos los pasos que convierten el catálogo en el mazo de la app.

Cada paso es incremental: solo calcula lo que no estaba ya en caché, así que tras ampliar el catálogo
(`python build_deck.py --extend ...`) basta con volver a lanzar esto.

  python pipeline.py
"""
import subprocess
import sys
import time

STEPS = [
    ("genres.py", "géneros y año (referencias para validar los aspectos)"),
    ("features.py", "características de audio clásicas (tempo, timbre, energía)"),
    ("mert_embed.py", "vectores de audio MERT"),
    ("finalize_deck.py", "mazo: vectores, novedad y medidas interpretables"),
    ("aspects.py", "espacios por aspecto (voz, estilo, ritmo, producción)"),
    ("colors.py", "color dominante de cada portada"),
]

for script, what in STEPS:
    t0 = time.time()
    print(f"\n=== {script}: {what}", flush=True)
    subprocess.run([sys.executable, script], check=True)
    print(f"--- {script}: {time.time() - t0:.0f} s", flush=True)
print("\nListo: cache/deck.json actualizado.")
