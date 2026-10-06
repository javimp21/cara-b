---
name: cara-b-design
description: Use when creating or changing any UI in Cara B (app.html, base.css, themes/tape.css): new screens, components, colors, typography or copy. Keeps the cassette look consistent and avoids generic AI-style design.
---

# Cara B: diseño de interfaz

Antes de tocar el aspecto, lee `DESIGN.md` en la raíz del repo. Es la fuente de verdad de colores, tipografía, formas y componentes.

## Cómo trabajar

1. Lee `DESIGN.md` y las reglas de `cache/themes/tape.css` para el componente que vas a cambiar.
2. Reutiliza tokens (`--bg`, `--acc`, `--label`, `--strip`…) y clases existentes (`.strip`, `.chip`, `.act`, `.sheet`). No inventes colores ni radios.
3. Estilo: casete minimalista. Una sola tipografía (Nunito), bordes de 2 px en `--fg`, radios de 6 px, sombras duras en los botones, tiras de etiquetadora para títulos y secciones.
4. Evita lo genérico: degradados morados, vidrio translúcido, serif cursiva, iconos emoji, sombras difusas, bordes finos.
5. Minimalismo: no añadas textos de ayuda, insignias ni información que el usuario no necesite. Lo de desarrollo va con la clase `.dev-only`.
6. Texto en español, tuteo, frases cortas.

## Comprobar antes de terminar

- Modo claro y oscuro (`prefers-color-scheme`).
- Móvil estrecho (375 px) sin scroll horizontal.
- `prefers-reduced-motion` respetado.
- Si cambiaste un token o un componente, actualiza `DESIGN.md`.
- La app se ve con `python -m http.server 8765 -d cache` y `http://localhost:8765/app.html` (añade `?dev` para las herramientas de evaluación).
