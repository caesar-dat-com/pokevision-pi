"""Features del modelo de precio. Compartido entre entrenamiento e inferencia.

Regla dura: NUNCA se usa avg1 como feature. avg1 es el objetivo (via log(avg1/avg7)).
Si entra aqui, el modelo hace trampa y las metricas mienten.
"""
from __future__ import annotations

import math
from datetime import datetime

# ordenadas de menos a mas escasa; el modelo recibe el indice como feature ordinal
RARITY_ORDER = [
    "none", "common", "uncommon", "rare", "double rare", "rare holo",
    "rare holo ex", "rare holo gx", "rare holo v", "rare holo vmax", "rare holo vstar",
    "ultra rare", "shiny rare", "shiny ultra rare", "illustration rare",
    "special illustration rare", "hyper rare", "secret rare", "rare secret",
    "amazing rare", "radiant rare", "rare rainbow", "rare shiny", "ace spec rare",
    "black white rare", "crown", "legend", "promo",
]
CATEGORIES = ["pokemon", "trainer", "energy"]

FEATURE_NAMES = [
    "log_avg30",        # nivel de precio (escala log)
    "mom_7_30",         # log(avg7/avg30): momentum mensual
    "low_ratio",        # log(low/avg30): que tan lejos esta el piso
    "trend_ratio",      # log(trend/avg30): señal propia de cardmarket
    "spread",           # (avg30-low)/avg30: dispersion del mercado
    "rarity_idx",       # rareza ordinal
    "rarity_known",     # 1 si la rareza esta en el catalogo
    "set_total",        # tamano del set
    "set_age_days",     # antiguedad del set (escasez por tiempo)
    "hp",
    "is_pokemon", "is_trainer", "is_energy",
    "v_holo", "v_reverse", "v_normal", "v_first_edition", "v_promo",
    "n_variants",
    "has_suffix",       # ex / V / VMAX / VSTAR en el sufijo
    "local_id_ratio",   # posicion en el set: >1 = secreta
    "is_secret",        # numero por encima del total oficial del set
]


def _safe_log(a, b, default=0.0):
    try:
        if a and b and a > 0 and b > 0:
            return math.log(a / b)
    except Exception:  # noqa: BLE001
        pass
    return default


def _rarity_idx(r):
    if not r:
        return -1
    key = str(r).strip().lower()
    if key in RARITY_ORDER:
        return RARITY_ORDER.index(key)
    for i, name in enumerate(RARITY_ORDER):  # coincidencia parcial
        if name in key or key in name:
            return i
    return -1


def _set_age_days(release):
    if not release:
        return 365.0  # valor neutro cuando TCGdex no trae la fecha
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(str(release)[:len(datetime.now().strftime(fmt))], fmt)
            return max(0.0, (datetime.utcnow() - d).days)
        except Exception:  # noqa: BLE001
            continue
    return 365.0


def build_row(card: dict):
    """dict de carta (formato de data/cards.jsonl) -> lista de features. None si no sirve."""
    cm = ((card.get("pricing") or {}).get("cardmarket") or {})
    avg7, avg30 = cm.get("avg7"), cm.get("avg30")
    low, trend = cm.get("low"), cm.get("trend")
    if not (isinstance(avg30, (int, float)) and avg30 and avg30 > 0.01):
        return None
    if not (isinstance(avg7, (int, float)) and avg7 and avg7 > 0.01):
        return None

    var = card.get("variants") or {}
    cat = str(card.get("category") or "").lower()
    rid = _rarity_idx(card.get("rarity"))
    try:
        local = float(str(card.get("local_id") or "0").split("/")[0].strip() or 0)
    except Exception:  # noqa: BLE001
        local = 0.0
    total = float(card.get("set_total") or 0) or 1.0
    hp = card.get("hp")

    return [
        math.log(avg30),
        _safe_log(avg7, avg30),
        _safe_log(low, avg30, -1.0),
        _safe_log(trend, avg30),
        float((avg30 - low) / avg30) if isinstance(low, (int, float)) and low else 0.5,
        float(rid),
        1.0 if rid >= 0 else 0.0,
        total,
        _set_age_days(card.get("set_release")),
        float(hp) if isinstance(hp, (int, float)) else 0.0,
        1.0 if "pokemon" in cat else 0.0,
        1.0 if "trainer" in cat else 0.0,
        1.0 if "energy" in cat else 0.0,
        1.0 if var.get("holo") else 0.0,
        1.0 if var.get("reverse") else 0.0,
        1.0 if var.get("normal") else 0.0,
        1.0 if var.get("firstEdition") else 0.0,
        1.0 if var.get("wPromo") else 0.0,
        float(sum(1 for v in var.values() if v)),
        1.0 if card.get("suffix") else 0.0,
        local / total,
        1.0 if local > total else 0.0,
    ]
