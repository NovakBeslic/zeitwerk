"""SQLite-Speicher.

Statt jede Messung einzeln zu speichern, wird ein Eintrag verlängert,
solange dieselbe App/derselbe Titel/dieselbe Domain aktiv bleibt
("Heartbeat-Merge"). So bleibt die Datenbank klein.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    start     REAL NOT NULL,   -- Unix-Zeit in Sekunden
    end       REAL NOT NULL,
    app       TEXT NOT NULL,
    bundle_id TEXT,
    title     TEXT,
    domain    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
"""


@dataclass
class Sample:
    """Eine einzelne Messung: was war zum Zeitpunkt `ts` im Vordergrund?"""
    ts: float
    app: str
    bundle_id: Optional[str] = None
    title: Optional[str] = None
    domain: Optional[str] = None

    def key(self) -> tuple:
        return (self.app, self.bundle_id, self.title, self.domain)


class Store:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._last_id: Optional[int] = None
        self._last_key: Optional[tuple] = None
        self._last_end: Optional[float] = None

    def record(self, sample: Sample, max_gap: float) -> None:
        """Hängt eine Messung an.

        Gleiches Fenster wie zuletzt und Lücke <= max_gap → letzten Eintrag verlängern.
        Sonst neuen Eintrag beginnen. Bei einem Wechsel wird der alte Eintrag
        bis zum aktuellen Zeitpunkt verlängert, damit keine Lücken entstehen.
        """
        gap_ok = self._last_end is not None and sample.ts - self._last_end <= max_gap
        if gap_ok and sample.key() == self._last_key:
            self._set_end(sample.ts)
            return
        if gap_ok:
            self._set_end(sample.ts)  # vorheriges Fenster lief bis jetzt
        cur = self.conn.execute(
            "INSERT INTO events (start, end, app, bundle_id, title, domain) VALUES (?,?,?,?,?,?)",
            (sample.ts, sample.ts, sample.app, sample.bundle_id, sample.title, sample.domain),
        )
        self.conn.commit()
        self._last_id = cur.lastrowid
        self._last_key = sample.key()
        self._last_end = sample.ts

    def break_streak(self, cut_at: Optional[float] = None) -> None:
        """Beendet den laufenden Eintrag (z. B. bei Inaktivität oder Sperrbildschirm).

        `cut_at` kürzt den Eintrag zurück, etwa auf den Zeitpunkt der letzten Eingabe,
        damit Pausen nicht als Arbeitszeit zählen.
        """
        if self._last_id is not None and cut_at is not None:
            self.conn.execute(
                "UPDATE events SET end = MAX(start, MIN(end, ?)) WHERE id = ?",
                (cut_at, self._last_id),
            )
            self.conn.commit()
        self._last_id = self._last_key = self._last_end = None

    def _set_end(self, ts: float) -> None:
        self.conn.execute("UPDATE events SET end = ? WHERE id = ?", (ts, self._last_id))
        self.conn.commit()
        self._last_end = ts

    def close(self) -> None:
        self.conn.close()
