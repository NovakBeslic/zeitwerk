"""Zeitwerk als Menüleisten-App (oben rechts, neben Ton, WLAN usw.).

Gestaltet nach den Apple Human Interface Guidelines für Menüleisten-Extras:
- ein SF Symbol als Vorlage-Bild, das sich Hell/Dunkel und der Auswahl anpasst
- ein Menü statt eines Popovers
- Menschen entscheiden selbst, ob das Symbol in der Menüleiste erscheint
  (Einstellungen). Ausgeblendet bleibt Zeitwerk über Spotlight erreichbar.

Start:  python -m zeitwerk.menubar
"""

from __future__ import annotations

import fcntl
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import rumps

from . import prefs, summary
from .classify import Classifier
from .config import Settings, data_dir, db_path, rules_path
from .tracker import build

log = logging.getLogger("zeitwerk")

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "menubar.png"  # Ersatz, falls SF Symbols fehlen
REFRESH_SECONDS = 30
PAUSES = [("15 Minuten", 15), ("1 Stunde", 60), ("Für heute", "today"), ("Bis zum Fortsetzen", None)]


def _native(item):
    return getattr(item, "_menuitem", None)


def _set_line(item: rumps.MenuItem, text: str) -> None:
    """Text setzen; leere Zeilen ausblenden statt leere Einträge anzuzeigen."""
    item.title = text or " "
    if (native := _native(item)) is not None:
        native.setHidden_(not text)


def _set_hidden(item: rumps.MenuItem, hidden: bool) -> None:
    if (native := _native(item)) is not None:
        native.setHidden_(hidden)


def _set_symbol(item: rumps.MenuItem, name: str) -> None:
    """SF Symbol vor einem Menüeintrag (HIG: innerhalb einer Gruppe alle oder keiner)."""
    try:
        from . import macui
        if (native := _native(item)) is not None and (img := macui.symbol(name)) is not None:
            native.setImage_(img)
    except Exception:
        pass


class Controller(rumps.App):
    def __init__(self):
        super().__init__("Zeitwerk", icon=str(ICON) if ICON.exists() else None,
                         template=True, quit_button=None)
        self.title = ""
        self.stop = threading.Event()
        self.tracker = None
        self.pause_until: float | None = None   # Zeitstempel; inf = bis zum Fortsetzen
        self.windows: dict[str, object] = {}
        self.day = summary.DaySummary()
        self._classifier: tuple[float, Classifier] | None = None
        self._notice: tuple[str, str] | None = None
        self._started = False
        self.header_view = None
        self.desk_widget = None

        # Kopf: Tagesübersicht (eigene Ansicht mit Balken, siehe _install_native)
        self.header = rumps.MenuItem("Heute")
        self.header_lines = [rumps.MenuItem("…"), rumps.MenuItem("")]
        # Meiste Zeit heute
        self.top_header = rumps.MenuItem("Meiste Zeit heute")
        self.top = [rumps.MenuItem("") for _ in range(3)]
        # Aktionen
        self.open_item = rumps.MenuItem("Übersicht öffnen", callback=self.open_main, key="o")
        self.desk_item = rumps.MenuItem("Widget ausblenden", callback=self.toggle_desk)
        self.pause_menu = rumps.MenuItem("Pausieren")
        for label, value in PAUSES:
            self.pause_menu.add(rumps.MenuItem(label, callback=self._pause_cb(value)))
        self.resume_item = rumps.MenuItem("Tracking fortsetzen", callback=self.resume)
        self.settings_item = rumps.MenuItem("Einstellungen …", callback=self.open_settings, key=",")
        self.quit_item = rumps.MenuItem("Zeitwerk beenden", callback=self.quit_app, key="q")

        self.menu = [
            self.header, *self.header_lines,
            None,
            self.top_header, *self.top,
            None,
            self.open_item, self.desk_item, self.pause_menu, self.resume_item,
            None,
            self.settings_item,
            None,
            self.quit_item,
        ]

        threading.Thread(target=self._run_tracker, name="tracker", daemon=True).start()
        rumps.Timer(self._first_tick, 0.2).start()
        rumps.Timer(self.refresh, REFRESH_SECONDS).start()

    # ------------------------------------------------------------ Start (nach Aufbau der Menüleiste)
    def _first_tick(self, timer) -> None:
        timer.stop()
        if self._started:
            return
        self._started = True
        try:
            self._install_native()
        except Exception:
            log.exception("Native Menüleisten-Elemente nicht verfügbar, nutze einfache Darstellung")
        p = prefs.load()
        self.apply_prefs(p)
        self.refresh()
        if not p["onboarded"]:
            self.open_main()  # Willkommensbildschirm beim ersten Start

    def _install_native(self) -> None:
        from . import macui, window
        from .menuview import HeaderView

        status = self._nsapp.nsstatusitem
        if (img := macui.symbol("stopwatch")) is not None:
            status.button().setImage_(img)
            status.button().setImagePosition_(2)  # Symbol links vom Wert

        # Kopfzeile mit Balken statt drei Textzeilen
        self.header_view = HeaderView.alloc().initWithFrame_(((0, 0), (280, 66)))
        _native(self.header).setView_(self.header_view)
        for it in self.header_lines:
            _set_hidden(it, True)

        for item, name in [(self.open_item, "chart.bar.xaxis"), (self.desk_item, "rectangle.on.rectangle"),
                           (self.pause_menu, "pause.circle"),
                           (self.resume_item, "play.circle"), (self.settings_item, "gearshape"),
                           (self.quit_item, "power")]:
            _set_symbol(item, name)
        self._dot = {k: macui.dot(v) for k, v in macui.LEVEL_COLORS.items()}

        window.install_main_menu(self)
        self._install_reopen()

    def _install_reopen(self) -> None:
        """Ein erneuter Start (Spotlight, Programme-Ordner) öffnet die Übersicht.
        Wichtig, wenn das Symbol in der Menüleiste ausgeblendet ist."""
        import objc

        controller = self

        def reopen(self_, app, has_visible):
            controller.open_main()
            return True

        sel = objc.selector(reopen, selector=b"applicationShouldHandleReopen:hasVisibleWindows:",
                            signature=b"Z@:@Z")
        objc.classAddMethods(type(self._nsapp), [sel])

    # ------------------------------------------------------------ Tracker
    def _run_tracker(self) -> None:
        try:
            self.tracker = build(Settings.load())
            self.tracker.run_forever(self.stop)
        except Exception:
            log.exception("Tracker konnte nicht starten")
            self._notice = ("Tracker-Fehler", "Details in ~/Library/Application Support/Zeitwerk/tracker.log")

    @property
    def paused(self) -> bool:
        return self.pause_until is not None

    def _pause_cb(self, value):
        def cb(_):
            if value is None:
                self.pause_until = float("inf")
            elif value == "today":
                tomorrow = datetime.combine(datetime.now().date() + timedelta(days=1), datetime.min.time())
                self.pause_until = tomorrow.timestamp()
            else:
                self.pause_until = time.time() + value * 60
            self._apply_pause()
        return cb

    def resume(self, _=None) -> None:
        self.pause_until = None
        self._apply_pause()

    def _apply_pause(self) -> None:
        if self.tracker:
            self.tracker.paused = self.paused
        # HIG: der Eintrag zeigt den möglichen Schritt, nicht den Zustand
        _set_hidden(self.pause_menu, self.paused)
        _set_hidden(self.resume_item, not self.paused)
        self.refresh()

    def pause_text(self) -> str:
        if not self.paused:
            return ""
        if self.pause_until == float("inf"):
            return "Pausiert, bis du fortsetzt"
        until = datetime.fromtimestamp(self.pause_until)
        if until.date() > datetime.now().date():
            return "Pausiert für heute"
        return f"Pausiert bis {until:%H:%M} Uhr"

    # ------------------------------------------------------------ Anzeige
    def classifier(self) -> Classifier:
        path = rules_path()
        mtime = path.stat().st_mtime
        if not self._classifier or self._classifier[0] != mtime:
            self._classifier = (mtime, Classifier.from_file(path))
        return self._classifier[1]

    def refresh(self, _=None) -> None:
        if self.pause_until and self.pause_until != float("inf") and time.time() >= self.pause_until:
            self.pause_until = None
            self._apply_pause()
            return
        if self._notice:  # Meldungen aus Hintergrund-Threads hier im Haupt-Thread zeigen
            title, msg = self._notice
            self._notice = None
            try:
                rumps.notification("Zeitwerk", title, msg)
            except Exception:
                log.warning("%s: %s", title, msg)
        try:
            self.day = summary.today(db_path(), self.classifier())
        except Exception:
            log.exception("Übersicht fehlgeschlagen")
            return

        p = prefs.load()
        score = "" if self.day.empty or self.day.score is None else f"{self.day.score:.0f}"
        self.title = (score if p["show_score_in_menubar"] and not self.paused else "")
        self._update_status_tooltip()

        if self.header_view is not None:
            self.header_view.show_day(self.day, self.pause_text())
        else:
            lines = self.day.menu_lines()
            _set_line(self.header, self.pause_text() or lines[0])
            _set_line(self.header_lines[0], lines[1])
            _set_line(self.header_lines[1], lines[2])

        for item, (name, sec) in zip(self.top, self.day.top + [("", 0)] * 3):
            _set_line(item, f"{name}   {summary.fmt_duration(sec)}" if name else "")
            if name and getattr(self, "_dot", None):
                level = self.day.levels.get(name)
                if (native := _native(item)) is not None and level in self._dot:
                    native.setImage_(self._dot[level])
        _set_hidden(self.top_header, not self.day.top)

        self._refresh_desk()
        for w in self.windows.values():
            w.refresh()

    def _refresh_desk(self) -> None:
        if self.desk_widget is None or not self.desk_widget.visible:
            return
        try:
            self.desk_widget.update(summary.desk(db_path(), self.classifier()), self.pause_text())
        except Exception:
            log.exception("Widget-Aktualisierung fehlgeschlagen")

    def _apply_desk(self, show: bool) -> None:
        try:
            if show:
                if self.desk_widget is None:
                    from .deskwidget import DeskWidget
                    self.desk_widget = DeskWidget(on_click=self.open_main, on_close=lambda: self.set_desk(False))
                self.desk_widget.show()
                self._refresh_desk()
            elif self.desk_widget is not None:
                self.desk_widget.hide()
        except Exception:
            log.exception("Widget auf dem Schreibtisch nicht verfügbar")
        self.desk_item.title = "Widget ausblenden" if show else "Widget einblenden"

    def set_desk(self, show: bool) -> None:
        """Wie der Schalter in den Einstellungen: merkt sich die Wahl und aktualisiert offene Fenster."""
        self.apply_prefs(prefs.set_value("show_desk_widget", show), changed="show_desk_widget")

    def toggle_desk(self, _=None) -> None:
        self.set_desk(not prefs.load()["show_desk_widget"])

    def _update_status_tooltip(self) -> None:
        try:
            button = self._nsapp.nsstatusitem.button()
            tip = "Zeitwerk" if self.day.empty else (
                f"Zeitwerk – heute {summary.fmt_duration(self.day.total)}, "
                f"Produktivitätswert {self.day.score:.0f}")
            button.setToolTip_(self.pause_text() or tip)
        except Exception:
            pass

    # ------------------------------------------------------------ Einstellungen anwenden
    def apply_prefs(self, p: dict, changed: str | None = None, source=None) -> None:
        try:  # HIG: Menschen entscheiden, ob das Symbol in der Menüleiste ist
            self._nsapp.nsstatusitem.setVisible_(bool(p["show_menubar_extra"]))
        except Exception:
            pass
        if changed in (None, "show_desk_widget"):
            self._apply_desk(bool(p["show_desk_widget"]))
        if changed in (None, "open_at_login"):
            prefs.apply_login_item(p["open_at_login"], os.environ.get("ZEITWERK_APP"))
        if self.tracker is not None:
            self.tracker.s.idle_threshold = float(p["idle_threshold_seconds"])
            self.tracker.s.store_titles = bool(p["store_titles"])
            self.tracker.s.store_urls = bool(p["store_urls"])
            sampler = getattr(self.tracker, "sampler", None)
            if sampler is not None and hasattr(sampler, "fetch_titles"):
                sampler.fetch_titles, sampler.fetch_urls = p["store_titles"], p["store_urls"]
        if changed in ("show_score_in_menubar", "show_menubar_extra"):
            self.refresh()
        for w in self.windows.values():
            if w is not source:
                w.push_prefs()

    # ------------------------------------------------------------ Fenster
    def _open(self, mode: str) -> None:
        from .window import WebWindow
        w = self.windows.get(mode)
        if w is None:
            w = self.windows[mode] = WebWindow(self, mode)
        w.show()

    def open_main(self, _=None) -> None:
        self._open("main")

    def open_settings(self, _=None) -> None:
        self._open("settings")

    def window_closed(self, w) -> None:
        for k, v in list(self.windows.items()):
            if v is w:
                del self.windows[k]

    def quit_app(self, _=None) -> None:
        self.stop.set()
        time.sleep(0.3)  # Tracker kurz Zeit geben, den letzten Eintrag abzuschließen
        rumps.quit_application()


# Rückwärtskompatibel für Tests/ältere Aufrufe
ZeitwerkApp = Controller


def _single_instance():
    """Verhindert, dass zwei Zeitwerk-Instanzen gleichzeitig messen."""
    lock = open(data_dir() / "zeitwerk.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("Zeitwerk läuft bereits.")
        sys.exit(0)
    return lock  # Referenz behalten, sonst wird die Sperre freigegeben


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(data_dir() / "tracker.log"), logging.StreamHandler()],
    )
    _lock = _single_instance()  # noqa: F841

    # Kein Dock-Symbol, nur Menüleiste (wie der Ton- oder WLAN-Reiter).
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    Controller().run()


if __name__ == "__main__":
    main()
