# Music Discovery

Prototipo de una app de recomendación musical con tarjetas tipo Tinder, pensada para escapar de los artistas de siempre: recomienda música parecida a la que te gusta que no sea la típica que ya conoce todo el mundo, y prioriza los idiomas que tú eliges.

> Estado: prototipo funcional (mazo estático generado a partir de unos artistas semilla). No es todavía una app con usuarios ni backend.

## Qué hace

- **Tarjetas con preview de 30 s** que suena sola. Desliza a la derecha (me gusta), a la izquierda (no) o hacia arriba (ya lo conozco). También con las teclas ← → ↑.
- **Motivos opcionales** en cada voto: por qué no (voz, ritmo, estilo, producción…) o qué te gusta. Al dar un "me gusta" salen enlaces a Spotify, YouTube Music, Apple Music y Tidal.
- **"Ya lo conozco" neutro**: no cuenta como "no", pregunta si te gusta, te da igual o no te gusta, y no gasta una de las 5 del día.
- **5 recomendaciones al día**, pensadas como hábito diario.
- **Idiomas**: un idioma principal y hasta 4 más por orden de preferencia, con un control de cuánta música quieres en el principal.
- **Sección "Descubiertas"**: lista de las canciones nuevas que te han gustado, agrupadas por el día en que las descubriste. Al pulsar una se despliegan los enlaces a Spotify, YouTube Music, Apple Music, Tidal y Deezer.
- **Control del usuario**: "Cambiar de opinión" tras un swipe y "No recomendar más a este artista".
- **El sistema aprende en el navegador** con cada voto: sube lo parecido a lo que te gusta, aleja lo parecido a lo que descartas según el motivo, y ajusta el peso de los idiomas y de la novedad.
- **Explicaciones honestas**: solo dice "parecida a X" si el parecido es alto dentro del mazo, y lo explica con medidas reales (tempo, energía, brillo), no con etiquetas inventadas.

## Cómo funciona

```
artistas semilla
   │  Deezer API: artistas relacionados (2 saltos) + sus canciones top + previews
   ▼
filtro de popularidad RELATIVA (se descarta el ~12 % más famoso del grafo)
   │
   ├─ idioma de cada canción:  letra (LRCLIB) > idioma del artista > audio (Whisper) + título
   ├─ embedding de audio:      MERT-v1-95M, capas 4-7, PCA a 128 dimensiones
   └─ medidas interpretables:  BPM, energía, brillo, pegada rítmica (librosa)
   ▼
cache/deck.json  ──►  cache/app.html (recomendador en JavaScript, sin backend)
```

Decisiones técnicas que merecen mención:

- **Spotify no sirve como fuente de datos.** Desde nov. 2024 su API corta recomendaciones, artistas relacionados, audio features y previews a las apps nuevas. Se usa Deezer (previews y relacionados gratis, sin clave) y LRCLIB (letras).
- **CLAP se descartó.** Es el primer modelo que probé, y agrupa por "género general": ante la pregunta "¿el vecino más cercano de una canción es otra del mismo artista?" acierta el 3 %. MERT, entrenado solo con música, acierta el 12 % (25 % entre los 5 más cercanos). Combinarlo con características clásicas no mejoraba.
- **La detección de idioma por audio (Whisper) no es fiable en música** (marcaba "Ay Mamá" como inglés), así que se usa solo como último recurso tras la letra y el idioma del artista.
- **La popularidad es relativa al grafo**, no un umbral fijo de fans: los fans de Deezer no son comparables entre países.

## Uso

Requiere Python 3.10+. La primera ejecución descarga los modelos (CLAP ≈ 800 MB, Whisper ≈ 500 MB, MERT ≈ 400 MB); en CPU, generar un mazo de ~250 canciones tarda más de una hora.

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

# 1) mazo base: grafo de artistas, previews, idiomas
python build_deck.py --seeds "Artista 1, Artista 2, Artista 3"
# 2) medidas clásicas de audio y embeddings MERT
python features.py
python mert_embed.py
# 3) vectores finales + datos para las explicaciones
python finalize_deck.py

# probar la app
python -m http.server 8765 -d cache
# abrir http://localhost:8765/app.html
```

En `cache/` hay ya un mazo generado con `Barry B, Sanguijuelas del Guadiana, Venturi`. Esa carpeta no se sube a git (los datos y las previews, que tienen copyright, se regeneran con el pipeline); solo se versiona `cache/app.html`. `discover.py` es el prototipo inicial en forma de informe HTML y también contiene las funciones de Deezer que usa el resto.

## Archivos

| Archivo | Para qué |
|---|---|
| `discover.py` | Cliente de Deezer con caché, descarga de previews y prototipo inicial con CLAP |
| `build_deck.py` | Construye el mazo: grafo, filtro de popularidad, idiomas |
| `features.py` | BPM, energía, timbre y armonía con librosa |
| `mert_embed.py` | Embeddings MERT por capas (con hooks, por compatibilidad con transformers 5) |
| `finalize_deck.py` | Sustituye los vectores por los de MERT y añade las medidas interpretables |
| `cache/app.html` | La app de tarjetas (HTML, CSS y JS en un archivo) |

## Pendiente

- Separar de verdad los motivos del "no" (voz frente a ritmo) en lugar de pesos distintos sobre el mismo vector.
- Mazos para varios idiomas: ahora el mazo sale de artistas en español y apenas hay inglés.
- Importar gustos desde Last.fm o una playlist, además del formulario de onboarding.
- Backend y cuentas de usuario para guardar los votos y generar las 5 del día.
- Evaluar con más usuarios que solo yo.
