#!/usr/bin/env python3
"""Ingesta de datos reales desde TCGdex.

Descarga:
  data/cards.jsonl        -> metadatos + pricing de cada carta
  data/images/<id>.webp   -> imagen oficial (low res) de cada carta

Uso:
  python scripts/fetch_dataset.py --sets 25 --workers 24
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://api.tcgdex.net/v2/en"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
IMG_DIR = os.path.join(DATA, "images")
UA = {"User-Agent": "pokevision-pi/1.0 (dataset builder)"}


def get_json(url, retries=3, timeout=25):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                return {"__error__": str(e), "__url__": url}
            time.sleep(1.5 * (i + 1))
    return None


def fetch_image(url, dest, retries=3):
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return True
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                blob = r.read()
            if len(blob) < 1000:
                return False
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, dest)
            return True
        except Exception:  # noqa: BLE001
            if i == retries - 1:
                return False
            time.sleep(1.0 * (i + 1))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", type=int, default=25, help="cuantos sets recientes")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    os.makedirs(IMG_DIR, exist_ok=True)

    sets = get_json(f"{API}/sets")
    if not isinstance(sets, list):
        print("ERROR listando sets:", sets)
        return 1
    # los sets llegan en orden cronologico; tomamos los mas recientes con cartas
    sets = [s for s in sets if s.get("cardCount", {}).get("total", 0) > 0]
    chosen = sets[-args.sets:]
    print(f"sets totales={len(sets)} elegidos={len(chosen)}: "
          f"{', '.join(s['id'] for s in chosen)}", flush=True)

    card_ids = []
    for s in chosen:
        det = get_json(f"{API}/sets/{s['id']}")
        if not isinstance(det, dict) or "cards" not in det:
            print("  skip set", s["id"], det if isinstance(det, dict) else "")
            continue
        for c in det["cards"]:
            card_ids.append((c["id"], s["id"], s.get("name", "")))
        print(f"  set {s['id']:>8} {s.get('name','')[:28]:<28} cartas={len(det['cards'])}", flush=True)
    print("total cartas a consultar:", len(card_ids), flush=True)

    out_path = os.path.join(DATA, "cards.jsonl")
    done = set()
    if os.path.exists(out_path):
        with open(out_path) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["id"])
                except Exception:  # noqa: BLE001
                    pass
        print("ya existentes:", len(done), flush=True)

    todo = [c for c in card_ids if c[0] not in done]
    ok = err = 0
    t0 = time.time()
    with open(out_path, "a") as out, ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(get_json, f"{API}/cards/{cid}"): (cid, sid, sname)
                for cid, sid, sname in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            cid, sid, sname = futs[fut]
            d = fut.result()
            if not isinstance(d, dict) or "__error__" in d or "id" not in d:
                err += 1
                continue
            rec = {
                "id": d["id"],
                "name": d.get("name"),
                "set_id": sid,
                "set_name": sname,
                "local_id": d.get("localId"),
                "rarity": d.get("rarity"),
                "category": d.get("category"),
                "illustrator": d.get("illustrator"),
                "hp": d.get("hp"),
                "types": d.get("types"),
                "stage": d.get("stage"),
                "suffix": d.get("suffix"),
                "regulation_mark": d.get("regulationMark"),
                "variants": d.get("variants"),
                "image": d.get("image"),
                "set_total": (d.get("set") or {}).get("cardCount", {}).get("total"),
                "set_release": (d.get("set") or {}).get("releaseDate"),
                "pricing": d.get("pricing"),
                "updated": d.get("updated"),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            ok += 1
            if n % 250 == 0:
                out.flush()
                print(f"  {n}/{len(todo)} ok={ok} err={err} "
                      f"{n/(time.time()-t0):.1f} req/s", flush=True)
    print(f"metadatos listos ok={ok} err={err} -> {out_path}", flush=True)

    if args.no_images:
        return 0

    # imagenes
    recs = []
    with open(out_path) as f:
        for line in f:
            try:
                recs.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    jobs = []
    for r in recs:
        if not r.get("image"):
            continue
        dest = os.path.join(IMG_DIR, r["id"].replace("/", "_") + ".webp")
        jobs.append((r["image"] + "/low.webp", dest))
    print("imagenes a bajar:", len(jobs), flush=True)
    got = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch_image, u, d): d for u, d in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            if fut.result():
                got += 1
            else:
                fail += 1
            if n % 500 == 0:
                print(f"  img {n}/{len(jobs)} ok={got} fail={fail} "
                      f"{n/(time.time()-t0):.1f} img/s", flush=True)
    print(f"imagenes listas ok={got} fail={fail} -> {IMG_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
