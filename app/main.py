"""PokeVision Pi - servidor FastAPI (corre en la Raspberry Pi 4).

    uvicorn app.main:app --host 0.0.0.0 --port 8000

Si los modelos aun no estan entrenados arranca igual, en MODO DEMO, con datos
deterministas tomados de data/cards.jsonl. Asi la interfaz siempre se puede probar.
"""
from __future__ import annotations

import io
import json
import os
import random
import time

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
DATA = os.path.join(ROOT, "data")
COLLECTION = os.path.join(DATA, "collection.json")

app = FastAPI(title="PokeVision Pi", version="1.0")
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))

PIPE = None
PIPE_ERROR = None
CARDS: list = []
CARDS_BY_ID: dict = {}


PLACEHOLDER_IMG = "/static/img/no-card.svg"


def _img(c):
    """URL de la imagen de la carta; placeholder local si TCGdex no la tiene."""
    base = (c or {}).get("image")
    return (base + "/low.webp") if base else PLACEHOLDER_IMG


def load_cards():
    global CARDS, CARDS_BY_ID
    path = os.path.join(DATA, "cards.jsonl")
    if not os.path.exists(path):
        return
    out = []
    with open(path) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    CARDS = out
    CARDS_BY_ID = {c["id"]: c for c in out}


@app.on_event("startup")
def _startup():
    global PIPE, PIPE_ERROR
    load_cards()
    try:
        from vision.pipeline import Pipeline

        PIPE = Pipeline()
        print(f"[pokevision] modelos cargados, indice={len(PIPE.meta)} cartas")
    except Exception as e:  # noqa: BLE001
        PIPE_ERROR = str(e)
        print(f"[pokevision] MODO DEMO (sin modelos): {e}")


# --------------------------------------------------------------------- demo
def demo_result(seed_bytes: bytes):
    """Resultado determinista segun la imagen: misma foto -> misma carta."""
    if not CARDS:
        raise HTTPException(503, "No hay datos. Corre scripts/fetch_dataset.py")
    with_price = [c for c in CARDS
                  if ((c.get("pricing") or {}).get("cardmarket") or {}).get("avg1")
                  and c.get("image")]
    pool = with_price or CARDS
    rnd = random.Random(len(seed_bytes) ^ sum(seed_bytes[:512]))
    card = rnd.choice(pool)
    alts = rnd.sample(pool, min(3, len(pool)))
    cm = ((card.get("pricing") or {}).get("cardmarket") or {})
    eur = cm.get("avg1") or cm.get("trend") or 1.0
    rate = rnd.uniform(-0.05, 0.12)
    fc_eur = [round(eur * (1 + rate * k), 2) for k in (1, 2.2, 3.4)]
    verdict = rnd.choices(["autentica", "sospechosa", "danada"], [0.72, 0.12, 0.16])[0]
    # la confianza tiene que ser coherente con el veredicto: "sospechosa" es, por
    # definicion, una deteccion insegura; no puede salir al 95%
    conf = rnd.uniform(0.78, 0.96) if verdict == "autentica" else (
        rnd.uniform(0.45, 0.6) if verdict == "sospechosa" else rnd.uniform(0.66, 0.88))
    return {
        "ok": True, "demo": True, "ms": rnd.randint(180, 520),
        "card": {"id": card["id"], "name": card.get("name"),
                 "set_name": card.get("set_name"), "local_id": card.get("local_id"),
                 "rarity": card.get("rarity"),
                 "image": _img(card),
                 "match_score": round(rnd.uniform(0.78, 0.97), 3)},
        "alternatives": [{"id": a["id"], "name": a.get("name"),
                          "image": _img(a),
                          "set_name": a.get("set_name"),
                          "match_score": round(rnd.uniform(0.4, 0.75), 3)}
                         for a in alts],
        "price": {"eur": round(eur, 2), "usd": round(eur * 1.15, 2),
                  "cop": int(eur * 4580), "low": cm.get("low"),
                  "trend": cm.get("trend"), "avg7": cm.get("avg7"),
                  "avg30": cm.get("avg30"), "source": "cardmarket (TCGdex)",
                  "updated": cm.get("updated")},
        "forecast": {"horizon_days": [30, 90, 180], "eur": fc_eur,
                     "low_band": [round(v * 0.86, 2) for v in fc_eur],
                     "high_band": [round(v * 1.18, 2) for v in fc_eur],
                     "direction": "sube" if rate > 0.02 else ("baja" if rate < -0.02 else "estable"),
                     "change_pct_180d": round(rate * 3.4 * 100, 1),
                     "confidence": round(rnd.uniform(0.45, 0.75), 2),
                     "modelo": "demo"},
        "condition": {"verdict": verdict, "confidence": round(conf, 3),
                      "scores": {"autentica": round(conf if verdict == "autentica" else (1 - conf) / 2, 3),
                                 "falsa": round(conf if verdict == "sospechosa" else (1 - conf) / 2, 3),
                                 "danada": round(conf if verdict == "danada" else (1 - conf) / 2, 3)},
                      "signals": {k: round(rnd.uniform(0.4, 0.95), 2)
                                  for k in ("bordes", "saturacion", "nitidez", "esquinas")},
                      "modelo": "demo",
                      "notes": ["Modo demo: los modelos aun no estan entrenados"]},
        "grade": grade_demo(seed_bytes, eur),
    }


def grade_demo(blob: bytes, eur: float):
    """En modo demo el grado NO se inventa: el centrado y el desgaste se miden
    de verdad sobre la imagen subida. Lo unico que falta es la red de subgrados."""
    try:
        import io

        from PIL import Image

        from vision.grading import geometric_subgrades, grade_report

        rep = grade_report(geometric_subgrades(Image.open(io.BytesIO(blob))), eur)
        rep["fuente"] = "medidas geometricas sobre la imagen (sin red de grado)"
        return rep
    except Exception as e:  # noqa: BLE001
        return {"psa": None, "error": str(e)}


# -------------------------------------------------------------------- paginas
@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "demo": PIPE is None, "n_cards": len(CARDS)})


# ---------------------------------------------------------------------- api
@app.get("/api/health")
def health():
    temp = None
    for p in ("/sys/class/thermal/thermal_zone0/temp",):
        try:
            with open(p) as f:
                temp = round(int(f.read().strip()) / 1000, 1)
        except Exception:  # noqa: BLE001
            pass
    metrics = {}
    for name, path in (
        ("condition", os.path.join(ROOT, "vision/models/condition_metrics.json")),
        ("grade", os.path.join(ROOT, "vision/models/grade_metrics.json")),
        ("price", os.path.join(ROOT, "pricing/models/price_metrics.json")),
    ):
        try:
            with open(path) as f:
                metrics[name] = json.load(f)
        except Exception:  # noqa: BLE001
            pass
    emb_metrics = os.path.join(ROOT, "vision/models/embedder_metrics.txt")
    if os.path.exists(emb_metrics):
        with open(emb_metrics) as f:
            metrics["embedder"] = dict(
                line.split("=", 1) for line in f.read().strip().splitlines() if "=" in line)
    return {"ok": True, "demo": PIPE is None, "error": PIPE_ERROR,
            "index_cards": len(PIPE.meta) if PIPE else 0,
            "catalog_cards": len(CARDS), "temp_c": temp, "metrics": metrics}


@app.post("/api/grade")
async def grade_only(file: UploadFile = File(...)):
    """Solo pre-grading PSA, sin identificar la carta (mas rapido)."""
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "imagen vacia")
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(blob))
    if PIPE is not None:
        return PIPE.grade(img)
    from vision.grading import geometric_subgrades, grade_report
    return grade_report(geometric_subgrades(img))


@app.post("/api/scan")
async def scan(file: UploadFile = File(...)):
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "imagen vacia")
    if PIPE is None:
        r = demo_result(blob)
        return JSONResponse(r)
    t0 = time.time()
    try:
        res = PIPE.analyze(blob)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"fallo el analisis: {e}")
    res["ms"] = int((time.time() - t0) * 1000)
    if res.get("card") and res["card"].get("image"):
        if not res["card"]["image"].endswith(".webp"):
            res["card"]["image"] += "/low.webp"
    for a in res.get("alternatives", []):
        if a.get("image") and not a["image"].endswith(".webp"):
            a["image"] += "/low.webp"
    return JSONResponse(res)


@app.get("/api/card/{card_id}")
def card(card_id: str):
    c = CARDS_BY_ID.get(card_id)
    if not c:
        raise HTTPException(404, "carta desconocida")
    out = {"card": {"id": c["id"], "name": c.get("name"),
                    "set_name": c.get("set_name"), "rarity": c.get("rarity"),
                    "local_id": c.get("local_id"),
                    "image": _img(c)}}
    if PIPE:
        out["price"] = PIPE.price_block(card_id)
        out["forecast"] = PIPE.forecast(card_id)
    else:
        cm = ((c.get("pricing") or {}).get("cardmarket") or {})
        out["price"] = {"eur": cm.get("avg1"), "low": cm.get("low"),
                        "trend": cm.get("trend"), "avg7": cm.get("avg7"),
                        "avg30": cm.get("avg30")}
        out["forecast"] = None
    return out


@app.get("/api/search")
def search(q: str = "", limit: int = 24):
    q = q.strip().lower()
    if len(q) < 2:
        return {"items": []}
    items = []
    for c in CARDS:
        if q in str(c.get("name", "")).lower():
            cm = ((c.get("pricing") or {}).get("cardmarket") or {})
            items.append({"id": c["id"], "name": c.get("name"),
                          "set_name": c.get("set_name"), "rarity": c.get("rarity"),
                          "image": _img(c),
                          "eur": cm.get("avg1") or cm.get("trend")})
            if len(items) >= limit:
                break
    return {"items": items}


def _read_collection():
    if os.path.exists(COLLECTION):
        try:
            with open(COLLECTION) as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return []


@app.get("/api/collection")
def get_collection():
    items = _read_collection()
    total = 0.0
    for it in items:
        c = CARDS_BY_ID.get(it["card_id"], {})
        cm = ((c.get("pricing") or {}).get("cardmarket") or {})
        eur = cm.get("avg1") or cm.get("trend") or 0
        it["name"] = c.get("name", it["card_id"])
        it["set_name"] = c.get("set_name")
        it["rarity"] = c.get("rarity")
        it["image"] = _img(c)
        it["eur"] = eur
        total += (eur or 0) * it.get("qty", 1)
    return {"items": items, "total_eur": round(total, 2),
            "total_cop": int(total * 4580)}


@app.post("/api/collection")
async def add_collection(payload: dict):
    cid = payload.get("card_id")
    if not cid:
        raise HTTPException(400, "falta card_id")
    qty = int(payload.get("qty", 1))
    cond = payload.get("condition", "autentica")
    items = _read_collection()
    for it in items:
        if it["card_id"] == cid:
            it["qty"] = max(0, it.get("qty", 1) + qty)
            break
    else:
        items.append({"card_id": cid, "qty": max(1, qty), "condition": cond,
                      "added": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    items = [i for i in items if i.get("qty", 0) > 0]
    os.makedirs(DATA, exist_ok=True)
    with open(COLLECTION, "w") as f:
        json.dump(items, f, indent=1)
    return get_collection()
