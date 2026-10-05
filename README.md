# Cara B

*Lo que no suena en la cara A.*

Cara B es un prototipo de app de recomendación musical con tarjetas tipo Tinder, pensada para escapar de los artistas de siempre: recomienda música parecida a la que te gusta que no sea la típica que ya conoce todo el mundo, y prioriza los idiomas que tú eliges. El nombre viene de la cara B de los discos, donde estaban las joyas que no se anunciaban.

> Estado: prototipo funcional (mazo estático generado a partir de unos artistas semilla). No es todavía una app con usuarios ni backend.

## Qué hace

- **Tarjetas con preview de 30 s** que suena sola. Desliza a la derecha (me gusta), a la izquierda (no) o hacia arriba (ya lo conozco). También con las teclas ← → ↑.
- **Motivos opcionales** en cada voto: por qué no (voz, ritmo, estilo, producción…) o qué te gusta. Al dar un "me gusta" salen enlaces a Spotify, YouTube Music, Apple Music y Tidal.
- **"Ya lo conozco" neutro**: no cuenta como "no", pregunta si te gusta, te da igual o no te gusta, y no gasta una de las 5 del día.
- **5 recomendaciones al día**, pensadas como hábito diario.
- **Idiomas**: un idioma principal y hasta 4 más por orden de preferencia, con un control de cuánta música quieres en el principal.
- **Sección "Descubiertas"**: lista de las canciones nuevas que te han gustado, agrupadas por el día en que las descubriste. Al pulsar una se despliegan los enlaces a Spotify, YouTube Music, Apple Music, Tidal y Deezer.
- **Modo desarrollo (`?dev`)**: añade la pestaña "Evaluación", que guarda cada voto con su contexto y mide si el sistema acierta más que el azar (ver *Evaluación*), y mezcla 1 de cada 5 canciones elegidas al azar como grupo de control. Es una herramienta para validar el sistema, no parte de la experiencia de un usuario final, así que está oculta por defecto.
- **Control del usuario**: "Cambiar de opinión" tras un swipe y "No recomendar más a este artista".
- **El sistema aprende en el navegador** con cada voto: sube lo parecido a lo que te gusta, aleja lo parecido a lo que descartas y ajusta cuánta novedad busca.
- **Los motivos actúan sobre lo que dices**: "no me gusta la voz" aleja canciones con esa voz o timbre pero no las de ritmo parecido, y "me gusta el ritmo" atrae canciones de ritmo parecido. Ver *Aspectos del sonido* más abajo.
- **Sin sobreexplicar**: la tarjeta dice solo "Muy parecida a X" cuando el parecido es alto dentro del mazo (y "Para ampliar tu gusto" cuando no), sin listar razones que el sistema no puede justificar.

## Diseño

Dirección visual **casete** (la letra de la esquina de la etiqueta es siempre una **B**): la portada es el inserto de la caja y debajo va el casete, con una etiqueta de la que cuelgan el título y el artista en **tiras de etiquetadora** (plástico negro con letras en relieve; la del artista toma el color de la canción), una franja del color de cada portada y dos carretes que giran mientras suena. Los botones son teclas de pletina. Sigue el tema claro u oscuro del sistema.

- **El punto de partida fue evitar la estética típica de interfaz generada por IA**: nada de degradados morados, de Inter ni de etiquetas en mayúsculas monoespaciadas con letra separada, y la forma de las piezas sale del objeto (casete, etiquetadora) y no de una plantilla. La tipografía sale del objeto: Nunito, de letras redondeadas, que es lo más parecido a las tiras de Dymo reales, elegida entre siete candidatas (grotescas, redondeadas y condensadas) en una comparativa lado a lado, y no de una lista de fuentes de moda. Las tiras se dibujan con CSS: la fuente Dymo más conocida tiene licencia solo para uso personal, así que no se incluye.
- **Minimalismo deliberado**: sin etiquetas de idioma ni de fans sobre la portada, sin texto de ayuda bajo los botones y con los ajustes secundarios plegados en «Más ajustes». La tarjeta dice solo «Muy parecida a X».
- **Otras tres direcciones exploradas**, todas funcionales: `fanzine` (fotocopia, letras recortadas), `crate` (caja de discos) y `riso` (cartel de risografía, con cada canción impresa en la tinta de su portada). Se ven una al lado de otra en `cache/themes.html` y se activan con `app.html?theme=nombre`; añadir `?themes` muestra un botón para ir cambiando.
- **Arquitectura de estilos**: `cache/base.css` (estructura y tema por defecto) más un `cache/themes/<nombre>.css` que lo sobrescribe, sin frameworks ni dependencias de interfaz. El color dominante de cada portada se calcula una vez al generar el mazo (`colors.py`), porque las portadas vienen de otro dominio y leer sus píxeles en el navegador exige permisos CORS.
- Respeta `prefers-reduced-motion` y `prefers-color-scheme`.

## Cómo funciona

```
artistas semilla
   │  Deezer API: artistas relacionados (2 saltos) + sus canciones top + previews
   ▼
filtro de popularidad RELATIVA (se descarta el ~12 % más famoso del grafo)
   │
   ├─ idioma de cada canción:  letra (LRCLIB) > idioma del artista > audio (Whisper) + título
   ├─ embedding de audio:      MERT-v1-95M, capas 4-7, PCA a 128 dimensiones
   ├─ medidas interpretables:  BPM, energía, brillo, pegada rítmica (librosa)
   └─ espacios por aspecto:    voz, estilo, ritmo, producción (aspects.py)
   ▼
cache/deck.json  ──►  cache/app.html (recomendador en JavaScript, sin backend)
```

Decisiones técnicas que merecen mención:

- **Spotify no sirve como fuente de datos.** Desde nov. 2024 su API corta recomendaciones, artistas relacionados, audio features y previews a las apps nuevas. Se usa Deezer (previews y relacionados gratis, sin clave) y LRCLIB (letras).
- **CLAP se descartó.** Es el primer modelo que probé, y agrupa por "género general": ante la pregunta "¿el vecino más cercano de una canción es otra del mismo artista?" acierta el 3 %. MERT, entrenado solo con música, acierta el 12 % (25 % entre los 5 más cercanos). Combinarlo con características clásicas no mejoraba.
- **La detección de idioma por audio (Whisper) no es fiable en música** (marcaba "Ay Mamá" como inglés), así que se usa solo como último recurso tras la letra y el idioma del artista.
- **La popularidad es relativa al grafo**, no un umbral fijo de fans: los fans de Deezer no son comparables entre países.

## Aspectos del sonido

Cuando dices "no me gusta la voz" o "me gusta el ritmo", el sistema debe actuar solo sobre esa dimensión. Para eso cada canción tiene un espacio por aspecto, y `aspects.py` los valida contra referencias externas (identidad de artista, géneros de Deezer, BPM):

| Aspecto | Señal | Referencia | Resultado |
|---|---|---|---|
| Voz / timbre | MERT capas 3-6 | mismo artista en los 5 vecinos | 0,21 (azar 0,02) |
| Ritmo | BPM, pegada, energía (librosa) | diferencia de BPM entre vecinos | 0,11 (azar 0,26) |
| Estilo | MERT capas 9-11 sin los 4 ejes principales de voz | géneros de Deezer | 0,25 (azar 0,23) |
| Producción | MERT capas 0-2 + contraste/brillo | ninguna fiable | sin validar, pesa la mitad |

Lo que salió bien y lo que no:

- **El ritmo y la voz se separan limpiamente** (correlación entre sus similitudes: +0,42) y están validados.
- **El estilo es débil.** En MERT el género y la voz están entrelazados: quitar los 4 ejes principales de voz deja las capas profundas casi sin identidad de artista y conserva el género; quitar más lo destruye (0,25 → 0,22). Mi primer intento, una "huella de géneros" con CLAP, quedó igual que el azar y lo descarté.
- **La producción no se pudo validar.** El mazo es muy homogéneo (casi todo de 2015-2026, mayoría pop/indie), así que ni el año de lanzamiento ni los géneros discriminan. Está implementada pero con peso reducido, a la espera de más datos.
- **Efecto comprobado:** al marcar la misma canción con "no" por voz, ritmo o estilo, las 15 canciones más penalizadas casi no coinciden entre sí (2 de 15 entre voz y ritmo). "Idioma" y "demasiado conocido" no tocan el sonido.

## Evaluación

Medir si las recomendaciones son buenas exige comparar con algo. Cada voto se guarda con la puntuación que tenía la canción cuando se la serví, si la eligió el modelo o el azar (grupo de control, 1 de cada 5 en modo evaluación) y la ronda. La pestaña **Evaluación** (solo visible con `?dev` en la URL, no está pensada para usuarios finales) calcula, solo sobre canciones nuevas (los "ya lo conozco" no cuentan):

- **Tasa de aciertos** del modelo frente al control, con intervalo de confianza del 95 % (Wilson). No afirma que el modelo supera al azar hasta que los intervalos dejan de solaparse.
- **Aciertos por ronda**, para ver si mejora con el uso.
- **AUC**: probabilidad de que una canción que te gustó tuviera más puntuación que una que no (0,50 = azar), con el sistema aprendiendo y sin aprender. Se calcula también solo sobre las de control, que no tienen sesgo de selección.
- **Exportar votos (JSON)** para analizarlos fuera.

La lógica del recomendador vive en `cache/recommender.js`, sin nada de interfaz, así que la app y la simulación ejecutan exactamente el mismo código.

## Simulación con usuarios sintéticos

Esperar semanas de uso real no es práctico, así que `sim/simulate.js` ejecuta el recomendador con usuarios simulados de gusto conocido: 12 rondas de 5 votos, 60 simulaciones por celda, intervalos del 95 % entre paréntesis. Les gusta una canción con probabilidad 0,85 si encaja con su perfil y 0,12 si no. Tres perfiles se definen por géneros de Deezer, un metadato externo al audio, para que la prueba no sea circular; el cuarto por BPM.

| Perfil (qué parte del mazo encaja) | Azar | Sin aprender | Modelo | Modelo, rondas 1-3 |
|---|---|---|---|---|
| rock / indie (34 %) | 36 % (±2) | 43 % (±1) | 44 % (±1) | 57 % (±2) |
| latino / flamenco (37 %) | 39 % (±1) | 31 % (±1) | 35 % (±1) | 25 % (±2) |
| pop indie / electro (15 %) | 24 % (±1) | 22 % (±1) | 22 % (±1) | 25 % (±2) |
| ritmo rápido ≥125 BPM (46 %) | 44 % (±1) | 57 % (±1) | 59 % (±1) | 66 % (±3) |

Lo que se ve, incluido lo que no sale bien:

- **Si el gusto se parece a los artistas de partida, el sistema acierta mucho más que el azar al principio** (57 % frente a 35 % en las primeras rondas), pero aprender de los votos añade poco sobre usar solo esas semillas (44 % frente a 43 %).
- **Arranque en frío.** Con un gusto distinto al de las semillas (latino / flamenco) empieza por debajo del azar (25 % frente a 38 %): las semillas pesan demasiado. Sí aprende (sube del 25 % al 43 % hacia la ronda 10), pero lento.
- **Con géneros que el audio no refleja** (pop indie / electro) no mejora al azar. Coincide con la validación de *Aspectos del sonido*: el estilo es la señal más débil.
- **Dar motivos ayuda.** En el perfil de ritmo, un usuario que dice "es por el ritmo" cuando rechaza consigue un 59 % frente al 55 % de quien no da motivos, y la diferencia crece en las últimas rondas (54 % frente a 48 %).
- **La caída de las rondas 10-12 en rock es un artefacto del mazo pequeño** (132 artistas): las canciones que encajan se agotan. No pasaría con un catálogo grande.
- **La pestaña Evaluación detecta estos mismos casos** sobre el log de las simulaciones: rock 47 % del modelo frente a 32 % del control; latino 35 % frente a 41 %; pop indie / electro 24 % frente a 24 %; ritmo 58 % frente a 41 %. El AUC sobre el control queda entre 0,48 y 0,59 (0,50 = azar), es decir, el sistema ordena solo un poco mejor que el azar.

Limitaciones: son usuarios sintéticos, los géneros de Deezer son ruidosos (nivel de álbum) y el perfil de ritmo comparte parte de su señal con el espacio de ritmo del sistema, así que prueba el mecanismo de motivos y no la calidad de las recomendaciones. Los números de gente real serán los que cuenten.

```bash
node sim/simulate.js --runs 60    # ~3 min; escribe sim/results.json
```

### Intentos de mejorar el arranque en frío (resultado negativo)

Con el mismo simulador, `sim/sweep.js` prueba variantes del recomendador (40 simulaciones por celda; media de los cuatro perfiles, y tasa de «me gusta» del perfil latino / flamenco en las rondas 1-3, que es el que arranca peor):

| Variante | Media de perfiles | Latino, rondas 1-3 | Rock, rondas 1-3 |
|---|---|---|---|
| actual | 40 % | 24 % | 57 % |
| semillas pierden peso al acumular «me gusta» (K = 1, 2, 3, 5) | 40-41 % | 23-26 % | 56-57 % |
| «me gusta» pesan ×2,5 | 41 % | 24 % | 58 % |
| semillas pierden peso + «me gusta» ×2,5 | 40 % | 25 % | 59 % |
| explorar al azar el 20 % al principio (decae ×0,85 por ronda) | 41 % | 31 % | 55 % |
| diversidad dentro de la ronda (0,15 / 0,3 / 0,5) | 39-40 % | 24-33 % | 50-54 % |

- **Bajar el peso de las semillas no cambia nada.** Mi hipótesis era que las semillas pesaban demasiado, pero el cuello de botella es otro: si el sistema no sirve canciones de tu gusto real, no recibe «me gusta» de los que aprender. Es un problema de exploración, no de ponderación.
- **Explorar sí ayuda al que parte mal** (24 % → 31 % en las primeras rondas), a costa de 2-4 puntos para quien ya estaba bien servido por sus semillas. En conjunto la mejora (40 % → 41 %) cae dentro del margen de error, así que **no he cambiado los valores por defecto**. Las opciones (`mmr`, `exploreP`, `likeW`, `seedDecayK`) quedan en `cache/recommender.js` por si se quieren activar.
- **El modo evaluación ya explora de forma natural:** el 20 % de canciones de control son al azar y también alimentan el aprendizaje.
- **En la práctica el problema pesa menos de lo que parece**, porque las semillas de un usuario real son los artistas que le gustan. El caso de un gusto que no se parece a nada de lo declarado en el onboarding es el de estrés de la simulación.

### Repetir artistas, con distancia

Antes, un artista dejaba de salir para siempre después de votar una de sus canciones, lo que agota el catálogo muy deprisa. Ahora **una canción no se repite nunca, pero un artista puede volver con otra canción** cuando han pasado suficientes tarjetas, y la espera depende de lo que opinaste de su última canción: tras un «me gusta» vuelve antes (10 tarjetas), tras un «me da igual» a medio plazo (30) y tras un «no» mucho después (60). Que ya conocieras la canción no cambia nada: conocer una canción no es conocer al artista, así que cuenta lo que opinaste de ella. Los artistas bloqueados y las semillas nunca vuelven.

Con el mismo simulador (30 simulaciones por celda, 12 rondas, tasa de «me gusta»):

| Variante | Rock / indie | Media de los cuatro perfiles |
|---|---|---|
| sin repetir artistas | 44 % | 40 % |
| me gusta 10 · no 60 | 51 % | 43 % |
| pronto: 5 · 30 | 52 % | 43 % |
| poco: 20 · 100 | 49 % | 42 % |
| solo repiten los que gustan | 51 % | 43 % |

Repetir a los artistas que gustan es lo que mejora los aciertos (tiene sentido: sus otras canciones se parecen a la que ya te gustó). Repetir a los descartados no aporta nada medible en la simulación (que no incluye votos de «me da igual»), así que esos valores se pueden ajustar sin coste.

## Uso

Requiere Python 3.10+. La primera ejecución descarga los modelos (Whisper ≈ 500 MB, MERT ≈ 400 MB). En CPU, cada canción nueva cuesta unos 5 s (vectores MERT, idioma y características), así que ampliar el catálogo con 1.000 canciones tarda alrededor de hora y media.

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

# 1) catálogo: grafo de artistas relacionados, previews e idioma de cada canción
python build_deck.py --seeds "Artista 1, Artista 2, Artista 3"
# 2) todo lo demás: vectores de audio, aspectos, colores y el mazo que lee la app
python pipeline.py

# probar la app
python -m http.server 8765 -d cache
# abrir http://localhost:8765/app.html
```

### Ampliar el catálogo

El proceso es **incremental**: ampliar solo procesa lo nuevo, nunca rehace lo ya calculado.

```bash
python build_deck.py --extend --hops 3 --max-artists 500   # más artistas parecidos, más lejos en el grafo
python build_deck.py --extend --votes votos.json           # crecer a partir de lo que te ha gustado
python build_deck.py --extend --seeds "Cala Vento, Hinds"  # añadir gustos nuevos (pasan a ser semillas)
python pipeline.py                                         # después de cualquiera de las anteriores
```

`votos.json` se exporta desde la app con `?dev` (pestaña Evaluación). Las ampliaciones mantienen el mismo listón de «no demasiado conocido» que el catálogo original.

En `cache/` hay ya un mazo generado con `Barry B, Sanguijuelas del Guadiana, Venturi`. Esa carpeta no se sube a git (los datos y las previews, que tienen copyright, se regeneran con el pipeline); solo se versionan la app y sus estilos. `discover.py` es el prototipo inicial en forma de informe HTML y también contiene las funciones de Deezer que usa el resto.

## Archivos

| Archivo | Para qué |
|---|---|
| `discover.py` | Cliente de Deezer con caché, descarga de previews y prototipo inicial con CLAP |
| `build_deck.py` | Crea y amplía el catálogo (incremental): grafo de artistas, filtro de popularidad, previews e idioma |
| `pipeline.py` | Ejecuta en orden todos los pasos que convierten el catálogo en el mazo de la app |
| `genres.py` | Géneros y año de Deezer por canción (referencias para validar los aspectos) |
| `features.py` | BPM, energía, timbre y armonía con librosa |
| `mert_embed.py` | Embeddings MERT por capas (con hooks, por compatibilidad con transformers 5) |
| `finalize_deck.py` | Sustituye los vectores por los de MERT y añade las medidas interpretables |
| `colors.py` | Color dominante de cada portada (Pillow), para el teñido de la pantalla |
| `aspects.py` | Espacios por aspecto (voz, estilo, ritmo, producción) y su validación |
| `cache/recommender.js` | Lógica del recomendador (puntuación, siguiente canción, aprendizaje, métricas), sin interfaz |
| `sim/simulate.js` | Simulación con usuarios sintéticos (Node) |
| `sim/sweep.js` | Barrido de parámetros del recomendador con la misma simulación |
| `cache/app.html` | La app de tarjetas (HTML y JavaScript) |
| `cache/base.css`, `cache/themes/` | Estilos: base y una hoja por dirección de diseño |
| `cache/themes.html` | Comparativa de las direcciones de diseño, una al lado de otra |

## De prototipo a producto: el catálogo

**Cuántas canciones hacen falta.** Un usuario que juega a diario consume unas 8 tarjetas al día (5 descubrimientos más las «ya la conocía» y los «no»), unas 3.000 al año. Una canción no se repite nunca, y un artista solo vuelve (con otra canción) tras un tiempo. Además, solo una fracción del catálogo (se estima entre el 10 y el 30 %) encaja con sus idiomas y gustos. Para que no se agote nunca, el catálogo «útil» debería ser 50-100 veces lo que consume: del orden de **100.000-300.000 canciones por idioma principal**. El mazo actual de este prototipo tiene 804 canciones de 489 artistas (con las 3 semillas originales como punto de partida): da para unas semanas de uso, no para un año. Puntuarlo entero en el navegador tarda unos 25 ms por carta; con decenas de miles de canciones hará falta un servidor (estimaciones, no medidas).

**El obstáculo no es técnico, es de derechos.** Deezer, la fuente de este prototipo, indica en sus [normas para desarrolladores](https://developers.deezer.com/guidelines) que *«el almacenamiento local de audio está estrictamente prohibido»* y que el audio no debe poder descargarse. Este proyecto sí guarda las previews en `cache/` para analizarlas y reproducirlas desde local. Eso es razonable para investigación personal (nada se redistribuye ni se sube al repositorio), pero **no se puede convertir en un servicio público tal cual**. La [API de búsqueda de iTunes](https://performance-partners.apple.com/search-api) tampoco lo resolvería: sus previews son solo para promocionar contenido de la tienda, en streaming y sin guardarse. Y Spotify cerró en noviembre de 2024 las recomendaciones, el análisis de audio y las previews a las aplicaciones nuevas.

**Cómo sería un camino realista:**

1. **Un catálogo con derechos.** Hay tres vías, y se pueden combinar: un acuerdo comercial con un proveedor de catálogo o de previews (Deezer, Apple y otros); un catálogo **aportado por los propios artistas**, que suben su música aceptando una licencia (encaja con la idea de monetizar por el lado del artista); y música con licencia abierta como relleno (Jamendo, Free Music Archive). Para escuchar la canción completa, reproductores oficiales incrustados y enlaces, sin alojar audio.
2. **Analizar el audio una sola vez, sobre material con derechos**, en un servidor con GPU. Solo se guardan los vectores (128 números por canción, unos 0,5 KB): un millón de canciones caben en medio gigabyte. Con MERT en GPU serían del orden de 5-15 horas de GPU en total (estimación; en la CPU de este prototipo serían semanas), y la ingesta de novedades sería nocturna e incremental, como ya lo es este pipeline.
3. **Un servidor en lugar del navegador.** Hoy la app puntúa todas las canciones en el navegador, algo que aguanta unos pocos miles. Con un catálogo grande haría falta un índice vectorial (pgvector o FAISS) que devuelva los vecinos más cercanos a tu gusto, filtrados por idioma, novedad y artistas ya vistos, y que genere las 5 del día. La app solo pediría y votaría.
4. **Crecer con cada usuario.** Los «me gusta» de la gente alimentan el grafo y los artistas que gustan traen nuevos parecidos: es lo que hace ya `--extend --votes`, a escala.

## Pendiente

- Aislar la voz con separación de fuentes (p. ej. Demucs) para que "la voz" no dependa del timbre general, y validar mejor estilo y producción con un catálogo más variado.
- Mazos para varios idiomas: ahora el mazo sale de artistas en español y apenas hay inglés.
- Importar gustos desde Last.fm o una playlist, además del formulario de onboarding.
- Backend y cuentas de usuario para guardar los votos y generar las 5 del día.
- Evaluar con más usuarios que solo yo.
- Arranque en frío: ajustar pesos o añadir exploración simple no basta (ver arriba). Lo que probablemente ayude es un onboarding que cubra más gustos y un modelo de preferencias entrenado con los votos, en vez de vecinos más cercanos.
