"""Calificacion tipo PSA: subgrados medidos sobre la imagen.

PSA puntua una carta de 1 a 10 mirando cuatro cosas:

    centering  (centrado)    ¿el arte esta centrado dentro del marco?
    corners    (esquinas)    ¿estan afiladas o blanqueadas/romas?
    edges      (bordes)      ¿el borde esta limpio o mellado?
    surface    (superficie)  ¿hay rayones, manchas, perdida de brillo?

Aqui se calculan de dos formas complementarias:

1. `geometric_subgrades()` mide el centrado con geometria real (donde cae el marco
   amarillo dentro de la carta). Es determinista y auditable: PSA publica el criterio
   de centrado en porcentaje, asi que esto no es una conjetura.
2. La red de `vision/train/train_grade.py` estima esquinas, bordes y superficie,
   entrenada con desgaste sintetico de severidad conocida.

El grado final combina los cuatro subgrados con la regla real de PSA: el grado global
nunca supera en mas de un punto al peor subgrado, y un subgrado muy bajo lo hunde.

LIMITACION: esto es una ESTIMACION de pre-grading. PSA evalua la carta fisica con lupa
y luz rasante. Sirve para decidir si vale la pena mandar una carta a graduar, no para
sustituir el dictamen.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

SUBGRADE_NAMES = ("centrado", "esquinas", "bordes", "superficie")

# Etiquetas oficiales de PSA por grado.
PSA_LABELS = {
    10: "GEM-MT 10 · Gem Mint",
    9: "MINT 9 · Mint",
    8: "NM-MT 8 · Near Mint-Mint",
    7: "NM 7 · Near Mint",
    6: "EX-MT 6 · Excellent-Mint",
    5: "EX 5 · Excellent",
    4: "VG-EX 4 · Very Good-Excellent",
    3: "VG 3 · Very Good",
    2: "GOOD 2 · Good",
    1: "PR 1 · Poor",
}

# Multiplicador de mercado sobre el precio en crudo (raw) segun el grado obtenido.
# Heuristica de mercado, NO un dato de API: las cartas modernas en PSA 10 se pagan
# muy por encima del raw, y por debajo de 8 el encapsulado aporta poco.
GRADE_MULTIPLIER = {10: 5.2, 9: 2.1, 8: 1.25, 7: 0.95, 6: 0.8, 5: 0.7,
                    4: 0.6, 3: 0.5, 2: 0.42, 1: 0.35}

# Coste aproximado del servicio de graduacion por carta (USD -> EUR), valor orientativo.
GRADING_COST_EUR = 22.0


# --------------------------------------------------------------- centrado real
def _card_bbox(gray: np.ndarray) -> tuple[int, int, int, int]:
    """Recorta el fondo oscuro alrededor de la carta (si lo hay)."""
    mask = gray > gray.mean() * 0.55
    rows = np.where(mask.any(1))[0]
    cols = np.where(mask.any(0))[0]
    if len(rows) < 10 or len(cols) < 10:
        return 0, 0, gray.shape[1], gray.shape[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _inner_frame(rgb: np.ndarray) -> tuple[float, float, float, float] | None:
    """Localiza el borde interior del marco amarillo clasico de las cartas Pokemon.

    Devuelve los margenes (izq, der, arriba, abajo) en pixeles desde el borde
    de la carta hasta donde empieza el arte.
    """
    h, w, _ = rgb.shape
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # amarillo: rojo y verde altos, azul bajo
    yellow = (r > 0.45) & (g > 0.38) & ((r + g) / 2 - b > 0.10)
    if yellow.mean() < 0.04:
        return None  # carta sin marco amarillo (full art, entrenador, etc.)

    def run(profile: np.ndarray, limit: int) -> float:
        """Grosor del marco: cuantas filas/columnas seguidas son mayoritariamente amarillas."""
        n = 0
        for v in profile[:limit]:
            if v < 0.45:
                break
            n += 1
        return float(n)

    col = yellow.mean(0)  # por columna
    row = yellow.mean(1)  # por fila
    lim_w, lim_h = int(w * 0.30), int(h * 0.30)
    # el escaneo puede traer 1-3 px de antialias en el borde: se saltan
    skip = 3
    left = run(col[skip:], lim_w) + skip
    right = run(col[::-1][skip:], lim_w) + skip
    top = run(row[skip:], lim_h) + skip
    bottom = run(row[::-1][skip:], lim_h) + skip
    thin = min(left, right, top, bottom) <= skip + 1
    fat = max(left, right) > w * 0.28 or max(top, bottom) > h * 0.28
    if thin or fat:
        return None  # no se localizo un marco fiable: mejor no inventar un centrado
    return left, right, top, bottom


def flatten(img: Image.Image) -> Image.Image:
    """Las imagenes de TCGdex son RGBA con las esquinas transparentes.

    Un convert('RGB') directo deja basura en el borde y arruina cualquier medida
    de esquinas o de centrado. Hay que componerlas sobre blanco primero.
    """
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return img.convert("RGB")


def geometric_subgrades(img: Image.Image) -> dict:
    """Centrado medido, mas indicios fisicos de esquinas/bordes/superficie."""
    im = flatten(img).resize((420, 587), Image.BILINEAR)
    a = np.asarray(im, np.float32) / 255.0
    gray = a.mean(2)
    x0, y0, x1, y1 = _card_bbox(gray)
    a = a[y0:y1, x0:x1]
    gray = gray[y0:y1, x0:x1]
    h, w = gray.shape

    out: dict = {}

    # ---- centrado
    fr = _inner_frame(a)
    if fr:
        left, right, top, bottom = fr
        lr = 100 * left / max(left + right, 1e-6)       # % del margen a la izquierda
        tb = 100 * top / max(top + bottom, 1e-6)
        worst = max(abs(lr - 50), abs(tb - 50)) * 2      # desviacion -> "x/100-y"
        pct = 50 + worst / 2
        # PSA: 55/45 o mejor = 10; 60/40 = 9; 65/35 = 8; 70/30 = 7; 80/20 = 6
        for limit, grade in ((55, 10), (60, 9), (65, 8), (70, 7), (80, 6), (90, 4)):
            if pct <= limit:
                centering = float(grade)
                break
        else:
            centering = 3.0
        out["centering_pct"] = f"{round(pct)}/{round(100 - pct)}"
        out["centering_lr"] = f"{round(lr)}/{round(100 - lr)}"
        out["centering_tb"] = f"{round(tb)}/{round(100 - tb)}"
    else:
        centering = 8.0  # sin marco medible no se penaliza: se asume correcto
        out["centering_pct"] = "no medible"
    out["centrado"] = round(centering, 1)

    # ---- esquinas: blanqueo del vertice comparado con el borde recto de al lado.
    # OJO: las cartas tienen las esquinas REDONDEADAS y los escaneos oficiales las
    # traen transparentes (aqui ya compuestas sobre blanco). Si se midiera el vertice
    # literal, toda carta perfecta saldria "blanqueada". Por eso el parche se mete
    # hacia dentro, fuera del radio de la esquina, y se compara con la franja recta
    # del mismo borde, que es el mismo material impreso.
    c = max(8, int(min(h, w) * 0.055))
    ins = int(c * 0.9)  # desplazamiento hacia dentro: evita el redondeo
    corners = [gray[ins:ins + c, ins:ins + c], gray[ins:ins + c, -ins - c:-ins],
               gray[-ins - c:-ins, ins:ins + c], gray[-ins - c:-ins, -ins - c:-ins]]
    mid = int(w / 2 - c / 2), int(h / 2 - c / 2)
    refs = [gray[ins:ins + c, mid[0]:mid[0] + c], gray[-ins - c:-ins, mid[0]:mid[0] + c],
            gray[mid[1]:mid[1] + c, ins:ins + c], gray[mid[1]:mid[1] + c, -ins - c:-ins]]
    ref = float(np.median([p.mean() for p in refs if p.size]))
    devs = [max(0.0, float(p.mean()) - ref) for p in corners if p.size]  # solo blanqueo
    worst_corner = max(devs) if devs else 0.0
    out["esquinas"] = round(float(np.clip(10 - worst_corner * 24, 1, 10)), 1)

    # ---- bordes: el perimetro deberia ser una franja uniforme. Se compara su
    # variacion con la del interior de la carta, que si tiene arte: asi la medida
    # no depende de lo recargado que sea el diseño.
    b = max(4, int(min(h, w) * 0.025))
    frame_px = np.concatenate([gray[:b].ravel(), gray[-b:].ravel(),
                               gray[:, :b].ravel(), gray[:, -b:].ravel()])
    inner_std = float(gray[b * 3:-b * 3, b * 3:-b * 3].std()) + 1e-6
    ratio = float(frame_px.std()) / inner_std
    out["bordes"] = round(float(np.clip(10 - max(0.0, ratio - 0.35) * 11, 1, 10)), 1)

    # ---- superficie: un rayon es un pico de alta frecuencia MUY por encima del
    # detalle normal del arte. Se mide el exceso relativo, no un valor absoluto:
    # un arte detallado no es una carta rayada.
    art = gray[int(h * .12):int(h * .58), int(w * .08):int(w * .92)]
    if art.size > 400:
        lap = np.abs(art[:-2, 1:-1] + art[2:, 1:-1] + art[1:-1, :-2] + art[1:-1, 2:]
                     - 4 * art[1:-1, 1:-1])
        typical = float(np.percentile(lap, 75)) + 1e-6
        excess = float(np.percentile(lap, 99.9)) / typical
        out["superficie"] = round(float(np.clip(10 - max(0.0, excess - 9.0) * 0.42, 1, 10)), 1)
        out["_surf_excess"] = round(excess, 2)
    else:
        out["superficie"] = 8.0
    return out


# ------------------------------------------------------------------ grado final
def combine(subgrades: dict) -> float:
    """Regla de PSA: el grado global lo marca el peor subgrado.

    PSA no promedia: una esquina rota hunde la carta aunque el resto sea perfecto.
    El global puede subir como mucho un punto sobre el minimo, y solo si los demas
    subgrados acompañan.
    """
    vals = [float(subgrades[k]) for k in SUBGRADE_NAMES if k in subgrades]
    if not vals:
        return 1.0
    lo = min(vals)
    avg = sum(vals) / len(vals)
    grade = min(lo + 1.0, avg)
    grade = min(grade, lo + 1.0)
    return float(np.clip(round(grade * 2) / 2, 1, 10))  # medios puntos


def grade_report(subgrades: dict, price_eur: float | None = None) -> dict:
    """Informe completo: grado, etiqueta, valor estimado encapsulado y si compensa."""
    g = combine(subgrades)
    gi = int(round(g))
    worst = min(SUBGRADE_NAMES, key=lambda k: subgrades.get(k, 10))
    rep = {
        "psa": g,
        "label": PSA_LABELS.get(gi, f"PSA {gi}"),
        "subgrades": {k: subgrades.get(k) for k in SUBGRADE_NAMES},
        "limiting_factor": worst,
        "centering_pct": subgrades.get("centering_pct"),
        "detail": subgrades.get("centering_lr") and
        f"izq/der {subgrades['centering_lr']} · arr/abj {subgrades['centering_tb']}",
        "note": _note(g, worst),
    }
    if price_eur:
        est = {}
        for cand in (10, 9, 8):
            est[f"psa{cand}"] = round(price_eur * GRADE_MULTIPLIER[cand], 2)
        rep["value_if_graded"] = est
        rep["value_at_estimate"] = round(price_eur * GRADE_MULTIPLIER.get(gi, 0.6), 2)
        gain = rep["value_at_estimate"] - price_eur - GRADING_COST_EUR
        rep["worth_grading"] = bool(gain > 0)
        rep["net_gain_eur"] = round(gain, 2)
        rep["grading_cost_eur"] = GRADING_COST_EUR
    return rep


def _note(g: float, worst: str) -> str:
    if g >= 9.5:
        return "Candidata a gem mint: merece la pena graduarla."
    if g >= 8.5:
        return f"Buen estado. El limite esta en {worst}."
    if g >= 7:
        return f"Estado jugable-coleccion. {worst.capitalize()} baja el grado."
    return f"Desgaste claro en {worst}: graduarla casi nunca compensa."
