#!/usr/bin/env python3
"""Construye el indice de identificacion y exporta los modelos a ONNX para la Pi.

Salidas en vision/models/:
  embedder.onnx        backbone + proyeccion (entrada 1x3x224x160, salida 1x256 L2-norm)
  condition.onnx       clasificador autentica/falsa/danada (salida logits 1x3)
  index.npy            matriz NxD de embeddings de referencia (float32, normalizada)
  index_meta.json      metadatos alineados con las filas de index.npy

En la Raspberry no hace falta PyTorch: solo onnxruntime + numpy + Pillow.

  python vision/build_index.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vision.train.train_condition import build_model as build_condition  # noqa: E402
from vision.train.train_embedder import Embedder  # noqa: E402

MODELS = os.path.join(ROOT, "vision", "models")
IMG_DIR = os.path.join(ROOT, "data", "images")
CARDS = os.path.join(ROOT, "data", "cards.jsonl")
IMSIZE = (224, 160)
TO_TENSOR = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def export_onnx(model, path, name):
    model.eval()
    dummy = torch.randn(1, 3, IMSIZE[0], IMSIZE[1])
    torch.onnx.export(
        model, dummy, path, input_names=["input"], output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}}, opset_version=13)
    print(f"  {name} -> {path} ({os.path.getsize(path)/1e6:.1f} MB)", flush=True)


def main():
    os.makedirs(MODELS, exist_ok=True)
    emb_ckpt = os.path.join(MODELS, "embedder.pt")
    cond_ckpt = os.path.join(MODELS, "condition.pt")
    if not os.path.exists(emb_ckpt):
        print("ERROR: falta embedder.pt (corre vision/train/train_embedder.py)")
        return 1

    print("exportando a ONNX...", flush=True)
    emb = Embedder(pretrained=False)
    emb.load_state_dict(torch.load(emb_ckpt, map_location="cpu")["state_dict"])
    export_onnx(emb, os.path.join(MODELS, "embedder.onnx"), "embedder")

    if os.path.exists(cond_ckpt):
        cond = build_condition()
        cond.load_state_dict(torch.load(cond_ckpt, map_location="cpu")["state_dict"])
        export_onnx(cond, os.path.join(MODELS, "condition.onnx"), "condition")
    else:
        print("  aviso: no hay condition.pt todavia")

    # ---- indice de referencia
    meta_by_id = {}
    with open(CARDS) as f:
        for line in f:
            try:
                c = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            meta_by_id[c["id"]] = c

    files = sorted(f for f in os.listdir(IMG_DIR) if f.endswith(".webp"))
    print(f"indexando {len(files)} cartas...", flush=True)
    emb.eval()
    vecs, metas, batch, bmeta = [], [], [], []
    t0 = time.time()

    def flush():
        if not batch:
            return
        with torch.no_grad():
            z = emb(torch.stack(batch)).numpy().astype(np.float32)
        vecs.append(z)
        metas.extend(bmeta)
        batch.clear()
        bmeta.clear()

    for i, fn in enumerate(files, 1):
        cid = fn[:-5]
        c = meta_by_id.get(cid, {})
        try:
            im = Image.open(os.path.join(IMG_DIR, fn)).convert("RGB").resize(
                (IMSIZE[1], IMSIZE[0]), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            continue
        batch.append(TO_TENSOR(im))
        cm = ((c.get("pricing") or {}).get("cardmarket") or {})
        tp = ((c.get("pricing") or {}).get("tcgplayer") or {})
        bmeta.append({
            "id": cid, "name": c.get("name"), "set_id": c.get("set_id"),
            "set_name": c.get("set_name"), "local_id": c.get("local_id"),
            "rarity": c.get("rarity"), "image": c.get("image"),
            "price_eur": cm.get("avg1") or cm.get("trend") or cm.get("avg7"),
            "price_usd": (tp.get("normal") or tp.get("holofoil") or {}).get("marketPrice")
            if isinstance(tp, dict) else None,
        })
        if len(batch) == 64:
            flush()
            if i % 640 == 0:
                print(f"  {i}/{len(files)} ({i/(time.time()-t0):.0f} img/s)", flush=True)
    flush()

    M = np.concatenate(vecs, 0) if vecs else np.zeros((0, 256), np.float32)
    np.save(os.path.join(MODELS, "index.npy"), M)
    with open(os.path.join(MODELS, "index_meta.json"), "w") as f:
        json.dump(metas, f, ensure_ascii=False)
    print(f"indice listo: {M.shape} -> {MODELS}/index.npy "
          f"({M.nbytes/1e6:.1f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
