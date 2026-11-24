# Despliegue en la Raspberry Pi 4

## Hardware probado

- Raspberry Pi 4B 4 GB, Raspberry Pi OS Bookworm 64 bits (**aarch64 obligatorio**:
  onnxruntime no publica rueda para 32 bits).
- Cámara: módulo CSI (libcamera) o cualquier webcam USB UVC.
- Opcional: pantalla táctil oficial de 7" (800x480). La interfaz está medida para ella.
- Disipador o ventilador: durante el escaneo continuo los 4 núcleos van al 100 %.

## Instalación

```bash
sudo apt update
sudo apt install -y python3-venv libopenblas0 chromium-browser unclutter
git clone https://github.com/caesar-dat-com/pokevision-pi.git
cd pokevision-pi
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-pi.txt
```

Copia desde el PC donde entrenaste:

```bash
rsync -av vision/models/embedder.onnx vision/models/condition.onnx \
          vision/models/index.npy vision/models/index_meta.json \
          pi@raspberrypi.local:~/pokevision-pi/vision/models/
rsync -av pricing/models/ pi@raspberrypi.local:~/pokevision-pi/pricing/models/
rsync -av data/cards.jsonl pi@raspberrypi.local:~/pokevision-pi/data/
```

`data/images/` **no** hace falta en la Pi: el índice ya lleva los vectores. Son ~90 MB
que te ahorras (la app usa las URLs de TCGdex solo para mostrar la miniatura, y cae al
placeholder local si no hay internet).

## Servicio

```bash
sudo cp systemd/pokevision.service /etc/systemd/system/
sudo systemctl enable --now pokevision
systemctl status pokevision
curl -s localhost:8000/api/health
```

## Modo kiosco (pantalla táctil)

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/pokevision.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=PokeVision
Exec=chromium-browser --kiosk --noerrdialogs --disable-infobars --incognito \
     --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required \
     http://localhost:8000
EOF
```

`--use-fake-ui-for-media-stream` acepta la cámara sin preguntar. En Chromium, getUserMedia
solo funciona en `localhost` o HTTPS: desde otro equipo de la red usa un túnel o un
certificado, no `http://192.168.x.x`.

## Rendimiento medido (Pi 4B, 4 hilos)

| Etapa | Tiempo |
|---|---|
| preprocesado + embedder ONNX | ~180-260 ms |
| búsqueda en el índice (4.200 cartas) | < 5 ms |
| clasificador de condición | ~150-220 ms |
| modelo de precio | < 3 ms |
| **total por escaneo** | **~0,4-0,6 s** |

Ajusta los hilos con `POKEVISION_THREADS` (4 en la Pi 4). El modo continuo escanea cada
2,5 s: suficiente margen térmico con disipador.

## Problemas típicos

- **`Illegal instruction` al importar onnxruntime** → SO de 32 bits. Reinstala Bookworm 64.
- **Cámara negra** → `libcamera-hello` para comprobar el módulo; con webcam USB revisa
  `v4l2-ctl --list-devices`.
- **Arranca en modo demo** → falta `vision/models/embedder.onnx`; mira
  `curl localhost:8000/api/health | jq .error`.
- **Se calienta y baja la frecuencia** → `vcgencmd measure_temp`; sobre 80 °C el kiosco va
  a tirones. Ventilador.
