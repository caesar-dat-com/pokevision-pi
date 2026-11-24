#!/usr/bin/env python3
"""Entrena el clasificador de autenticidad y estado: autentica / falsa / danada.

Dataset: se deriva de las imagenes oficiales (data/images). Cada carta produce
ejemplos de las tres clases:

  autentica -> scan oficial + augmentacion fotografica (lo que veria la camara)
  falsa     -> artefactos de falsificacion (color desviado, trama de impresion,
               texto blando, borde mal cortado, holo plano, reimpresion)
  danada    -> desgaste fisico (esquinas, rayones, dobleces, manchas, descolorida)

Limitacion documentada: las clases negativas son SINTETICAS. Replican los indicios
que se usan en la practica, pero el modelo debe revalidarse con falsificaciones
reales antes de usarlo para decidir una compra.

Split por CARTA (no por imagen): ninguna carta del test aparece en train.

  python vision/train/train_condition.py --epochs 6 --per-class 2
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from vision.dataset import list_images, make_damaged, make_fake, photo_augment  # noqa: E402

IMG_DIR = os.path.join(ROOT, "data", "images")
OUT_DIR = os.path.join(ROOT, "vision", "models")
CLASSES = ["autentica", "falsa", "danada"]
IMSIZE = (224, 160)
NORM = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
TO_TENSOR = transforms.Compose([transforms.ToTensor(), NORM])


class ConditionDS(Dataset):
    def __init__(self, paths, per_class=2, seed=0, train=True):
        self.items = []
        for p in paths:
            for c in range(3):
                for k in range(per_class):
                    self.items.append((p, c, k))
        self.seed = seed
        self.train = train

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p, cls, k = self.items[i]
        rng = random.Random(hash((p, cls, k, self.seed)) & 0xFFFFFFFF)
        try:
            base = Image.open(p).convert("RGB").resize((IMSIZE[1], IMSIZE[0]), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            base = Image.new("RGB", (IMSIZE[1], IMSIZE[0]), (20, 20, 20))
        if cls == 1:
            base = make_fake(base, rng)
        elif cls == 2:
            base = make_damaged(base, rng)
        # toda carta se ve a traves de la camara: tambien las falsas y las danadas
        base = photo_augment(base, rng)
        return TO_TENSOR(base), cls


def build_model():
    m = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    m.classifier[3] = nn.Linear(m.classifier[3].in_features, 3)
    return m


def evaluate(model, dl):
    model.eval()
    cm = np.zeros((3, 3), dtype=int)
    with torch.no_grad():
        for x, y in dl:
            pred = model(x).argmax(1)
            for t, p in zip(y.tolist(), pred.tolist()):
                cm[t, p] += 1
    acc = cm.trace() / max(cm.sum(), 1)
    per = {}
    for i, c in enumerate(CLASSES):
        tp, fp, fn = cm[i, i], cm[:, i].sum() - cm[i, i], cm[i].sum() - cm[i, i]
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        per[c] = {"precision": round(float(prec), 4), "recall": round(float(rec), 4),
                  "f1": round(float(2 * prec * rec / max(prec + rec, 1e-9)), 4)}
    model.train()
    return float(acc), per, cm.tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=48)
    ap.add_argument("--lr", type=float, default=4e-4)
    ap.add_argument("--per-class", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args()

    if args.threads:
        torch.set_num_threads(args.threads)
    os.makedirs(OUT_DIR, exist_ok=True)

    paths = list_images(IMG_DIR)
    if args.limit:
        paths = paths[: args.limit]
    if len(paths) < 50:
        print(f"ERROR: solo {len(paths)} imagenes. Corre scripts/fetch_dataset.py")
        return 1
    rng = random.Random(7)
    rng.shuffle(paths)
    cut = int(len(paths) * 0.85)
    tr_paths, te_paths = paths[:cut], paths[cut:]
    print(f"cartas train={len(tr_paths)} test={len(te_paths)} "
          f"(split por carta, sin fuga)", flush=True)

    tr = ConditionDS(tr_paths, args.per_class, seed=1)
    te = ConditionDS(te_paths, 1, seed=99, train=False)
    dtr = DataLoader(tr, batch_size=args.batch, shuffle=True, num_workers=args.workers,
                     drop_last=True, persistent_workers=args.workers > 0)
    dte = DataLoader(te, batch_size=args.batch, num_workers=max(2, args.workers // 2))
    print(f"muestras train={len(tr)} test={len(te)}", flush=True)

    model = build_model()
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    steps = args.epochs * len(dtr)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps,
                                                pct_start=0.25)
    crit = nn.CrossEntropyLoss(label_smoothing=0.05)

    model.train()
    t0, step, best = time.time(), 0, 0.0
    for ep in range(1, args.epochs + 1):
        run = cor = tot = 0
        for nb, (x, y) in enumerate(dtr, 1):
            out = model(x)
            loss = crit(out, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            run += loss.item()
            cor += (out.argmax(1) == y).sum().item()
            tot += y.numel()
            step += 1
            if nb % 10 == 0:
                eta = (time.time() - t0) / step * (steps - step)
                print(f"  ep{ep} {nb}/{len(dtr)} loss={run/nb:.4f} "
                      f"acc={cor/tot:.3f} eta={eta/60:.1f}min", flush=True)
        acc, per, cm = evaluate(model, dte)
        print(f"epoca {ep}/{args.epochs} train_acc={cor/max(tot,1):.3f} "
              f"TEST_acc={acc:.3f} {json.dumps(per)}", flush=True)
        if acc >= best:
            best = acc
            torch.save({"state_dict": model.state_dict(), "classes": CLASSES},
                       os.path.join(OUT_DIR, "condition.pt"))
            with open(os.path.join(OUT_DIR, "condition_metrics.json"), "w") as f:
                json.dump({"test_accuracy": acc, "per_class": per,
                           "confusion_matrix": cm, "classes": CLASSES,
                           "cards_train": len(tr_paths), "cards_test": len(te_paths),
                           "epochs": ep, "nota": "clases falsa/danada sinteticas"},
                          f, indent=2, ensure_ascii=False)
    print(f"mejor TEST acc={best:.3f} -> {OUT_DIR}/condition.pt", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
