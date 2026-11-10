#!/bin/bash
# Zeitwerk aus diesem Repo installieren oder aktualisieren.
#
#   ./install.sh
#
# Beim ersten Mal: legt eine eigene Python-Umgebung an (braucht python3 ab 3.11),
# baut /Applications/Zeitwerk.app und startet Zeitwerk.
# Danach: übernimmt Code-Änderungen in die App und startet Zeitwerk neu.
# Erfasste Zeit, deine Regeln und Einstellungen bleiben immer erhalten.
#
# Zum Testen umlenkbar: ZEITWERK_APP_PATH, ZEITWERK_RUNTIME, ZEITWERK_NO_LAUNCH=1
set -euo pipefail

[[ "$(uname)" == "Darwin" ]] || { echo "Zeitwerk läuft nur auf macOS." >&2; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="${ZEITWERK_APP_PATH:-/Applications/Zeitwerk.app}"
RUNTIME="${ZEITWERK_RUNTIME:-$HOME/Library/Application Support/Zeitwerk/runtime}"
PY="$RUNTIME/venv/bin/python"

# ------------------------------------------------------------ 1. Python-Umgebung (nur beim ersten Mal)
if [[ ! -x "$PY" ]]; then
  BASE="${PYTHON:-python3}"
  if ! command -v "$BASE" >/dev/null || ! "$BASE" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    echo "Zeitwerk braucht Python 3.11 oder neuer." >&2
    echo "Installieren über https://www.python.org/downloads/ oder: brew install python" >&2
    exit 1
  fi
  echo "→ Eigene Python-Umgebung anlegen (einmalig, 1–2 Minuten) …"
  mkdir -p "$RUNTIME"
  "$BASE" -m venv "$RUNTIME/venv"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r "$DIR/requirements.txt"
fi

# ------------------------------------------------------------ 2. Tests (falls pytest vorhanden)
if "$PY" -c "import pytest" 2>/dev/null; then
  echo "→ Tests …"
  "$PY" -m pytest -q -p no:cacheprovider "$DIR/tests" || { echo "Tests fehlgeschlagen, nichts übernommen." >&2; exit 1; }
fi

# ------------------------------------------------------------ 3. App bauen bzw. aktualisieren
echo "→ App bauen: $APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
rsync -a --delete --exclude '__pycache__' --exclude '.DS_Store' \
  "$DIR/zeitwerk" "$DIR/assets" "$DIR/rules.toml" "$DIR/requirements.txt" "$DIR/README.md" "$DIR/VERSION" \
  "$APP/Contents/Resources/app/"
cp "$DIR/macos/Info.plist" "$APP/Contents/Info.plist"
cp "$DIR/macos/launcher.sh" "$APP/Contents/MacOS/Zeitwerk"
cp "$DIR/macos/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
chmod +x "$APP/Contents/MacOS/Zeitwerk"

# ------------------------------------------------------------ 4. Starten
if [[ -n "${ZEITWERK_NO_LAUNCH:-}" ]]; then
  echo "✓ Fertig (nicht gestartet)."
  exit 0
fi
echo "→ Zeitwerk (neu) starten …"
pkill -f "zeitwerk.menubar" || true
for _ in 1 2 3 4 5 6; do pgrep -f "zeitwerk.menubar" >/dev/null || break; sleep 1; done
sleep 1
open -a "$APP" || { sleep 3; open -a "$APP"; }
echo "✓ Fertig. Zeitwerk läuft oben rechts in der Menüleiste."
