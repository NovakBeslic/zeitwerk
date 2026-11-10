"""Erzeugt Beispieldaten, um die Übersicht ohne echte Aufzeichnung anzusehen.

    ZEITWERK_HOME=/tmp/zw-demo .venv/bin/python -m zeitwerk.demo
    ZEITWERK_HOME=/tmp/zw-demo .venv/bin/python -m zeitwerk.menubar

(Vorher die laufende Zeitwerk-App über die Menüleiste beenden.)
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from .config import db_path, rules_path
from .db import Store

ACTIVITIES = [  # (App, Bundle-ID, Titel, Domain, Gewicht)
    ("FL Studio", "com.image-line.flstudio", "KYRIE – beat_042.flp", None, 14),
    ("Code", "com.microsoft.VSCode", "PluginProcessor.cpp — Halo", None, 10),
    ("Code", "com.microsoft.VSCode", "dashboard.py — finance", None, 5),
    ("Terminal", "com.apple.Terminal", "zsh", None, 3),
    ("Preview", "com.apple.Preview", "Studienbrief 4 – Lineare Algebra.pdf", None, 6),
    ("Arc", "company.thebrowser.Browser", "Moodle", "moodle.uni.example", 3),
    ("Arc", "company.thebrowser.Browser", "Claude", "claude.ai", 4),
    ("Arc", "company.thebrowser.Browser", "GitHub", "github.com", 3),
    ("Arc", "company.thebrowser.Browser", "Sidechain Tutorial - YouTube", "youtube.com", 3),
    ("Arc", "company.thebrowser.Browser", "Random Video - YouTube", "youtube.com", 5),
    ("Arc", "company.thebrowser.Browser", "Instagram", "instagram.com", 5),
    ("Arc", "company.thebrowser.Browser", "reddit", "reddit.com", 3),
    ("Discord", "com.hnc.Discord", "#general", None, 3),
    ("WhatsApp", "net.whatsapp.WhatsApp", "WhatsApp", None, 3),
    ("Spotify", "com.spotify.client", "Spotify", None, 2),
    ("Finder", "com.apple.finder", "Downloads", None, 2),
    ("Splice", "com.splice.Splice", "Splice", None, 2),
    ("Mystery Tool", "com.example.mystery", "Fenster", None, 1),
]


def main(days: int = 14, seed: int = 7) -> None:
    rng = random.Random(seed)
    rules_path()  # legt rules.toml im Datenordner an
    store = Store(db_path())
    store.conn.execute("DELETE FROM events")
    weights = [a[-1] for a in ACTIVITIES]
    now = datetime.now()

    for d in range(days - 1, -1, -1):
        day = date.today() - timedelta(days=d)
        t = datetime.combine(day, time(rng.randint(8, 10), rng.randint(0, 59)))
        end_of_day = datetime.combine(day, time(rng.randint(21, 23), rng.randint(0, 59)))
        while t < min(end_of_day, now):
            app, bid, title, domain, _ = rng.choices(ACTIVITIES, weights)[0]
            dur = timedelta(minutes=rng.choice([2, 5, 8, 12, 20, 35, 50]))
            end = min(t + dur, end_of_day, now)
            store.conn.execute(
                "INSERT INTO events (start,end,app,bundle_id,title,domain) VALUES (?,?,?,?,?,?)",
                (t.timestamp(), end.timestamp(), app, bid, title, domain))
            # Pausen (Essen, Uni, unterwegs)
            t = end + timedelta(minutes=rng.choice([0, 0, 0, 1, 3, 15, 60]))
    store.conn.commit()
    n = store.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"{n} Beispiel-Einträge in {db_path()} geschrieben.")


if __name__ == "__main__":
    main()
