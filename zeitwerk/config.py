"""Pfade und Einstellungen.

Alle Daten bleiben lokal unter ~/Library/Application Support/Zeitwerk
(bzw. $ZEITWERK_HOME, falls gesetzt – praktisch zum Testen).
"""

from __future__ import annotations

import os
import shutil
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_RULES = PACKAGE_DIR.parent / "rules.toml"


def data_dir() -> Path:
    env = os.environ.get("ZEITWERK_HOME")
    if env:
        base = Path(env).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Zeitwerk"
    else:
        base = Path.home() / ".local" / "share" / "zeitwerk"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "zeitwerk.db"


def rules_path() -> Path:
    """Die Regeln liegen im Datenordner. Beim ersten Start wird die Vorlage kopiert."""
    path = data_dir() / "rules.toml"
    if not path.exists() and DEFAULT_RULES.exists():
        shutil.copy(DEFAULT_RULES, path)
    return path


@dataclass
class Settings:
    sample_interval: float = 5.0      # Sekunden zwischen zwei Messungen
    idle_threshold: float = 180.0     # ab so vielen Sekunden ohne Eingabe gilt man als weg
    store_titles: bool = True         # Fenstertitel speichern?
    store_urls: bool = True           # Browser-Domains speichern?
    private_apps: tuple[str, ...] = ()  # Apps, deren Titel/URLs nie gespeichert werden

    @classmethod
    def load(cls, path: Path | None = None, prefs: dict | None = None) -> "Settings":
        """Messintervall und private Apps aus rules.toml, Schalter aus dem Einstellungsfenster."""
        from . import prefs as prefs_mod

        path = path or rules_path()
        raw = {}
        if path.exists():
            with open(path, "rb") as f:
                raw = tomllib.load(f).get("settings", {})
        p = prefs if prefs is not None else prefs_mod.load()
        return cls(
            sample_interval=float(raw.get("sample_interval_seconds", 5)),
            idle_threshold=float(p["idle_threshold_seconds"]),
            store_titles=bool(p["store_titles"]),
            store_urls=bool(p["store_urls"]),
            private_apps=tuple(a.lower() for a in raw.get("private_apps", [])),
        )
