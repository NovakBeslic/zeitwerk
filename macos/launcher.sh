#!/bin/bash
APP="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$HOME/Library/Application Support/Zeitwerk/runtime/venv/bin/python"
export ZEITWERK_APP="$APP"
cd "$APP/Contents/Resources/app" || exit 1
if [ ! -x "$PY" ]; then
  osascript -e 'display alert "Zeitwerk ist unvollständig installiert." message "Bitte den Zeitwerk-Installer noch einmal öffnen." as critical' >/dev/null 2>&1
  exit 1
fi
exec "$PY" -m zeitwerk.menubar
