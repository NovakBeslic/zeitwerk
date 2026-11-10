"""Fragt macOS ab, was gerade passiert.

Benötigte Berechtigungen (Systemeinstellungen → Datenschutz & Sicherheit):
- nichts für App-Name und Idle-Zeit
- "Bildschirmaufnahme" für Fenstertitel (sonst bleibt der Titel leer)
- "Automation" für Browser-URLs (macOS fragt beim ersten Mal nach)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

# AppleScript-Abfrage der aktiven URL je Browser (Bundle-ID → Skript).
# Firefox unterstützt das nicht; dort bleibt nur der Fenstertitel.
_CHROMIUM_SCRIPT = 'tell application id "{bid}" to return URL of active tab of front window'
BROWSER_SCRIPTS = {
    "com.apple.Safari": 'tell application id "com.apple.Safari" to return URL of front document',
    "com.apple.SafariTechnologyPreview": 'tell application id "com.apple.SafariTechnologyPreview" to return URL of front document',
    "com.google.Chrome": _CHROMIUM_SCRIPT,
    "com.brave.Browser": _CHROMIUM_SCRIPT,
    "com.microsoft.edgemac": _CHROMIUM_SCRIPT,
    "company.thebrowser.Browser": _CHROMIUM_SCRIPT,  # Arc
    "company.thebrowser.dia": _CHROMIUM_SCRIPT,      # Dia
    "com.vivaldi.Vivaldi": _CHROMIUM_SCRIPT,
    "com.operasoftware.Opera": _CHROMIUM_SCRIPT,
}


@dataclass
class Snapshot:
    app: str
    bundle_id: Optional[str]
    pid: Optional[int]
    title: Optional[str]
    domain: Optional[str]
    idle_seconds: float
    locked: bool


def domain_from_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    host = urlparse(url.strip()).hostname
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


class MacSampler:
    def __init__(self, fetch_titles: bool = True, fetch_urls: bool = True):
        # Import erst hier, damit der Rest des Pakets auch ohne macOS testbar ist.
        import Quartz  # noqa: F401  (pyobjc-framework-Quartz)
        from AppKit import NSWorkspace  # (pyobjc-framework-Cocoa)

        self._Q = Quartz
        self._ws = NSWorkspace.sharedWorkspace()
        self.fetch_titles = fetch_titles
        self.fetch_urls = fetch_urls

    def idle_seconds(self) -> float:
        Q = self._Q
        return float(Q.CGEventSourceSecondsSinceLastEventType(
            Q.kCGEventSourceStateHIDSystemState, Q.kCGAnyInputEventType))

    def screen_locked(self) -> bool:
        session = self._Q.CGSessionCopyCurrentDictionary() or {}
        return bool(session.get("CGSSessionScreenIsLocked", False))

    def window_title(self, pid: int) -> Optional[str]:
        """Titel des obersten normalen Fensters der App (braucht Bildschirmaufnahme-Recht)."""
        Q = self._Q
        windows = Q.CGWindowListCopyWindowInfo(
            Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
            Q.kCGNullWindowID,
        ) or []
        for w in windows:  # Liste ist von vorne nach hinten sortiert
            if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0:
                name = w.get("kCGWindowName")
                if name:
                    return str(name)
        return None

    @staticmethod
    def browser_url(bundle_id: str) -> Optional[str]:
        script = BROWSER_SCRIPTS.get(bundle_id)
        if not script:
            return None
        try:
            out = subprocess.run(
                ["osascript", "-e", script.format(bid=bundle_id)],
                capture_output=True, text=True, timeout=2,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None

    def snapshot(self) -> Snapshot:
        app = self._ws.frontmostApplication()
        name = str(app.localizedName()) if app else "Unbekannt"
        bid = str(app.bundleIdentifier()) if app and app.bundleIdentifier() else None
        pid = int(app.processIdentifier()) if app else None

        title = self.window_title(pid) if (self.fetch_titles and pid) else None
        domain = domain_from_url(self.browser_url(bid)) if (self.fetch_urls and bid) else None

        return Snapshot(
            app=name, bundle_id=bid, pid=pid, title=title, domain=domain,
            idle_seconds=self.idle_seconds(),
            locked=self.screen_locked() or bid == "com.apple.loginwindow",
        )
