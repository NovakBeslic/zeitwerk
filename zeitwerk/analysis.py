"""Liest Einträge aus der Datenbank und bereitet sie für Auswertungen auf."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .classify import LEVELS, Classifier

SELF_BUNDLE_ID = "at.kyrie.zeitwerk"

COLUMNS = ["start", "end", "seconds", "app", "bundle_id", "title", "domain",
           "label", "category", "productivity", "level", "day", "hour"]


def _split_at_midnight(rows: list[dict]) -> list[dict]:
    """Einträge über Mitternacht werden geteilt, damit Tageswerte stimmen."""
    out = []
    for r in rows:
        start, end = r["start"], r["end"]
        while start.date() < end.date():
            midnight = datetime.combine(start.date() + timedelta(days=1), datetime.min.time())
            out.append({**r, "start": start, "end": midnight})
            start = midnight
        out.append({**r, "start": start, "end": end})
    return out


def load_events(db: Path | str, since: datetime, until: datetime,
                classifier: Classifier) -> pd.DataFrame:
    """Alle Einträge zwischen `since` und `until` (lokale Zeit), auf den Bereich zugeschnitten."""
    if not Path(db).exists():
        return pd.DataFrame(columns=COLUMNS)
    t0, t1 = since.timestamp(), until.timestamp()
    with sqlite3.connect(str(db)) as conn:
        raw = conn.execute(
            "SELECT start, end, app, bundle_id, title, domain FROM events "
            "WHERE end > ? AND start < ? AND end > start "
            "AND COALESCE(bundle_id, '') != ? ORDER BY start",  # ältere Einträge von Zeitwerk selbst
            (t0, t1, SELF_BUNDLE_ID),
        ).fetchall()

    rows = []
    for start, end, app, bid, title, domain in raw:
        cat, prod = classifier.classify(app, bid, title, domain)
        rows.append({
            "start": datetime.fromtimestamp(max(start, t0)),
            "end": datetime.fromtimestamp(min(end, t1)),
            "app": app, "bundle_id": bid, "title": title, "domain": domain,
            "label": domain or app,
            "category": cat, "productivity": prod, "level": LEVELS[prod],
        })
    rows = _split_at_midnight(rows)
    if not rows:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(rows)
    df["seconds"] = (df["end"] - df["start"]).dt.total_seconds()
    df = df[df["seconds"] > 0].copy()
    df["day"] = df["start"].dt.normalize()
    df["hour"] = df["start"].dt.hour
    return df[COLUMNS]


def productivity_score(df: pd.DataFrame) -> float:
    """0–100: 100 = nur sehr produktiv, 50 = neutral, 0 = nur sehr ablenkend."""
    total = df["seconds"].sum()
    if not total:
        return 0.0
    return float(((df["productivity"] + 2) / 4 * df["seconds"]).sum() / total * 100)


def split_by_sign(df: pd.DataFrame) -> dict[str, float]:
    """Sekunden produktiv / neutral / ablenkend."""
    return {
        "produktiv": float(df.loc[df["productivity"] > 0, "seconds"].sum()),
        "neutral": float(df.loc[df["productivity"] == 0, "seconds"].sum()),
        "ablenkend": float(df.loc[df["productivity"] < 0, "seconds"].sum()),
    }


def fmt_duration(seconds: float) -> str:
    m = int(round(seconds / 60))
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"
