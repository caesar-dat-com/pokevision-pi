"""Entrena el estimador de subgrados tipo PSA (centrado, esquinas, bordes, superficie).

Idea: no existe un dataset publico de cartas con su grado PSA y su foto. Pero el
desgaste SI se puede simular con severidad conocida: si a un escaneo perfecto le
aplico un blanqueo de esquinas de severidad 0.4, se cuanto debe bajar ese subgrado.
La red aprende a leer esa severidad desde la imagen.

    etiqueta_subgrado = 10 - 9 * severidad

Salidas: 4 regresiones en [1,10]. Metrica honesta = MAE en grados y % de aciertos
dentro de +-1 grado, sobre cartas que la red NUNCA vio (split por carta).

    python vision/train/train_grade.py --epochs 5 --per-card 2

Limitacion documentada en README: el desgaste es sintetico. Es un pre-grading
orientativo, no el dictamen de PSA.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time

import numpy as np
import torch
import torch.nn as nn
from PIL import Image, ImageDraw, ImageFilter
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from vision.grading import flatten  # noqa: E402

IMG_DIR = os.path.join(ROOT, "data", "images")
MODELS = os.path.join(ROOT, "vision", "models")
CARD_W, CARD_H = 160, 224
NORM = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])


# ------------------------------------------------------------------ deterioro
def wear_corners(img: Image.Image, sev: float, rnd: random.Random) -> Image.Image:
    """Blanqueo y redondeo de esquinas, el defecto que mas hunde un grado PSA."""
    if sev <= 0.01:
        return img
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    size = int(min(w, h) * (0.05 + 0.13 * sev))
    for cx, cy in ((0, 0), (w, 0), (0, h), (w, h)):
        if rnd.random() < 0.25 and sev < 0.6:
            continue  # no todas las esquinas se desgastan igual
        r = int(size * rnd.uniform(0.7, 1.3))
        alpha = int(90 + 150 * sev)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, alpha))
        if sev > 0.55:  # esquina roma: se come el material
            d.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2],
                      fill=(246, 246, 240, 255))
    return img


def wear_edges(img: Image.Image, sev: float, rnd: random.Random) -> Image.Image:
    """Mellas y blanqueo del perimetro."""
    if sev <= 0.01:
        return img
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    nicks = int(3 + 26 * sev)
    for _ in range(nicks):
        side = rnd.randrange(4)
        ln = int(rnd.uniform(3, 7 + 22 * sev))
        th = int(1 + 3 * sev)
        a = int(110 + 130 * sev)
        if side == 0:
            x = rnd.randrange(0, max(1, w - ln)); d.rectangle([x, 0, x + ln, th], fill=(255, 255, 255, a))
        elif side == 1:
            x = rnd.randrange(0, max(1, w - ln)); d.rectangle([x, h - th, x + ln, h], fill=(255, 255, 255, a))
        elif side == 2:
            y = rnd.randrange(0, max(1, h - ln)); d.rectangle([0, y, th, y + ln], fill=(255, 255, 255, a))
        else:
            y = rnd.randrange(0, max(1, h - ln)); d.rectangle([w - th, y, w, y + ln], fill=(255, 255, 255, a))
    return img


def wear_surface(img: Image.Image, sev: float, rnd: random.Random) -> Image.Image:
    """Rayones, manchas y perdida de brillo en la superficie."""
    if sev <= 0.01:
        return img
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(int(1 + 13 * sev)):
        x0, y0 = rnd.randrange(w), rnd.randrange(h)
        x1 = x0 + rnd.randint(-70, 70); y1 = y0 + rnd.randint(-70, 70)
        d.line([x0, y0, x1, y1], fill=(255, 255, 255, int(45 + 110 * sev)),
               width=rnd.randint(1, 1 + int(2 * sev)))
    for _ in range(int(3 * sev)):  # manchas
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.randint(4, 4 + int(16 * sev))
        d.ellipse([x - r, y - r, x + r, y + r], fill=(120, 105, 70, int(40 + 70 * sev)))
    if sev > 0.4:  # dobleces
        for _ in range(int(sev * 2)):
            y = rnd.randrange(h)
            d.line([0, y, w, y + rnd.randint(-8, 8)], fill=(255, 255, 255, int(70 * sev)), width=1)
    return img


def shift_centering(img: Image.Image, sev: float, rnd: random.Random) -> Image.Image:
    """Descentrado de corte: la carta se recorta y se vuelve a encuadrar desplazada."""
    if sev <= 0.01:
        return img
    w, h = img.size
    dx = int(w * 0.09 * sev * rnd.choice([-1, 1]))
    dy = int(h * 0.09 * sev * rnd.choice([-1, 1]))
    canvas = Image.new("RGB", (w, h), (252, 250, 242))
    canvas.paste(img, (dx, dy))
    return canvas


def photo_noise(img: Image.Image, rnd: random.Random) -> Image.Image:
    """Variacion de captura, para que la red no memorice el escaneo limpio."""
    from PIL import ImageEnhance
    img = ImageEnhance.Brightness(img).enhance(rnd.uniform(0.82, 1.18))
    img = ImageEnhance.Color(img).enhance(rnd.uniform(0.85, 1.15))
    if rnd.random() < 0.5:
        img = img.filter(ImageFilter.GaussianBlur(rnd.uniform(0, 0.7)))
    return img


# ------------------------------------------------------------------- dataset
class GradeDataset(Dataset):
    """Cada muestra: una carta con desgaste de severidad conocida en 4 ejes."""

    def __init__(self, files, per_card=2, seed=0, eval_mode=False):
        self.files = files
        self.per_card = per_card
        self.seed = seed
        self.eval = eval_mode

    def __len__(self):
        return len(self.files) * self.per_card

    def __getitem__(self, i):
        fi, k = divmod(i, self.per_card)
        rnd = random.Random((self.seed * 7919 + i) if not self.eval else i)
        # flatten(): las imagenes de TCGdex son RGBA con esquinas transparentes; sin
        # componerlas sobre blanco la red aprenderia sobre basura en el borde
        img = flatten(Image.open(self.files[fi])).resize(
            (CARD_W, CARD_H), Image.BILINEAR)

        # severidades independientes; el 30% de las muestras son cartas casi perfectas
        if rnd.random() < 0.3:
            sev = [rnd.uniform(0, 0.12) for _ in range(4)]
        else:
            sev = [rnd.random() ** 1.4 for _ in range(4)]
        s_cen, s_cor, s_edg, s_sur = sev

        img = shift_centering(img, s_cen, rnd)
        img = wear_corners(img, s_cor, rnd)
        img = wear_edges(img, s_edg, rnd)
        img = wear_surface(img, s_sur, rnd)
        img = photo_noise(img, rnd)

        x = NORM(transforms.functional.to_tensor(img))
        y = torch.tensor([10.0 - 9.0 * s for s in sev], dtype=torch.float32)
        return x, y


def build_model():
    m = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    m.classifier[3] = nn.Linear(m.classifier[3].in_features, 4)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=48)
    ap.add_argument("--per-card", type=int, default=2)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)

    files = sorted(os.path.join(IMG_DIR, f) for f in os.listdir(IMG_DIR)
                   if f.endswith(".webp"))
    if args.limit:
        files = files[:args.limit]
    rnd = random.Random(7)
    rnd.shuffle(files)
    # split POR CARTA: ninguna carta de test aparece en entrenamiento
    cut = int(len(files) * 0.85)
    tr_files, te_files = files[:cut], files[cut:]
    print(f"cartas: train={len(tr_files)} test={len(te_files)}", flush=True)

    tr = DataLoader(GradeDataset(tr_files, args.per_card, seed=1),
                    batch_size=args.batch, shuffle=True, num_workers=args.workers,
                    drop_last=True, persistent_workers=args.workers > 0)
    te = DataLoader(GradeDataset(te_files, 2, seed=2, eval_mode=True),
                    batch_size=args.batch, shuffle=False, num_workers=args.workers)

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("dispositivo:", dev, flush=True)
    model = build_model().to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=args.lr * 3, total_steps=args.epochs * len(tr))
    lossf = nn.L1Loss()

    t0 = time.time()
    for ep in range(1, args.epochs + 1):
        model.train()
        run = 0.0
        for i, (x, y) in enumerate(tr, 1):
            x, y = x.to(dev), y.to(dev)
            opt.zero_grad()
            loss = lossf(model(x), y)
            loss.backward()
            opt.step()
            sched.step()
            run += loss.item()
            if i % 10 == 0:
                done = (ep - 1) * len(tr) + i
                eta = (time.time() - t0) / done * (args.epochs * len(tr) - done)
                print(f"  ep{ep} {i}/{len(tr)} mae={run/i:.3f} eta={eta/60:.1f}min",
                      flush=True)

        model.eval()
        errs, preds, gts = [], [], []
        with torch.no_grad():
            for x, y in te:
                p = model(x.to(dev)).cpu().clamp(1, 10)
                errs.append((p - y).abs())
                preds.append(p)
                gts.append(y)
        E = torch.cat(errs)
        P, G = torch.cat(preds), torch.cat(gts)
        mae = E.mean().item()
        within1 = (E <= 1.0).float().mean().item()
        print(f"[ep{ep}] test MAE={mae:.3f} grados · dentro de +-1 = {within1*100:.1f}%",
              flush=True)

    os.makedirs(MODELS, exist_ok=True)
    torch.save({"state_dict": model.state_dict()}, os.path.join(MODELS, "grade.pt"))
    names = ["centrado", "esquinas", "bordes", "superficie"]
    per_axis = {n: round(float(E[:, i].mean()), 3) for i, n in enumerate(names)}
    # correlacion por eje: ¿la red sigue de verdad la severidad o predice la media?
    corr = {}
    for i, n in enumerate(names):
        p, g = P[:, i].numpy(), G[:, i].numpy()
        corr[n] = round(float(np.corrcoef(p, g)[0, 1]), 3)
    baseline = float((G - G.mean()).abs().mean())
    metrics = {
        "test_mae_grades": round(mae, 3),
        "within_1_grade": round(within1, 4),
        "mae_por_eje": per_axis,
        "correlacion_por_eje": corr,
        "baseline_predecir_media_mae": round(baseline, 3),
        "gana_a_baseline": bool(mae < baseline),
        "cartas_test": len(te_files),
        "muestras_test": int(G.shape[0]),
        "epochs": args.epochs,
        "nota": "Desgaste sintetico de severidad conocida; etiqueta = 10 - 9*severidad.",
    }
    with open(os.path.join(MODELS, "grade_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=1, ensure_ascii=False)
    print(json.dumps(metrics, indent=1, ensure_ascii=False), flush=True)

    # export ONNX para la Raspberry
    model_cpu = model.to("cpu").eval()
    torch.onnx.export(model_cpu, torch.randn(1, 3, CARD_H, CARD_W),
                      os.path.join(MODELS, "grade.onnx"),
                      input_names=["input"], output_names=["output"],
                      dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
                      opset_version=13)
    print("grade.onnx exportado", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
