"""Einstellungen, die in der App per Schalter geändert werden (prefs.json im Datenordner).

Kategorien bleiben in rules.toml. Hier liegt nur, was das Einstellungsfenster steuert.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import data_dir

LABEL = "at.kyrie.zeitwerk"

DEFAULTS: dict[str, Any] = {
    "show_menubar_extra": True,   # HIG: Menschen entscheiden, ob das Symbol in der Menüleiste ist
    "show_score_in_menubar": True,
    "show_desk_widget": True,     # Widget auf dem Schreibtisch
    "desk_widget_origin": "",     # "x,y" – leer = oben rechts
    "desk_widget_scale": "1",     # Größe des Widgets (0.75 … 1.8)
    "open_at_login": True,
    "store_titles": True,
    "store_urls": True,
    "idle_threshold_seconds": 180,
    "onboarded": False,
    "last_settings_pane": "general",  # HIG: Einstellungen öffnen den zuletzt benutzten Bereich
    "last_period": "today",
}

IDLE_CHOICES = (60, 180, 300, 600)


def path() -> Path:
    return data_dir() / "prefs.json"


def load() -> dict[str, Any]:
    prefs = dict(DEFAULTS)
    try:
        prefs.update({k: v for k, v in json.loads(path().read_text()).items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return prefs


def save(prefs: dict[str, Any]) -> None:
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(prefs, indent=2))
    os.replace(tmp, path())  # atomar, damit nie eine halbe Datei entsteht


def set_value(key: str, value: Any) -> dict[str, Any]:
    if key not in DEFAULTS:
        raise KeyError(key)
    expected = type(DEFAULTS[key])
    if expected is bool:
        value = bool(value)
    elif expected is int:
        value = int(value)
        if key == "idle_threshold_seconds" and value not in IDLE_CHOICES:
            raise ValueError(value)
    else:
        value = str(value)
    prefs = load()
    prefs[key] = value
    save(prefs)
    return prefs


# ------------------------------------------------------------ Beim Anmelden öffnen
def login_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def apply_login_item(enabled: bool, app_path: str | None) -> None:
    """Legt den Autostart an oder entfernt ihn. Ohne bekannten App-Pfad passiert nichts."""
    agent = login_agent_path()
    if not enabled:
        agent.unlink(missing_ok=True)
        return
    if not app_path:
        return
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>{app_path}</string>
  </array>
  <key>RunAtLoad</key>        <true/>
</dict>
</plist>
""")
