#!/bin/bash
# Änderungen aus diesem Repo in die installierte App übernehmen und Zeitwerk neu starten.
# Aufruf:  ./deploy.sh
# Die App muss schon einmal über den Zeitwerk-Installer eingerichtet worden sein
# (eigenes Python unter ~/Library/Application Support/Zeitwerk/runtime).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="/Applications/Zeitwerk.app"
PY="$HOME/Library/Application Support/Zeitwerk/runtime/venv/bin/python"

[[ -d "$APP" && -x "$PY" ]] || { echo "Zeitwerk ist nicht installiert (erst den Installer ausführen)." >&2; exit 1; }

echo "→ Tests …"
"$PY" -m pytest -q "$DIR/tests" 2>/dev/null || {
  "$PY" -c "import pytest" 2>/dev/null && { echo "Tests fehlgeschlagen, nichts übernommen." >&2; exit 1; }
  echo "  (pytest fehlt in Zeitwerks Python, Tests übersprungen: \"$PY\" -m pip install pytest)"
}

echo "→ Code in die App kopieren …"
rsync -a --delete --exclude '__pycache__' --exclude '.DS_Store' \
  "$DIR/zeitwerk" "$DIR/assets" "$DIR/rules.toml" "$DIR/requirements.txt" "$DIR/README.md" "$DIR/VERSION" \
  "$APP/Contents/Resources/app/"
cp "$DIR/macos/Info.plist" "$APP/Contents/Info.plist"
cp "$DIR/macos/launcher.sh" "$APP/Contents/MacOS/Zeitwerk"
cp "$DIR/macos/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

echo "→ Zeitwerk neu starten …"
pkill -f "zeitwerk.menubar" || true
for _ in 1 2 3 4 5 6; do pgrep -f "zeitwerk.menubar" >/dev/null || break; sleep 1; done
sleep 1
open -a "$APP" || { sleep 3; open -a "$APP"; }
echo "✓ Fertig."
