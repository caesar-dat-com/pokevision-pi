"""Runtime de inferencia para la Raspberry Pi 4.

Solo depende de onnxruntime + numpy + Pillow (ni torch ni sklearn-heavy en la Pi;
el modelo de precio es un joblib ligero de sklearn, que si se instala).

    from vision.pipeline import Pipeline
    p = Pipeline()
    print(p.analyze(open("foto.jpg", "rb").read()))
"""
from __future__ import annotations

import io
import json
import math
import os
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "vision", "models")
PRICE_MODEL = os.path.join(ROOT, "pricing", "models", "price_model.joblib")
CARDS = os.path.join(ROOT, "data", "cards.jsonl")

IMSIZE = (224, 160)  # alto, ancho
MEAN = np.array([0.485, 0.456, 0.406], np.float32).reshape(3, 1, 1)
STD = np.array([0.229, 0.224, 0.225], np.float32).reshape(3, 1, 1)
CLASSES = ["autentica", "falsa", "danada"]
EUR_USD = float(os.environ.get("POKEVISION_EUR_USD", "1.15"))
EUR_COP = float(os.environ.get("POKEVISION_EUR_COP", "4580"))


def preprocess(img: Image.Image) -> np.ndarray:
    img = img.convert("RGB").resize((IMSIZE[1], IMSIZE[0]), Image.BILINEAR)
    a = np.asarray(img, np.float32).transpose(2, 0, 1) / 255.0
    return ((a - MEAN) / STD)[None, ...]


def softmax(x):
    e = np.exp(x - x.max())
    return e / e.sum()


# --------------------------------------------------------------- senales clasicas
def classic_signals(img: Image.Image) -> dict:
    """Indicios interpretables que acompanan al veredicto de la red.

    No son el modelo: son la explicacion que ve el usuario (y lo unico que
    funciona si todavia no hay condition.onnx entrenado).
    """
    im = img.convert("RGB").resize((320, 448), Image.BILINEAR)
    a = np.asarray(im, np.float32) / 255.0
    g = a.mean(2)

    # nitidez: energia del laplaciano (una falsa impresa barata es blanda)
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1])
    sharp = float(np.clip(lap.var() * 900, 0, 1))

    # saturacion media: las falsas suelen salir chillonas o lavadas
    mx, mn = a.max(2), a.min(2)
    sat = float((mx - mn).mean())
    sat_score = float(np.clip(1 - abs(sat - 0.42) / 0.42, 0, 1))

    # bordes: desviacion del marco respecto a su propia media (corte irregular)
    b = 10
    frame = np.concatenate([g[:b].ravel(), g[-b:].ravel(),
                            g[:, :b].ravel(), g[:, -b:].ravel()])
    edge = float(np.clip(1 - frame.std() * 2.2, 0, 1))

    # esquinas: blanqueo / desgaste -> mucho mas claras que el resto
    c = 26
    corners = [g[:c, :c], g[:c, -c:], g[-c:, :c], g[-c:, -c:]]
    body = float(g[c:-c, c:-c].mean())
    worst = max(float(abs(x.mean() - body)) for x in corners)
    corner = float(np.clip(1 - worst * 2.6, 0, 1))

    return {"bordes": round(edge, 3), "saturacion": round(sat_score, 3),
            "nitidez": round(sharp, 3), "esquinas": round(corner, 3)}


class Pipeline:
    def __init__(self, models_dir: str = MODELS):
        import onnxruntime as ort  # import tardio: la Pi arranca mas rapido

        so = ort.SessionOptions()
        so.intra_op_num_threads = int(os.environ.get("POKEVISION_THREADS", "4"))
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.emb = ort.InferenceSession(os.path.join(models_dir, "embedder.onnx"),
                                        so, providers=["CPUExecutionProvider"])
        cond_path = os.path.join(models_dir, "condition.onnx")
        self.cond = (ort.InferenceSession(cond_path, so,
                                          providers=["CPUExecutionProvider"])
                     if os.path.exists(cond_path) else None)
        self.index = np.load(os.path.join(models_dir, "index.npy"))
        with open(os.path.join(models_dir, "index_meta.json")) as f:
            self.meta = json.load(f)
        self.cards = {}
        if os.path.exists(CARDS):
            with open(CARDS) as f:
                for line in f:
                    try:
                        c = json.loads(line)
                        self.cards[c["id"]] = c
                    except Exception:  # noqa: BLE001
                        pass
        self.price = None
        if os.path.exists(PRICE_MODEL):
            try:
                import joblib
                self.price = joblib.load(PRICE_MODEL)
            except Exception as e:  # noqa: BLE001
                print("aviso: modelo de precio no cargado:", e)

    # ------------------------------------------------------------------ vision
    def identify(self, img: Image.Image, topk=4):
        x = preprocess(img)
        z = self.emb.run(None, {"input": x})[0][0]
        z = z / (np.linalg.norm(z) + 1e-9)
        sims = self.index @ z
        idx = np.argsort(-sims)[:topk]
        out = []
        for i in idx:
            m = dict(self.meta[int(i)])
            m["match_score"] = round(float(sims[int(i)]), 4)
            out.append(m)
        return out

    def condition(self, img: Image.Image):
        signals = classic_signals(img)
        if self.cond is None:
            score = float(np.mean(list(signals.values())))
            verdict = "autentica" if score > 0.62 else (
                "danada" if signals["esquinas"] < 0.5 else "sospechosa")
            return {"verdict": verdict, "confidence": round(score, 3),
                    "scores": {"autentica": round(score, 3),
                               "falsa": round((1 - score) / 2, 3),
                               "danada": round((1 - score) / 2, 3)},
                    "signals": signals, "modelo": "heuristico (sin red entrenada)",
                    "notes": self._notes(signals, "autentica")}
        probs = softmax(self.cond.run(None, {"input": preprocess(img)})[0][0])
        k = int(np.argmax(probs))
        verdict = CLASSES[k]
        conf = float(probs[k])
        # red insegura + indicios raros -> no afirmamos "autentica", decimos sospechosa
        if verdict == "autentica" and conf < 0.6:
            verdict = "sospechosa"
        return {"verdict": verdict, "confidence": round(conf, 3),
                "scores": {c: round(float(p), 4) for c, p in zip(CLASSES, probs)},
                "signals": signals, "modelo": "mobilenetv3-small (onnx)",
                "notes": self._notes(signals, verdict)}

    @staticmethod
    def _notes(s, verdict):
        n = []
        n.append("Bordes regulares" if s["bordes"] > 0.6 else
                 "Corte de bordes irregular: revisar troquelado")
        n.append("Color dentro de rango" if s["saturacion"] > 0.6 else
                 "Saturacion fuera de rango tipico de impresion oficial")
        n.append("Impresion nitida" if s["nitidez"] > 0.45 else
                 "Texto/arte sin filo: posible reimpresion")
        n.append("Esquinas intactas" if s["esquinas"] > 0.6 else
                 "Desgaste visible en esquinas")
        if verdict == "falsa":
            n.insert(0, "La red marca patrones de impresion no oficiales")
        elif verdict == "danada":
            n.insert(0, "La red detecta dano fisico que afecta el valor")
        return n

    # ------------------------------------------------------------------ precio
    def price_block(self, card_id):
        c = self.cards.get(card_id, {})
        cm = ((c.get("pricing") or {}).get("cardmarket") or {})
        tp = ((c.get("pricing") or {}).get("tcgplayer") or {})
        eur = cm.get("avg1") or cm.get("trend") or cm.get("avg7") or cm.get("avg30")
        usd = None
        if isinstance(tp, dict):
            for v in tp.values():
                if isinstance(v, dict) and v.get("marketPrice"):
                    usd = v["marketPrice"]
                    break
        if eur and not usd:
            usd = round(eur * EUR_USD, 2)
        return {
            "eur": round(eur, 2) if eur else None,
            "usd": round(usd, 2) if usd else None,
            "cop": int(eur * EUR_COP) if eur else None,
            "low": cm.get("low"), "trend": cm.get("trend"),
            "avg7": cm.get("avg7"), "avg30": cm.get("avg30"),
            "source": "cardmarket+tcgplayer (TCGdex)",
            "updated": cm.get("updated"),
        }

    def forecast(self, card_id, horizons=(30, 90, 180)):
        c = self.cards.get(card_id)
        if not c or self.price is None:
            return None
        import sys as _sys
        if ROOT not in _sys.path:
            _sys.path.insert(0, ROOT)
        from pricing.features import build_row

        row = build_row(c)
        if row is None:
            return None
        r_week = float(self.price["model"].predict(np.array([row], np.float32))[0])
        sd = float(self.price.get("resid_std", 0.18))
        base = self.price_block(card_id)["eur"] or 0.0
        daily = r_week / 7.0
        eur, lo, hi = [], [], []
        for h in horizons:
            # amortiguacion: el momentum no se mantiene indefinidamente
            damp = 1 - math.exp(-h / 75.0)
            drift = daily * 75.0 * damp
            band = sd * math.sqrt(h / 7.0) * 0.8
            eur.append(round(base * math.exp(drift), 2))
            lo.append(round(base * math.exp(drift - band), 2))
            hi.append(round(base * math.exp(drift + band), 2))
        chg = (eur[-1] / base - 1) * 100 if base else 0.0
        return {
            "horizon_days": list(horizons), "eur": eur,
            "low_band": lo, "high_band": hi,
            "direction": "sube" if chg > 2 else ("baja" if chg < -2 else "estable"),
            "change_pct_180d": round(chg, 1),
            "weekly_rate": round(r_week, 4),
            "confidence": round(float(np.clip(1 - sd * 2.2, 0.15, 0.9)), 2),
            "modelo": "HistGradientBoosting sobre serie Cardmarket",
        }

    # ------------------------------------------------------------------ todo junto
    def analyze(self, image_bytes: bytes):
        t0 = time.time()
        img = Image.open(io.BytesIO(image_bytes))
        matches = self.identify(img)
        cond = self.condition(img)
        best = matches[0] if matches else None
        res = {"ok": bool(best), "ms": int((time.time() - t0) * 1000),
               "card": best, "alternatives": matches[1:], "condition": cond}
        if best:
            res["price"] = self.price_block(best["id"])
            res["forecast"] = self.forecast(best["id"])
        return res
