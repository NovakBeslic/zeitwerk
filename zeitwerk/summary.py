"""Kurze Tagesübersicht für die Menüleiste (ohne macOS-Abhängigkeiten, damit testbar)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .analysis import fmt_duration, load_events, productivity_score, split_by_sign
from .classify import Classifier


@dataclass
class DaySummary:
    total: float = 0.0
    productive: float = 0.0
    distracting: float = 0.0
    score: float | None = None
    top: list[tuple[str, float]] = field(default_factory=list)
    levels: dict[str, str] = field(default_factory=dict)  # Kategorie → Stufe (p2 … m2)

    @property
    def empty(self) -> bool:
        return self.total < 60  # weniger als eine Minute: noch nichts Aussagekräftiges

    def menubar_title(self, paused: bool = False) -> str:
        if paused:
            return "Pause"
        return "–" if self.empty or self.score is None else f"{self.score:.0f}"

    def menu_lines(self) -> list[str]:
        if self.empty:
            return ["Heute noch keine Daten", "", "", ""]
        pct = lambda s: f"{s / self.total:.0%}"  # noqa: E731
        return [
            f"Heute erfasst: {fmt_duration(self.total)}",
            f"Produktiv: {fmt_duration(self.productive)} · {pct(self.productive)}",
            f"Ablenkend: {fmt_duration(self.distracting)} · {pct(self.distracting)}",
            f"Produktivitätswert: {self.score:.0f} / 100",
        ]

    def top_lines(self, n: int = 3) -> list[str]:
        lines = [f"{name}   {fmt_duration(sec)}" for name, sec in self.top[:n]]
        return lines + [""] * (n - len(lines))


def _day_from(df) -> DaySummary:
    if df.empty:
        return DaySummary()
    parts = split_by_sign(df)
    top = (df.groupby("category")["seconds"].sum().sort_values(ascending=False))
    keys = {2: "p2", 1: "p1", 0: "n", -1: "m1", -2: "m2"}
    levels = {str(c): keys[int(p)] for c, p in df.groupby("category")["productivity"].first().items()}
    return DaySummary(
        total=float(df["seconds"].sum()),
        productive=parts["produktiv"],
        distracting=parts["ablenkend"],
        score=productivity_score(df),
        top=[(str(k), float(v)) for k, v in top.items()],
        levels=levels,
    )


def today(db: Path, classifier: Classifier, now: datetime | None = None) -> DaySummary:
    now = now or datetime.now()
    return _day_from(load_events(db, datetime.combine(now.date(), time.min), now, classifier))


# ------------------------------------------------------------ Widget auf dem Schreibtisch
CURRENT_GAP = 90  # Sekunden: so lange gilt die zuletzt erfasste App noch als „gerade aktiv“


@dataclass
class DeskSummary:
    day: DaySummary = field(default_factory=DaySummary)
    # Website (bei Browsern, falls bekannt) oder App: Name, Bundle-ID der App (für das Symbol), Sekunden
    top_apps: list[tuple[str, str | None, float]] = field(default_factory=list)
    week: list[tuple[datetime, float]] = field(default_factory=list)            # 7 Tage, heute zuletzt
    week_avg: float = 0.0              # Ø der vergangenen Tage mit Daten (ohne heute)
    yesterday_same_time: float = 0.0   # gestern bis zur gleichen Uhrzeit
    current: tuple[str, datetime] | None = None  # Website oder App und seit wann


def desk(db: Path, classifier: Classifier, now: datetime | None = None, top_n: int = 5) -> DeskSummary:
    now = now or datetime.now()
    midnight = datetime.combine(now.date(), time.min)
    days = [midnight - timedelta(days=i) for i in range(6, -1, -1)]
    df = load_events(db, days[0], now, classifier)
    if df.empty:
        return DeskSummary(week=[(d, 0.0) for d in days])

    today_df = df[df["start"] >= midnight]
    per_day = df.groupby("day")["seconds"].sum()
    week = [(d, float(per_day.get(pd.Timestamp(d), 0.0))) for d in days]
    past = [sec for _, sec in week[:-1] if sec > 0]

    y_start, y_end = midnight - timedelta(days=1), now - timedelta(days=1)
    yesterday = df[(df["start"] >= y_start) & (df["start"] < y_end)]
    y_secs = float((yesterday["end"].clip(upper=y_end) - yesterday["start"]).dt.total_seconds().sum())

    apps = (today_df.groupby("label").agg(seconds=("seconds", "sum"), bundle_id=("bundle_id", "first"))
            .sort_values("seconds", ascending=False).head(top_n))
    top_apps = [(str(a), r.bundle_id if isinstance(r.bundle_id, str) else None, float(r.seconds))
                for a, r in apps.iterrows()]

    return DeskSummary(
        day=_day_from(today_df),
        top_apps=top_apps,
        week=week,
        week_avg=sum(past) / len(past) if past else 0.0,
        yesterday_same_time=y_secs,
        current=_current(df, now),
    )


def _current(df, now: datetime) -> tuple[str, datetime] | None:
    """Zuletzt aktive Website/App, falls sie gerade noch läuft, und seit wann sie ohne Unterbrechung vorne ist."""
    rows = df.sort_values("start")
    last = rows.iloc[-1]
    if (now - last["end"]).total_seconds() > CURRENT_GAP:
        return None
    app, since, prev_start = last["label"], last["start"], last["start"]
    for _, r in rows.iloc[-2::-1].iterrows():
        if r["label"] != app or (prev_start - r["end"]).total_seconds() > CURRENT_GAP:
            break
        since = prev_start = r["start"]
    return str(app), since.to_pydatetime() if hasattr(since, "to_pydatetime") else since
