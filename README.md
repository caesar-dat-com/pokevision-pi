# PokéVision Pi

**Identifica una carta Pokémon con la cámara, dice cuánto vale, predice cuánto va a
valer y avisa si es falsa o está dañada. Todo corriendo dentro de una Raspberry Pi 4.**

Proyecto de clase: visión por computador + modelo de mercado, desplegado en hardware
embebido. Sin servicios en la nube en tiempo de ejecución: los tres modelos viven en la
Pi y responden sin internet (solo las imágenes de referencia se descargan una vez).

Punto de partida: [`hulldrapro/pokeprecio`](https://github.com/hulldrapro/pokeprecio),
una app Android que leía el nombre con OCR y consultaba el precio. Aquí se reemplaza el
OCR por reconocimiento visual entrenado, se añade predicción de valor y detección de
falsas/dañadas, y la interfaz se rehace para pantalla táctil.

---

## Los tres modelos

| # | Modelo | Qué hace | Cómo se entrena |
|---|---|---|---|
| 1 | **Identificador** | Dice *qué carta* es, entre miles | MobileNetV3-Small + aprendizaje contrastivo (NT-Xent). Cada carta genera dos "fotos" distintas de sí misma y la red aprende a reconocerlas como la misma |
| 2 | **Autenticidad y estado** | auténtica / falsa / dañada + indicios | MobileNetV3-Small, 3 clases, con falsificaciones y desgaste sintéticos derivados del escaneo oficial |
| 3 | **Valor futuro** | Proyección a 30/90/180 días con banda | HistGradientBoosting sobre la serie real de Cardmarket (avg30 → avg7 → avg1) |

### Métricas reales de este repositorio

Se escriben solas al entrenar, en `vision/models/` y `pricing/models/`, y la app las
muestra en la pestaña **MODELOS**. No se reportan números a mano.

```
pricing   objetivo log(avg1/avg7) · split POR SET (ningún set en train y test a la vez)
          acierto de dirección 73.2 %   MAE 0.1761   R² 0.157
          baseline "predecir cero" MAE 0.1791 · baseline "media" MAE 0.1775  → el modelo gana
```

Las métricas de visión quedan en `vision/models/embedder_metrics.txt` y
`vision/models/condition_metrics.json` al terminar el entrenamiento.

---

## Cómo decide si una carta es falsa

La red da el veredicto; junto a él se muestran cuatro indicios interpretables calculados
sobre la imagen (`vision/pipeline.py:classic_signals`), para que la decisión no sea una
caja negra:

- **Bordes** — regularidad del troquelado y del marco.
- **Saturación** — desviación del color respecto a la impresión oficial.
- **Nitidez** — energía del laplaciano: una reimpresión pierde filo en el texto.
- **Esquinas** — blanqueo y desgaste respecto al cuerpo de la carta.

Si la red dice "auténtica" con menos del 60 % de confianza, el veredicto que se muestra
es **sospechosa**: el sistema no afirma autenticidad cuando duda.

> **Limitación honesta:** no existe un dataset público de falsificaciones reales. Las
> clases *falsa* y *dañada* se generan sintéticamente replicando los defectos que se usan
> en la práctica para detectarlas. Sirve como cribado, **no** como peritaje para comprar.

---

## Cómo predice el valor futuro

TCGdex expone, por carta, la serie corta de Cardmarket: media de 30 días, media de 7 días
y último día, más `trend` y `low`. Con eso se plantea un problema supervisado real:

- **Entrada**: estado pasado de la carta — `avg30`, momentum `log(avg7/avg30)`, posición
  del mínimo, rareza ordinal, antigüedad del set, tamaño del set, HP, variantes
  (holo/reverse/1ª edición), si es carta secreta…
- **Objetivo**: `log(avg1 / avg7)`, el movimiento más reciente — **que no aparece en
  ninguna entrada**. Sin fuga de información.

El modelo aprende qué tipo de carta sigue subiendo y cuál corrige. `vision/pipeline.py`
convierte esa tasa en una proyección amortiguada a 30/90/180 días con banda de
incertidumbre derivada del error real en test. Nada de inventar una curva bonita.

---

## Puesta en marcha

### 1. Datos (una vez, con internet)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-train.txt
python scripts/fetch_dataset.py --sets 30 --workers 24
```

Descarga ~4.500 cartas de los 30 sets más recientes: metadatos y precios en
`data/cards.jsonl`, imágenes oficiales en `data/images/`. Tarda unos 5 minutos.

### 2. Entrenar (en un PC, no en la Pi)

```bash
python vision/train/train_embedder.py  --epochs 6 --batch 48   # identificación
python vision/train/train_condition.py --epochs 5 --per-class 1 # falsa/dañada
python pricing/train_price.py                                   # valor futuro
python vision/build_index.py                                    # ONNX + índice
```

En un portátil con 16 hilos: ~15 min el embedder, ~25 min el clasificador, segundos el
modelo de precio. Sin GPU.

### 3. Desplegar en la Raspberry Pi 4

```bash
sudo apt install -y python3-venv libopenblas0
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-pi.txt          # onnxruntime, sin PyTorch
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Copia a la Pi: el repo + `vision/models/*.onnx` + `index.npy` + `index_meta.json` +
`pricing/models/` + `data/cards.jsonl`. **PyTorch no se instala en la Pi.**

Servicio permanente y kiosco a pantalla completa:

```bash
sudo cp systemd/pokevision.service /etc/systemd/system/
sudo systemctl enable --now pokevision
```

Si falta cualquier modelo, la app arranca igual en **modo demo** con datos reales del
catálogo, para poder probar la interfaz.

---

## Interfaz

Diseño propio: estética Apple (jerarquía, aire, materiales translúcidos, movimiento con
intención) sobre la paleta de [Pokémon Champions](https://champions.pokemon.com) —azul
abisal `#000244`, lima `#BFE900`, tipografía condensada—. Especificación completa en
[`docs/DESIGN.md`](docs/DESIGN.md).

- Carta identificada con **flip 3D y brillo holográfico** que sigue al dedo.
- **Barrido láser** sobre el visor mientras se procesa.
- Precio con **conteo animado**, barras de confianza con easing.
- Gráfica de precio histórico + predicción en **canvas 2D a mano** (sin librerías).
- Pestañas con **View Transitions API** y botón de movimiento reducido.
- Cero frameworks, cero CDNs, fuentes empaquetadas: funciona **sin internet** y fluido en
  una Pi 4.

Pestañas: **Escanear · Colección · Mercado · Modelos**.

---

## API

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/scan` | multipart `file` → carta + precio + predicción + veredicto |
| `GET` | `/api/card/{id}` | ficha, precio y proyección |
| `GET` | `/api/search?q=` | búsqueda por nombre |
| `GET` | `/api/collection` | colección y valor total |
| `POST` | `/api/collection` | `{card_id, qty}` |
| `GET` | `/api/health` | estado, temperatura de la Pi y métricas de los modelos |

---

## Estructura

```
app/        FastAPI + interfaz (templates, CSS, JS, fuentes)
vision/     dataset.py (augmentaciones) · train/ · build_index.py · pipeline.py (runtime Pi)
pricing/    features.py · train_price.py · models/
scripts/    fetch_dataset.py · smoke.sh
docs/       DESIGN.md · RASPBERRY.md
legacy-www/ app original de referencia (pokeprecio)
```

## Créditos y licencia

- Datos e imágenes: [TCGdex](https://tcgdex.dev) (precios de Cardmarket/TCGplayer).
- Inspiración funcional: [`hulldrapro/pokeprecio`](https://github.com/hulldrapro/pokeprecio).
- Pokémon y los nombres de las cartas son marcas de Nintendo / Creatures / GAME FREAK.
  Proyecto académico sin ánimo de lucro, sin afiliación oficial.
- Código bajo licencia MIT.
