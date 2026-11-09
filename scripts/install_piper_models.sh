#!/usr/bin/env bash
# Скачивает бесплатные русские ONNX-модели Piper в data/piper/.
# Запуск: bash scripts/install_piper_models.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/piper
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU"
for voice in dmitri irina; do
  for ext in onnx onnx.json; do
    out="data/piper/ru_RU-${voice}-medium.${ext}"
    if [ ! -s "$out" ]; then
      echo "Скачиваю $out"
      curl -L --fail --retry 3 -o "$out" "$BASE/$voice/medium/ru_RU-${voice}-medium.${ext}"
    else
      echo "Уже есть $out"
    fi
  done
done
echo "Готово. voice.piper_model = data/piper/ru_RU-dmitri-medium.onnx"
