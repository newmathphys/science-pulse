#!/usr/bin/env bash
# Устанавливает локальный user-systemd таймер SCM: 09/13/17/21 по местному времени.
# Работает, пока ПК включён; GitHub Actions остаётся вторым контуром.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/scm-pulse.service" <<SERVICE
[Unit]
Description=SCM Science Pulse autopilot
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$ROOT
EnvironmentFile=$ROOT/.env
ExecStart=/usr/bin/env bash -lc './run.sh run'
TimeoutStartSec=1800
SERVICE
cat > "$UNIT_DIR/scm-pulse.timer" <<TIMER
[Unit]
Description=SCM Science Pulse schedule

[Timer]
OnCalendar=*-*-* 09,13,17,21:00:00
Persistent=true
Unit=scm-pulse.service

[Install]
WantedBy=timers.target
TIMER
systemctl --user daemon-reload
systemctl --user enable --now scm-pulse.timer
echo "Установлено: scm-pulse.timer"
systemctl --user list-timers scm-pulse.timer --no-pager || true
