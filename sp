#!/usr/bin/env bash
# SCM operator entry: один вход для владельца.
set -uo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

cmd="${1:-enter}"
shift || true

case "$cmd" in
  enter)
    echo "=== SCM / Science Content Machine ==="
    "$PY" -m science_pulse.cli status
    echo
    "$PY" -m science_pulse.cli doctor || true
    echo
    "$PY" -m science_pulse.cli preflight --no-media || true
    echo
    "$PY" -m science_pulse.cli knowledge stats || true
    ;;
  check)
    "$PY" -m unittest discover
    "$PY" -m science_pulse.cli verify
    "$PY" -m science_pulse.cli preflight --no-media
    "$PY" -m science_pulse.cli knowledge index
    "$PY" -m science_pulse.cli knowledge integrity
    ;;
  knowledge)
    "$PY" -m science_pulse.cli knowledge "$@"
    ;;
  growth)
    "$PY" -m science_pulse.cli growth "$@"
    ;;
  next)
    "$PY" -m science_pulse.cli next "$@"
    ;;
  watch)
    "$PY" -m science_pulse.cli watch "$@"
    ;;
  threads-token)
    "$PY" -m science_pulse.cli threads-token "$@"
    ;;
  videos)
    "$PY" -m science_pulse.cli videos "$@"
    ;;
  launch)
    echo "=== SCM launch: Telegram + Threads ==="
    "$PY" -m science_pulse.cli auth-check
    "$PY" -c "from science_pulse.config import load_config; from science_pulse.publishers.threads import ThreadsPublisher; print('Threads image:', ThreadsPublisher(load_config()).image_mode())"
    echo
    "$PY" -m science_pulse.cli preflight --no-media
    echo
    "$PY" -m science_pulse.cli doctor
    ;;
  publish)
    "$PY" -m science_pulse.cli publish "$@"
    ;;
  site)
    "$PY" -m science_pulse.cli site "$@"
    ;;
  admin)
    "$PY" -m science_pulse.cli admin "$@"
    ;;
  daemon)
    "$PY" -m science_pulse.cli daemon "$@"
    ;;
  stop)
    if [ -f data/admin.pid ]; then
      kill "$(cat data/admin.pid)" 2>/dev/null || true
      rm -f data/admin.pid
      echo "Пульт остановлен."
    else
      echo "Пульт не запущен (data/admin.pid нет)."
    fi
    ;;
  docs)
    echo "docs/INDEX.md"
    sed -n '1,120p' docs/INDEX.md
    ;;
  help|*)
    cat <<'EOF'
SCM operator entry
  ./sp enter            статус, doctor, preflight, knowledge
  ./sp check            тесты + verify + preflight + knowledge integrity
  ./sp knowledge ...    index|search|stats|claim|note|integrity|export
  ./sp next             что осталось до релиза: Threads + Cloudflare
  ./sp watch            что изменилось в API площадок
  ./sp threads-token    проверить/обменять Threads-токен
  ./sp videos           реестр сгенерированных видео
  ./sp launch           проверить ключи Telegram/Threads и готовность
  ./sp publish [args]   опубликовать следующий пост
  ./sp site             пересобрать сайт
  ./sp admin            Telegram-пульт
  ./sp daemon           локальный планировщик
  ./sp stop             остановить пульт
  ./sp docs             карта документации
EOF
    ;;
esac
