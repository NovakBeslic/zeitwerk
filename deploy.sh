#!/bin/bash
# Alter Name, macht dasselbe wie ./install.sh (installieren oder aktualisieren).
exec "$(cd "$(dirname "$0")" && pwd)/install.sh" "$@"
