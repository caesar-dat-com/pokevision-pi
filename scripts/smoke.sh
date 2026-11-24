#!/bin/bash
# Prueba de humo del servidor local (ya levantado en el puerto 8099).
cd /home/hades/.hermes/cache/scratch/pokevision-pi || exit 1
B=http://127.0.0.1:8099
echo '=== health'; curl -s $B/api/health | head -c 420; echo
echo '=== index'; curl -s -o /tmp/idx.html -w 'code=%{http_code} bytes=%{size_download}\n' $B/
echo '=== estaticos'
for u in /static/css/app.css /static/css/tokens.css /static/js/app.js /static/js/chart.js /static/fonts/saira-latin-700-normal.woff2; do
  printf '%-48s' "$u"; curl -s -o /dev/null -w '%{http_code} %{size_download}\n' $B$u
done
cp "$(ls data/images/*.webp | head -1)" /tmp/t.webp
.venv/bin/python -c "from PIL import Image; Image.open('/tmp/t.webp').convert('RGB').save('/tmp/test_card.jpg')"
echo '=== scan'; curl -s -F file=@/tmp/test_card.jpg $B/api/scan | head -c 620; echo
echo '=== search'; curl -s "$B/api/search?q=char" | head -c 240; echo
echo '=== collection POST'; curl -s -X POST -H 'Content-Type: application/json' -d '{"card_id":"sv03-125","qty":1}' $B/api/collection | head -c 260; echo
echo '=== log'; tail -4 /tmp/server.log
