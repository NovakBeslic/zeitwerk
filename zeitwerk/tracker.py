"""Hintergrund-Prozess: misst alle paar Sekunden und schreibt in die Datenbank.

Start:  python -m zeitwerk.tracker
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Callable, Optional

from .config import Settings, db_path
from .db import Sample, Store

log = logging.getLogger("zeitwerk")

SELF_BUNDLE_ID = "at.kyrie.zeitwerk"  # Zeitwerk misst sich nicht selbst


class Tracker:
    def __init__(self, store: Store, sampler, settings: Settings,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.sampler = sampler
        self.s = settings
        self.clock = clock
        self._last_tick: Optional[float] = None
        self.paused = False  # von der Menüleiste aus umschaltbar

    @property
    def max_gap(self) -> float:
        # Etwas Puffer, falls eine Messung mal länger dauert (z. B. AppleScript).
        return self.s.sample_interval * 2.5

    def tick(self) -> None:
        now = self.clock()

        # Lange Lücke seit der letzten Messung → Mac hat geschlafen. Nichts zuordnen.
        if self._last_tick is not None and now - self._last_tick > self.max_gap:
            self.store.break_streak()
        self._last_tick = now

        if self.paused:
            self.store.break_streak(cut_at=now)
            return

        snap = self.sampler.snapshot()

        if snap.locked:
            self.store.break_streak(cut_at=now)
            return
        if snap.idle_seconds >= self.s.idle_threshold:
            # Pause: Eintrag auf den Moment der letzten Eingabe zurückschneiden.
            self.store.break_streak(cut_at=now - snap.idle_seconds)
            return

        if (snap.bundle_id or "").lower() == SELF_BUNDLE_ID:
            # Zeit in Zeitwerk selbst (Übersicht, Einstellungen) zählt wie eine Pause.
            self.store.break_streak(cut_at=now)
            return

        private = (snap.app.lower() in self.s.private_apps
                   or (snap.bundle_id or "").lower() in self.s.private_apps)
        title = snap.title if (self.s.store_titles and not private) else None
        domain = snap.domain if (self.s.store_urls and not private) else None

        self.store.record(
            Sample(ts=now, app=snap.app, bundle_id=snap.bundle_id, title=title, domain=domain),
            max_gap=self.max_gap,
        )

    def run_forever(self, stop: threading.Event) -> None:
        log.info("Zeitwerk läuft. Daten: %s", db_path())
        while not stop.is_set():
            started = self.clock()
            try:
                self.tick()
            except Exception:  # ein Fehler soll nie den ganzen Tracker beenden
                log.exception("Messung fehlgeschlagen")
            stop.wait(max(0.5, self.s.sample_interval - (self.clock() - started)))
        self.store.break_streak()
        self.store.close()
        log.info("Zeitwerk beendet.")


def build(settings: Settings | None = None) -> Tracker:
    """Tracker mit echtem macOS-Sampler. Im selben Thread aufrufen, in dem er läuft
    (SQLite-Verbindungen dürfen nicht zwischen Threads wandern)."""
    from .macos import MacSampler

    settings = settings or Settings.load()
    sampler = MacSampler(fetch_titles=settings.store_titles, fetch_urls=settings.store_urls)
    return Tracker(Store(db_path()), sampler, settings)


def main() -> None:
    """Tracker ohne Menüleiste, z. B. für Tests im Terminal."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    build().run_forever(stop)


if __name__ == "__main__":
    main()
