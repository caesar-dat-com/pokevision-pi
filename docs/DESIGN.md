# Sistema de diseño — PokéVision Pi

Dos referencias, mezcladas a propósito:

- **Apple** (apple.com, visionOS): jerarquía tipográfica brutal, muchísimo aire,
  movimiento suave y con intención, materiales translúcidos, cero adornos.
- **Pokémon Champions** (champions.pokemon.com): azul marino profundo, acento lima
  eléctrico, tipografía condensada en mayúsculas, píldoras, energía de competición.

Resultado buscado: *panel de laboratorio Apple con alma de torneo Pokémon.*
Oscuro, nítido, caro. Nada de "web de los 2010" ni degradados chillones.

## Tokens (ya definidos en `app/static/css/tokens.css`)

### Color — extraído del sitio real de Champions

| token | valor | uso |
|---|---|---|
| `--bg-abyss` | `#000244` | fondo base (azul Champions más profundo) |
| `--bg-deep` | `#010636` | capas inferiores, vignette |
| `--bg-royal` | `#1C208A` | fin del degradado del héroe |
| `--blue-glow` | `#0A95F6` | azul señal, foco, links |
| `--blue-deep` | `#1B6FEF` | botones primarios |
| `--lime` | `#BFE900` | **acento principal**: valor, subidas, CTA |
| `--gold` | `#FFCC00` | rareza, destacados |
| `--violet-a` / `--violet-b` | `#8477FB` / `#5230EC` | gradiente de holo |
| `--magenta` | `#FF00C8` | brillo holográfico, alertas de falsa |
| `--ink` | `#F9FFFA` | texto principal |
| `--ink-dim` | `rgba(249,255,250,.62)` | texto secundario |
| `--danger` | `#FF4D5E` | falsa |
| `--warn` | `#FFA23A` | dañada / sospechosa |
| `--ok` | `#BFE900` | auténtica |

Fondo global: `radial-gradient` de `--bg-royal` al 20% superior sobre
`linear-gradient(#000244, #010636)`. Nunca negro puro: siempre azul.

### Tipografía (empaquetada, sin CDN — la Pi puede estar sin internet)

`app/static/fonts/` ya trae los `.woff2`:

- **Sofia Sans Condensed 900** → titulares en MAYÚSCULA, `letter-spacing: -.01em`.
  Es la fuente del sitio de Champions. Úsala para `h1`, `h2`, veredictos y el precio.
- **Saira 400/700/800** → interfaz, etiquetas, cuerpo. Ancho normal, muy legible a 7".
- **Saira Condensed 700** → datos tabulares, chips, números de set.
- Números siempre con `font-variant-numeric: tabular-nums` (evita el baile al animar).

Escala (Apple: saltos grandes, nada intermedio):
`clamp(2.6rem, 7vw, 4.5rem)` titular · `1.35rem` subtítulo · `1rem` cuerpo ·
`.8rem` etiqueta en mayúscula con `letter-spacing: .14em`.

### Forma y material

- Radios: `--r-pill: 999px`, `--r-card: 22px`, `--r-chip: 10px`. Nada de 4px.
- Vidrio: `background: rgba(255,255,255,.055)` + `backdrop-filter: blur(22px) saturate(1.3)`
  + borde `1px solid rgba(255,255,255,.1)` + sombra `0 24px 60px rgba(0,2,68,.55)`.
- Botón primario: píldora lima con texto `--bg-abyss`, sombra `0 0 32px rgba(191,233,0,.35)`.
- Borde de énfasis: gradiente cónico violeta→magenta→lima con máscara (`border-image`
  no, usa pseudo-elemento + `mask-composite`).

## Movimiento

Easing de la casa: `--ease: cubic-bezier(.16,1,.3,1)` (el "suave Apple").
Duraciones: 180 ms micro · 420 ms transición · 900 ms entrada de carta.

Obligatorio:

1. **Holo tilt**: la carta identificada responde al puntero/táctil con
   `rotate3d` máx 10° + capa de gradiente cónico que se desplaza (el brillo holográfico).
2. **Barrido de escaneo**: línea lima con blur que recorre el visor mientras procesa.
3. **Conteo de precio**: tween numérico con `requestAnimationFrame`, easing out.
4. **Barras de confianza**: se llenan con `transform: scaleX()`, nunca con `width`.
5. **Entrada escalonada**: `animation-delay` incremental de 60 ms por tarjeta.
6. **Transición de pestaña**: View Transitions API con fallback de opacidad.
7. `@media (prefers-reduced-motion: reduce)` apaga todo lo anterior. El sitio de
   Champions tiene su propio botón de "Reduced Motion": nosotros también.

Solo se animan `transform` y `opacity`. Nada de animar `width`, `top` o `filter`
en bucle: la Pi 4 no tiene GPU para eso.

## Reglas de presupuesto (Raspberry Pi 4)

- Cero frameworks, cero CDNs, cero librerías de gráficas: canvas 2D a mano.
- Máximo 3 capas con `backdrop-filter` visibles a la vez.
- Imágenes de carta a `width: 100%` con `loading="lazy"`.
- El CSS completo debe pesar menos de 40 KB sin comprimir.

## Layout

- Pantalla de 7" (800×480): visor a la izquierda, resultado a la derecha, dos columnas.
- Monitor: tres columnas (visor · carta · mercado).
- Barra inferior de pestañas tipo iOS, píldoras flotantes con vidrio: **Escanear ·
  Colección · Mercado · Autenticidad**.
- Área táctil mínima 44×44 px (regla de Apple).

## Tono de los textos

Español neutro, corto, sin signos de admiración. "Carta identificada", no
"¡Wow, encontramos tu carta!". Los números mandan; el texto solo los enmarca.
