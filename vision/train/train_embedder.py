#!/usr/bin/env python3
"""Entrena el embedder de identificacion de cartas (metric learning auto-supervisado).

Problema: no hay fotos reales etiquetadas de cada carta, solo el scan oficial. La
solucion es aprendizaje contrastivo (NT-Xent / SimCLR): cada carta genera dos vistas
"fotografiadas" distintas (perspectiva, brillo, blur, glare, ruido) y la red aprende a
acercar las vistas de la MISMA carta y separar las de cartas distintas. El resultado es
un embedding robusto a como se vea la foto en la Raspberry.

Backbone: MobileNetV3-Small (pensado para correr en una Pi 4 via ONNX Runtime).

  python vision/train/train_embedder.py --epochs 8 --batch 48
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from vision.dataset import list_images, photo_augment  # noqa: E402

IMG_DIR = os.path.join(ROOT, "data", "images")
OUT_DIR = os.path.join(ROOT, "vision", "models")
IMSIZE = (224, 160)  # (alto, ancho) proporcion de carta

NORM = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
TO_TENSOR = transforms.Compose([transforms.ToTensor(), NORM])


class PairViews(Dataset):
    """Dos vistas fotograficas distintas de la misma carta."""

    def __init__(self, paths, imsize=IMSIZE):
        self.paths = paths
        self.imsize = imsize

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        p = self.paths[i]
        try:
            base = Image.open(p).convert("RGB").resize(
                (self.imsize[1], self.imsize[0]), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            base = Image.new("RGB", (self.imsize[1], self.imsize[0]), (20, 20, 20))
        rng = random.Random(random.randrange(1 << 30))
        v1 = photo_augment(base.copy(), rng)
        v2 = photo_augment(base.copy(), rng)
        return TO_TENSOR(v1), TO_TENSOR(v2)


class Embedder(nn.Module):
    def __init__(self, dim=256, pretrained=True):
        super().__init__()
        w = MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        m = mobilenet_v3_small(weights=w)
        self.backbone = m.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.proj = nn.Sequential(
            nn.Linear(576, 512), nn.Hardswish(), nn.Linear(512, dim)
        )

    def forward(self, x):
        h = self.pool(self.backbone(x)).flatten(1)
        z = self.proj(h)
        return F.normalize(z, dim=1)


def nt_xent(z1, z2, temp=0.12):
    n = z1.size(0)
    z = torch.cat([z1, z2], 0)
    sim = (z @ z.t()) / temp
    sim.fill_diagonal_(-1e4)
    targets = torch.cat([torch.arange(n, 2 * n), torch.arange(0, n)]).to(z.device)
    return F.cross_entropy(sim, targets)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=48)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--limit", type=int, default=0, help="usar solo N imagenes")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args()

    if args.threads:
        torch.set_num_threads(args.threads)
    os.makedirs(OUT_DIR, exist_ok=True)

    paths = list_images(IMG_DIR)
    if args.limit:
        paths = paths[: args.limit]
    if len(paths) < 32:
        print(f"ERROR: solo {len(paths)} imagenes en {IMG_DIR}. "
              "Corre antes scripts/fetch_dataset.py")
        return 1
    print(f"imagenes de entrenamiento: {len(paths)}", flush=True)

    ds = PairViews(paths)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=args.workers,
                    drop_last=True, persistent_workers=args.workers > 0)
    model = Embedder()
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    steps = args.epochs * len(dl)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps,
                                                pct_start=0.25)
    print(f"pasos totales: {steps} ({len(dl)} por epoca)", flush=True)

    model.train()
    t0 = time.time()
    step = 0
    for ep in range(1, args.epochs + 1):
        run, nb = 0.0, 0
        for v1, v2 in dl:
            z1, z2 = model(v1), model(v2)
            loss = nt_xent(z1, z2)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            run += loss.item()
            nb += 1
            step += 1
            if nb % 10 == 0:
                el = time.time() - t0
                eta = el / max(step, 1) * (steps - step)
                print(f"  ep{ep} {nb}/{len(dl)} loss={run/nb:.4f} "
                      f"eta={eta/60:.1f}min", flush=True)
        print(f"epoca {ep}/{args.epochs} loss={run/max(nb,1):.4f} "
              f"({(time.time()-t0)/60:.1f} min)", flush=True)
        torch.save({"state_dict": model.state_dict(), "dim": 256},
                   os.path.join(OUT_DIR, "embedder.pt"))

    # evaluacion honesta: recall@1 recuperando la carta correcta entre todas
    model.eval()
    with torch.no_grad():
        sub = paths[: min(600, len(paths))]
        refs, qrys = [], []
        for p in sub:
            base = Image.open(p).convert("RGB").resize((IMSIZE[1], IMSIZE[0]), Image.LANCZOS)
            refs.append(TO_TENSOR(base))
            qrys.append(TO_TENSOR(photo_augment(base.copy(), random)))
        R = torch.cat([model(torch.stack(refs[i:i + 64])) for i in range(0, len(refs), 64)])
        Q = torch.cat([model(torch.stack(qrys[i:i + 64])) for i in range(0, len(qrys), 64)])
        sim = Q @ R.t()
        top1 = (sim.argmax(1) == torch.arange(len(sub))).float().mean().item()
        top5 = (sim.topk(5, 1).indices == torch.arange(len(sub)).unsqueeze(1)).any(1).float().mean().item()
    print(f"EVAL sobre {len(sub)} cartas -> recall@1={top1:.3f} recall@5={top5:.3f}",
          flush=True)
    with open(os.path.join(OUT_DIR, "embedder_metrics.txt"), "w") as f:
        f.write(f"cards_eval={len(sub)}\nrecall@1={top1:.4f}\nrecall@5={top5:.4f}\n"
                f"epochs={args.epochs}\nimages={len(paths)}\n")
    print("modelo ->", os.path.join(OUT_DIR, "embedder.pt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
