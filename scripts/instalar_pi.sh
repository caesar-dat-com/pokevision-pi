#!/usr/bin/env bash
# Instalador de PokeVision Pi en una Raspberry Pi 4.
#
#   curl -fsSL https://raw.githubusercontent.com/caesar-dat-com/pokevision-pi/main/scripts/instalar_pi.sh | bash
#
# Deja la app funcionando como servicio en el puerto 8000 y, si hay escritorio,
# abriendo sola en pantalla completa al encender. No pide nada por el camino.
set -euo pipefail

REPO=https://github.com/caesar-dat-com/pokevision-pi.git
DEST="${POKEVISION_DIR:-$HOME/pokevision-pi}"
MODELS_URL="https://github.com/caesar-dat-com/pokevision-pi/releases/latest/download/models.zip"
PORT="${POKEVISION_PORT:-8000}"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] && fail "no lo ejecutes como root; hazlo con tu usuario normal (sin sudo delante)"

if [ "$(uname -m)" != "aarch64" ] && [ "$(uname -m)" != "x86_64" ]; then
  fail "sistema de 32 bits ($(uname -m)). onnxruntime necesita Raspberry Pi OS de 64 bits."
fi

say "1/6 Paquetes del sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv python3-pip unzip curl libopenblas0 >/dev/null

say "2/6 Descargando el proyecto en $DEST"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DEST"
fi
cd "$DEST"

say "3/6 Entorno de Python (sin PyTorch: la Pi solo necesita onnxruntime)"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements-pi.txt

say "4/6 Modelos entrenados (~15 MB)"
if curl -fsSL -o /tmp/models.zip "$MODELS_URL"; then
  unzip -oq /tmp/models.zip -d "$DEST"
  rm -f /tmp/models.zip
  echo "   modelos instalados"
else
  echo "   AVISO: no se pudieron bajar los modelos; la app arrancara en modo demo"
fi

say "5/6 Servicio que arranca solo al encender"
SERVICE=/etc/systemd/system/pokevision.service
sudo tee "$SERVICE" >/dev/null <<EOF
[Unit]
Description=PokeVision Pi
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$DEST
Environment=OMP_NUM_THREADS=4
Environment=POKEVISION_THREADS=4
ExecStart=$DEST/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=4
CPUQuota=380%

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q --now pokevision
sudo systemctl restart pokevision

say "6/6 Comprobando"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/tmp/pv_health.json 2>/dev/null; then break; fi
  sleep 2
done
if [ -s /tmp/pv_health.json ]; then
  python3 - <<'PY'
import json
d = json.load(open('/tmp/pv_health.json'))
print(f"   catalogo: {d.get('catalog_cards')} cartas | indice: {d.get('index_cards')} | "
      f"modo demo: {d.get('demo')} | temp: {d.get('temp_c')} C")
PY
else
  fail "el servicio no respondio. Mira: sudo journalctl -u pokevision -n 40"
fi

# kiosco, solo si esta instalado un escritorio
if command -v chromium-browser >/dev/null || command -v chromium >/dev/null; then
  CHROME=$(command -v chromium-browser || command -v chromium)
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/pokevision.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PokeVision
Exec=$CHROME --kiosk --noerrdialogs --disable-infobars --incognito --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required http://localhost:$PORT
X-GNOME-Autostart-enabled=true
EOF
  echo "   kiosco configurado: al reiniciar abre solo a pantalla completa"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<EOF

  LISTO.

  En la propia Pi:      http://localhost:$PORT
  Desde la red de casa: http://${IP:-IP_DE_LA_PI}:$PORT

  Mandale esto a Cesar:  IP = ${IP:-?}   hostname = $(hostname)

  Estado:   systemctl status pokevision
  Registro: sudo journalctl -u pokevision -f
EOF
