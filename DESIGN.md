# Cara B: guía de diseño

Fuente de verdad del aspecto de la app. Los valores salen de `cache/base.css` (estructura) y `cache/themes/tape.css` (el tema por defecto, el casete). Si cambias un valor en el CSS, cámbialo aquí también.

## Idea

Un casete con su caja. La portada es el inserto, el título y el artista van en **tiras de etiquetadora** (plástico negro con letras blancas en relieve), los botones son **teclas de pletina** y la lista de descubiertas es el **tracklist** de la caja. Es minimalista: no hay texto de ayuda, ni idioma ni fans sobre la portada, ni líneas decorativas.

Lo que no queremos: el aspecto genérico de IA (degradados morados, tarjetas de cristal, serif cursiva "editorial", emojis como iconos, tipografías por defecto de plantilla).

## Colores

| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| `--bg` | `#e4dcc9` | `#1b2321` | fondo (con rayado horizontal casi invisible) |
| `--surface` | `#cfc6b2` | `#2d3835` | cuerpo de la tarjeta |
| `--surface2` | `#bdb39d` | `#37443f` | superficies secundarias |
| `--fg` | `#1d1b17` | `#eee7d4` | texto y bordes |
| `--muted` | `#5d574b` | `#a3ad9f` | texto secundario |
| `--line` | = `--fg` | = `--fg` | bordes (siempre del color del texto, de 2 px) |
| `--acc` | `#ff5a1f` | `#ff7a3d` | acción principal, selección, progreso |
| `--acc-fg` | `#fff` | `#1a120c` | texto sobre `--acc` |
| `--nope` | `#d6361d` | `#d6361d` | "no", bloquear |
| `--label` | `#f6f0df` | igual | papel de la etiqueta y de las hojas |
| `--teal` | `#1f8a86` | igual | sello "me gusta" |
| `--tape` / `--tape-ink` | `#171614` / `#f3f0e6` | igual | tira de etiquetadora |

Tintas fijas sobre `--label` (no cambian con el modo oscuro): texto `#1d1b17`, secundario `#5d574b`. Hoy están repetidas a mano en `tape.css`; si se amplía el tema, conviene convertirlas en `--ink` y `--ink-muted`.

**Color de la canción.** Cada canción tiene `--song` (color dominante de su portada, calculado por `colors.py`) y `--song-ink` (negro o blanco según su luminosidad, calculado en `app.html`). Se usa solo en el borde superior de la etiqueta y en la tira del artista. No se usa en botones ni en texto.

## Tipografía

- Una sola familia: **Nunito** (Google Fonts, licencia abierta). Redondeada, parecida a las tiras de Dymo reales. Fallback: `Arial Rounded MT Bold`, `sans-serif`.
- Tiras: peso 900, mayúsculas, `letter-spacing:.07em`. Tienen relieve con `text-shadow` y `-webkit-text-stroke`.
- Títulos grandes (onboarding, hojas, pantalla final): 700, sin mayúsculas, `letter-spacing` ligeramente negativo.
- Texto de interfaz: 15 px base; etiquetas pequeñas 11,5-12 px.

Escala usada: 11,5 · 12,5 · 14,5 · 15 · 17 · 28 · 40-44 · 92 (número grande).

## Forma, borde y sombra

- Bordes: **2 px** sólidos en `--fg`. Nada de bordes finos translúcidos.
- Radios: botones y chips **6 px**, tarjeta 12 px, etiqueta `6 6 26 26`, hojas `14 14 0 0`, tiras 3 px. Los círculos solo para carretes y puntos de progreso.
- Sombras: la tarjeta usa `--shadow`; los botones tienen una sombra **dura** y sin desenfoque, `0 5px 0 var(--fg)`, que al pulsar baja 4 px (efecto de tecla).
- Sin degradados salvo en las tiras (negro brillante) y en los botones (leve brillo de plástico).

## Componentes

| Componente | Reglas |
|---|---|
| Tarjeta | caja con borde 2 px; portada con marco `--label` de 5 px; etiqueta con borde superior de 11 px en `--song` |
| Carretes | dos discos de 34 px en una ventana oscura; giran (`spin 2.2s`) mientras suena y se paran en pausa |
| Botón de pletina | 74×56 (me gusta 86×62), borde 2 px, sombra dura; "me gusta" naranja, "no" crema; "ya la conozco" es solo texto |
| Chip | borde 2 px, radio 6; activo = `--acc` (en hojas, tinta negra) |
| Tira (`.strip`) | fondo negro con degradado, letras `--tape-ink`, ligeramente rotada (-2° en la cabecera, -1° en los días) |
| Hoja inferior | papel `--label`, borde 2 px y borde superior de 11 px en `--acc` |
| Lista | numerada `01, 02…` como un tracklist; imagen 46 px con marco de papel |
| Barra | 10 px, borde 2 px, relleno `--acc`, sin radio |

## Movimiento

Corto y mecánico: la tecla baja en 80 ms, los carretes giran sin parar mientras suena, la tarjeta entra con `cardIn` (550 ms). Todo se desactiva con `prefers-reduced-motion`.

## Reglas para cambios

1. Usa los tokens; no escribas colores nuevos en el CSS.
2. Toda tira (título, sección, día) usa la clase `.strip` o el mismo bloque de estilos de `tape.css`.
3. Un tema nuevo es un archivo en `cache/themes/` que solo redefine los tokens y las reglas de `tape.css` que cambien; la estructura vive en `base.css`.
4. Comprueba siempre claro y oscuro, y que nada ensanche la pantalla en móvil (`overflow-x:clip`).
5. Antes de añadir texto o decoración, pregúntate si se puede quitar: la dirección es minimalista.
6. Texto de interfaz en español, con tuteo y frases cortas.
