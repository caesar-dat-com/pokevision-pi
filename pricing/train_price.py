#!/usr/bin/env python3
"""Modelo de prediccion del valor futuro de una carta.

DATOS REALES. TCGdex expone, por carta, la serie de Cardmarket:
    avg30 (media 30 dias) -> avg7 (media 7 dias) -> avg1 (ultimo dia)
mas `trend` y `low`. Eso es una serie temporal corta pero verdadera del mercado.

Planteamiento supervisado honesto (sin fuga de informacion):
    features  = estado "pasado" de la carta: avg30, avg7/avg30 (momentum), low/avg30,
                trend/avg30, rareza, antiguedad del set, tamano del set, hp, tipo,
                variantes (holo/reverse), categoria, nivel de precio.
    objetivo  = r_next = log(avg1 / avg7)  -> el movimiento MAS RECIENTE, que no
                aparece en ninguna feature.
El modelo aprende que tipo de carta tiende a seguir subiendo o a corregir. Despues,
`predict.py` aplica esa tasa diaria estimada, amortiguada, a 30/90/180 dias.

Se compara siempre contra dos baselines (predecir 0 y predecir la media) para no
enganarse: si el modelo no les gana, el README lo dice.

  python pricing/train_price.py
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pricing.features import FEATURE_NAMES, build_row  # noqa: E402

CARDS = os.path.join(ROOT, "data", "cards.jsonl")
OUT = os.path.join(ROOT, "pricing", "models")


def load_rows():
    X, y, meta = [], [], []
    n_total = n_price = 0
    with open(CARDS) as f:
        for line in f:
            try:
                c = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            n_total += 1
            cm = ((c.get("pricing") or {}).get("cardmarket") or {})
            avg1, avg7, avg30 = cm.get("avg1"), cm.get("avg7"), cm.get("avg30")
            if not all(isinstance(v, (int, float)) and v and v > 0.01
                       for v in (avg1, avg7, avg30)):
                continue
            n_price += 1
            target = math.log(avg1 / avg7)
            if abs(target) > 1.5:  # datos basura (x4 en un dia)
                continue
            row = build_row(c)
            if row is None:
                continue
            X.append(row)
            y.append(target)
            meta.append({"id": c["id"], "set_id": c.get("set_id"),
                         "name": c.get("name"), "avg1": avg1, "avg7": avg7,
                         "avg30": avg30})
    print(f"cartas leidas={n_total} con serie de precios completa={n_price} "
          f"usables={len(X)}", flush=True)
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32), meta


def main():
    os.makedirs(OUT, exist_ok=True)
    X, y, meta = load_rows()
    if len(X) < 300:
        print("ERROR: muy pocas cartas con precios. Corre scripts/fetch_dataset.py")
        return 1

    # split POR SET: ningun set aparece en train y test a la vez
    sets = sorted({m["set_id"] for m in meta})
    rng = np.random.default_rng(13)
    rng.shuffle(sets)
    test_sets = set(sets[: max(1, len(sets) // 5)])
    te_idx = np.array([i for i, m in enumerate(meta) if m["set_id"] in test_sets])
    tr_idx = np.array([i for i, m in enumerate(meta) if m["set_id"] not in test_sets])
    print(f"sets train={len(sets)-len(test_sets)} test={len(test_sets)} "
          f"| muestras train={len(tr_idx)} test={len(te_idx)}", flush=True)

    model = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.05, max_depth=6, min_samples_leaf=25,
        l2_regularization=1.0, early_stopping=True, validation_fraction=0.15,
        random_state=13)
    model.fit(X[tr_idx], y[tr_idx])

    pred = model.predict(X[te_idx])
    yt = y[te_idx]
    mae = mean_absolute_error(yt, pred)
    r2 = r2_score(yt, pred)
    base_zero = mean_absolute_error(yt, np.zeros_like(yt))
    base_mean = mean_absolute_error(yt, np.full_like(yt, y[tr_idx].mean()))
    # acierto de direccion (sube/baja) sobre movimientos no triviales
    mask = np.abs(yt) > 0.005
    dir_acc = float((np.sign(pred[mask]) == np.sign(yt[mask])).mean()) if mask.sum() else 0.0
    resid = float(np.std(yt - pred))

    print(f"TEST  MAE={mae:.5f}  R2={r2:.4f}  acierto_direccion={dir_acc:.3f}")
    print(f"baseline cero MAE={base_zero:.5f} | baseline media MAE={base_mean:.5f}")
    gana = mae < base_zero and mae < base_mean
    print("el modelo " + ("SI" if gana else "NO") + " le gana a los baselines")

    joblib.dump({"model": model, "features": FEATURE_NAMES, "resid_std": resid},
                os.path.join(OUT, "price_model.joblib"))
    metrics = {
        "entrenado": datetime.utcnow().isoformat() + "Z",
        "muestras_train": int(len(tr_idx)), "muestras_test": int(len(te_idx)),
        "sets_train": len(sets) - len(test_sets), "sets_test": len(test_sets),
        "objetivo": "log(avg1/avg7) - movimiento semanal mas reciente",
        "mae": round(float(mae), 6), "r2": round(float(r2), 5),
        "baseline_cero_mae": round(float(base_zero), 6),
        "baseline_media_mae": round(float(base_mean), 6),
        "acierto_direccion": round(dir_acc, 4),
        "resid_std": round(resid, 6),
        "gana_a_baselines": bool(gana),
        "fuente": "Cardmarket via TCGdex (avg1/avg7/avg30/trend/low)",
    }
    with open(os.path.join(OUT, "price_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print("modelo ->", os.path.join(OUT, "price_model.joblib"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
