"""Bereitet die Daten für das Übersichtsfenster auf (reines Python, ohne macOS, testbar).

Die Oberfläche bekommt fertige Zahlen und Sätze. Nach den Apple-Richtlinien für
Diagramme hat jedes Diagramm einen Titel und eine Zusammenfassung in Worten, und
Werte werden eindeutig beschrieben ("5 Stunden 13 Minuten" statt "5:13").
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .analysis import fmt_duration, load_events, productivity_score, split_by_sign
from .classify import LEVELS, UNCATEGORIZED, Classifier

PERIODS = {
    "today": "Heute",
    "yesterday": "Gestern",
    "week": "Letzte 7 Tage",
    "month": "Letzte 30 Tage",
}
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
LEVEL_KEYS = {2: "p2", 1: "p1", 0: "n", -1: "m1", -2: "m2"}


# ------------------------------------------------------------ Formatierung
def spoken(seconds: float) -> str:
    """Für Screenreader: '2 Stunden 5 Minuten'."""
    m = int(round(seconds / 60))
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h} Stunde" + ("n" if h != 1 else ""))
    if m or not h:
        parts.append(f"{m} Minute" + ("n" if m != 1 else ""))
    return " ".join(parts)


def long_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day}. {MONTHS[d.month - 1]}"


def range_text(a: date, b: date) -> str:
    if a.month == b.month:
        return f"{a.day}.–{b.day}. {MONTHS[b.month - 1]} {b.year}"
    return f"{a.day}. {MONTHS[a.month - 1]} – {b.day}. {MONTHS[b.month - 1]} {b.year}"


def pct(part: float, total: float) -> str:
    return f"{part / total:.0%}".replace("%", "\u00a0%") if total else "0\u00a0%"


# ------------------------------------------------------------ Zeitraum
def period_bounds(period: str, now: datetime) -> tuple[datetime, datetime, date, date]:
    today = now.date()
    start_of = lambda d: datetime.combine(d, time.min)  # noqa: E731
    if period == "today":
        return start_of(today), now, today, today
    if period == "yesterday":
        y = today - timedelta(days=1)
        return start_of(y), start_of(today), y, y
    days = 7 if period == "week" else 30
    first = today - timedelta(days=days - 1)
    return start_of(first), now, first, today


# ------------------------------------------------------------ Bausteine
def _segments(df: pd.DataFrame) -> dict[str, float]:
    s = df.groupby("productivity")["seconds"].sum()
    return {LEVEL_KEYS[int(p)]: round(float(v), 1) for p, v in s.items()}


def _split_hours(df: pd.DataFrame) -> pd.DataFrame:
    """Teilt Einträge an vollen Stunden, damit keine Stunde mehr als 60 Minuten zeigt."""
    rows = []
    for r in df.to_dict("records"):
        start, end = r["start"], r["end"]
        while start < end:
            nxt = min(end, start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            rows.append({**r, "start": start, "end": nxt, "hour": start.hour,
                         "seconds": (nxt - start).total_seconds()})
            start = nxt
    return pd.DataFrame(rows, columns=df.columns)


def _chart(df: pd.DataFrame, first: date, last: date) -> dict:
    if first == last:
        df = _split_hours(df)
        buckets = []
        for h in range(24):
            part = df[df["hour"] == h]
            total = float(part["seconds"].sum())
            buckets.append({
                "label": f"{h}", "short": f"{h}",
                "aria": f"{h} bis {h + 1} Uhr: {spoken(total)} erfasst" if total else f"{h} bis {h + 1} Uhr: nichts erfasst",
                "total": round(total, 1), "segments": _segments(part),
            })
        prod = (df[df["productivity"] > 0].groupby("hour")["seconds"].sum())
        if prod.empty:
            summary = "Noch keine produktive Zeit."
        else:
            h = int(prod.idxmax())
            summary = (f"Am produktivsten zwischen {h} und {h + 1} Uhr "
                       f"({fmt_duration(prod.max())}).")
        return {"kind": "hours", "title": "Über den Tag", "summary": summary,
                "unit": "min", "buckets": buckets}

    buckets = []
    d = first
    while d <= last:
        part = df[df["day"] == pd.Timestamp(d)]
        total = float(part["seconds"].sum())
        p = float(part.loc[part["productivity"] > 0, "seconds"].sum())
        buckets.append({
            "label": f"{WEEKDAYS[d.weekday()][:2]}", "short": f"{d.day}.",
            "aria": f"{long_date(d)}: {spoken(total)} erfasst, davon {spoken(p)} produktiv",
            "total": round(total, 1), "segments": _segments(part),
            "date": d.isoformat(),
        })
        d += timedelta(days=1)
    per_day = df[df["productivity"] > 0].groupby("day")["seconds"].sum()
    if per_day.empty:
        summary = "Noch keine produktive Zeit."
    else:
        best = per_day.idxmax().date()
        avg = per_day.sum() / max(1, df["day"].nunique())
        summary = (f"Produktivster Tag war {long_date(best)} mit {fmt_duration(per_day.max())}. "
                   f"Im Schnitt {fmt_duration(avg)} produktiv pro aktivem Tag.")
    return {"kind": "days", "title": "Pro Tag", "summary": summary, "unit": "h", "buckets": buckets}


def _timeline(df: pd.DataFrame, day: date) -> dict:
    """Spuren pro Kategorie, Zeiten in Minuten seit Mitternacht. Kurze Lücken werden geschlossen."""
    midnight = datetime.combine(day, time.min)
    lanes = []
    order = (df.groupby(["category", "productivity"])["seconds"].sum()
               .reset_index().sort_values(["productivity", "seconds"], ascending=[False, False]))
    for _, row in order.iterrows():
        part = df[df["category"] == row["category"]].sort_values("start")
        spans: list[dict] = []
        for _, e in part.iterrows():
            s = (e["start"] - midnight).total_seconds() / 60
            t = (e["end"] - midnight).total_seconds() / 60
            if spans and s - spans[-1]["e"] <= 2:
                spans[-1]["e"] = max(spans[-1]["e"], t)
                spans[-1]["sec"] += e["seconds"]
                continue
            spans.append({"s": s, "e": t, "sec": e["seconds"], "label": e["label"]})
        for sp in spans:
            sp["text"] = (f"{row['category']}, {int(sp['s'] // 60):02d}:{int(sp['s'] % 60):02d}"
                          f"–{int(sp['e'] // 60):02d}:{int(sp['e'] % 60):02d}, {fmt_duration(sp['sec'])}")
            sp["s"], sp["e"] = round(sp["s"], 1), round(sp["e"], 1)
            del sp["sec"]
        lanes.append({"category": row["category"], "level": LEVEL_KEYS[int(row["productivity"])],
                      "spans": spans})
    first = int(df["start"].min().hour)
    last = int((df["end"].max() - timedelta(seconds=1)).hour) + 1
    return {"start_hour": max(0, first), "end_hour": min(24, max(last, first + 1)), "lanes": lanes}


# ------------------------------------------------------------ Gesamt
def overview(db: Path, classifier: Classifier, period: str = "today",
             now: datetime | None = None) -> dict:
    if period not in PERIODS:
        period = "today"
    now = now or datetime.now()
    since, until, first, last = period_bounds(period, now)
    df = load_events(db, since, until, classifier)

    out: dict = {
        "period": period,
        "title": PERIODS[period],
        "subtitle": long_date(first) if first == last else range_text(first, last),
        "levels": [{"key": LEVEL_KEYS[p], "label": LEVELS[p]} for p in (2, 1, 0, -1, -2)],
        "empty": df.empty,
    }
    if df.empty:
        out["summary"] = ("Für diesen Zeitraum gibt es noch keine Daten. Zeitwerk zeichnet "
                          "automatisch auf, sobald du deinen Mac benutzt.")
        return out

    total = float(df["seconds"].sum())
    parts = split_by_sign(df)
    score = productivity_score(df)
    when = "heute" if period == "today" else "gestern" if period == "yesterday" else "in diesem Zeitraum"
    out["summary"] = (f"Du warst {when} {fmt_duration(total)} am Mac aktiv. "
                      f"{pct(parts['produktiv'], total)} davon waren produktiv, "
                      f"{pct(parts['ablenkend'], total)} ablenkend.")
    out["kpis"] = [
        {"id": "total", "label": "Erfasst", "value": fmt_duration(total), "detail": None,
         "aria": f"Erfasst: {spoken(total)}"},
        {"id": "p", "label": "Produktiv", "value": fmt_duration(parts["produktiv"]),
         "detail": pct(parts["produktiv"], total), "level": "p2",
         "aria": f"Produktiv: {spoken(parts['produktiv'])}, {pct(parts['produktiv'], total)}"},
        {"id": "m", "label": "Ablenkend", "value": fmt_duration(parts["ablenkend"]),
         "detail": pct(parts["ablenkend"], total), "level": "m2",
         "aria": f"Ablenkend: {spoken(parts['ablenkend'])}, {pct(parts['ablenkend'], total)}"},
        {"id": "score", "label": "Produktivitätswert", "value": f"{score:.0f}", "detail": "von 100",
         "score": round(score, 1), "aria": f"Produktivitätswert {score:.0f} von 100"},
    ]
    out["chart"] = _chart(df, first, last)

    cats = (df.groupby(["category", "productivity"])["seconds"].sum().reset_index()
              .sort_values("seconds", ascending=False))
    out["categories"] = [{
        "name": r["category"], "level": LEVEL_KEYS[int(r["productivity"])],
        "levelLabel": LEVELS[int(r["productivity"])],
        "seconds": float(r["seconds"]), "time": fmt_duration(r["seconds"]),
        "share": float(r["seconds"] / total),
    } for _, r in cats.iterrows()]

    items = (df.groupby(["label", "app", "bundle_id", "domain", "category", "productivity"],
                        dropna=False)["seconds"].sum().reset_index()
               .groupby(["label"], dropna=False)
               .agg(seconds=("seconds", "sum"), app=("app", "first"), bundle_id=("bundle_id", "first"),
                    domain=("domain", "first"), category=("category", "first"),
                    productivity=("productivity", "first"))
               .reset_index().sort_values("seconds", ascending=False).head(12))
    out["items"] = [{
        "label": r["label"], "web": isinstance(r["domain"], str) and bool(r["domain"]),
        "app": r["app"], "bundle_id": r["bundle_id"] if isinstance(r["bundle_id"], str) else None,
        "category": r["category"], "level": LEVEL_KEYS[int(r["productivity"])],
        "time": fmt_duration(r["seconds"]), "share": float(r["seconds"] / total),
    } for _, r in items.iterrows()]

    if first == last:
        out["timeline"] = _timeline(df, first)

    unc = df[df["category"] == UNCATEGORIZED]
    if not unc.empty:
        u = (unc.groupby(["label", "app", "bundle_id"], dropna=False)["seconds"].sum()
                .reset_index().sort_values("seconds", ascending=False).head(8))
        out["uncategorized"] = {
            "total": fmt_duration(unc["seconds"].sum()),
            "items": [{"label": r["label"], "app": r["app"],
                       "bundle_id": r["bundle_id"] if isinstance(r["bundle_id"], str) else None,
                       "time": fmt_duration(r["seconds"])} for _, r in u.iterrows()],
        }
    return out


def categories_overview(classifier: Classifier) -> list[dict]:
    """Für den Einstellungsbereich 'Kategorien'."""
    return [{
        "name": c.name, "level": LEVEL_KEYS[c.productivity], "levelLabel": LEVELS[c.productivity],
        "count": len(c.apps) + len(c.domains) + len(c.titles),
        "examples": ", ".join(c.examples) or "Regeln für Fenstertitel",
    } for c in classifier.categories]
