#!/usr/bin/env python3
"""Demonio de camara: alimenta /tmp/frame.jpg desde el telefono (ADB) o un simulador.

El telefono queda FIJO apuntando a la mesa; la carta se pone debajo. La Pi toma
los frames por USB y la interfaz (en un laptop de la red) solo consume /api/frame.

Fuentes:

  ipwebcam  La app "IP Webcam" en el telefono, por USB sin WiFi:
            adb forward tcp:8888 tcp:8080  y  MJPEG en http://localhost:8888/video

  screen    Sin instalar nada: la app de camara del telefono abierta en primer
            plano y capturas de pantalla por ADB (~1 fps, vale para escanear).

  dir RUTA  Simulador de demo: rota las imagenes de un directorio (ej. data/images).
            Salva la clase si el telefono falla el dia D.

Uso (en la Pi, servicio aparte):

    python scripts/adb_camera.py --source ipwebcam
    python scripts/adb_camera.py --source screen
    python scripts/adb_camera.py --source dir data/images

Escribe:
    /tmp/frame.jpg   ultimo frame (escritura atomica)
    /tmp/frame.json  {"ok":true,"source":...,"fps":...,"ts":...} para /api/frame_state
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

FRAME = "/tmp/frame.jpg"
STATE = "/tmp/frame.json"


def _write(blob: bytes) -> None:
    tmp = FRAME + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, FRAME)


def _state(ok: bool, source: str, fps: float, err: str = "") -> None:
    with open(STATE + ".tmp", "w") as f:
        json.dump({"ok": ok, "source": source, "fps": round(fps, 1),
                   "ts": time.time(), "error": err}, f)
    os.replace(STATE + ".tmp", STATE)


def adb(*args: str) -> bytes:
    return subprocess.run(["adb", *args], capture_output=True, timeout=30).stdout


# --------------------------------------------------------------------- fuentes
def src_ipwebcam(port: int, fps_target: float):
    """MJPEG de IP Webcam por adb forward. Genera frames a la velocidad de la camara."""
    subprocess.run(["adb", "wait-for-device"], check=False)
    subprocess.run(["adb", "forward", f"tcp:{port}", "tcp:8080"], check=False,
                   capture_output=True)
    import requests

    url = f"http://localhost:{port}/video"
    while True:
        try:
            t0, n = time.time(), 0
            with requests.get(url, stream=True, timeout=(5, 15)) as r:
                r.raise_for_status()
                buf = b""
                for chunk in r.iter_content(4096):
                    buf += chunk
                    # JPEG completo dentro del stream MJPEG
                    s = buf.find(b"\xff\xd8")
                    e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                    if s >= 0 and e > 0:
                        _write(buf[s:e + 2])
                        buf = buf[e + 2:]
                        n += 1
                        if n % 5 == 0:
                            _state(True, "ipwebcam", n / max(0.001, time.time() - t0))
        except Exception as e:  # noqa: BLE001
            _state(False, "ipwebcam", 0, str(e)[:200])
            time.sleep(2)


def src_screen(interval: float, fps_target: float):
    """Capturas de pantalla del telefono con la camara en primer plano (sin apps)."""
    subprocess.run(["adb", "wait-for-device"], check=False)
    # dejar la pantalla encendida y la camara abierta:
    subprocess.run(["adb", "shell", "svc", "power", "stayon", "true"], capture_output=True)
    subprocess.run(["adb", "shell", "am", "start", "-a",
                    "android.media.action.STILL_IMAGE_CAMERA"], capture_output=True)
    while True:
        try:
            png = adb("exec-out", "screencap", "-p")
            if png[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError("screencap no devolvio PNG (telefono desconectado?)")
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(png)).convert("RGB")
            # recortar la barra de estado/notificaciones para no analizarla
            w, h = img.size
            img = img.crop((0, int(h * 0.04), w, int(h * 0.96)))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=88)
            _write(out.getvalue())
            _state(True, "screen", 1 / interval)
        except Exception as e:  # noqa: BLE001
            _state(False, "screen", 0, str(e)[:200])
        time.sleep(interval)


def src_dir(path: str, interval: float, fps_target: float):
    """Simulador: rota imagenes del dataset. Para probar/demosalvar sin telefono."""
    files = sorted(os.path.join(path, f) for f in os.listdir(path)
                   if f.lower().endswith((".webp", ".jpg", ".jpeg", ".png")))
    if not files:
        _state(False, "dir", 0, f"no hay imagenes en {path}")
        sys.exit(1)
    i = 0
    while True:
        p = files[i % len(files)]
        i += 1
        try:
            from PIL import Image
            import io
            img = Image.open(p).convert("RGB")
            out = io.BytesIO()
            img.save(out, "JPEG", quality=90)
            _write(out.getvalue())
            _state(True, f"dir:{os.path.basename(path)}", 1 / interval)
        except Exception as e:  # noqa: BLE001
            _state(False, "dir", 0, str(e)[:200])
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["ipwebcam", "screen", "dir"], required=True)
    ap.add_argument("--dir", default="data/images", help="para --source dir")
    ap.add_argument("--port", type=int, default=8888, help="puerto local del forward")
    ap.add_argument("--interval", type=float, default=1.2,
                    help="segundos entre frames (screen/dir)")
    args = ap.parse_args()
    print(f"camara: fuente={args.source} -> {FRAME}", flush=True)
    if args.source == "ipwebcam":
        src_ipwebcam(args.port, 0)
    elif args.source == "screen":
        src_screen(args.interval, 0)
    else:
        src_dir(args.dir, args.interval, 0)


if __name__ == "__main__":
    main()
