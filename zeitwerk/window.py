"""Native Fenster (NSWindow + WKWebView) für Übersicht und Einstellungen.

Die Oberfläche selbst ist zeitwerk/ui/app.html. Sie spricht über eine
Nachrichten-Brücke mit Python: JS → window.webkit.messageHandlers.zeitwerk,
Python → evaluateJavaScript("Zeitwerk.…").
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import objc
from AppKit import (
    NSApplication, NSBackingStoreBuffered, NSMakeRect, NSMenu, NSMenuItem, NSScreen,
    NSToolbar, NSViewHeightSizable, NSViewWidthSizable, NSVisualEffectView, NSWindow,
)
from Foundation import NSURL, NSObject
from WebKit import WKWebView, WKWebViewConfiguration

from . import macui, payload, prefs
from .config import db_path, rules_path

if TYPE_CHECKING:
    from .menubar import Controller

log = logging.getLogger("zeitwerk")

UI = Path(__file__).resolve().parent / "ui" / "app.html"
APP_ICON = Path(__file__).resolve().parent.parent / "assets" / "AppIcon.png"

# Stilmasken (als Zahlen, damit es auf allen macOS-Versionen gleich importiert)
TITLED, CLOSABLE, MINIATURIZABLE, RESIZABLE = 1, 2, 4, 8
MATERIAL_SIDEBAR, MATERIAL_WINDOW_BG = 7, 12
BLEND_BEHIND_WINDOW, STATE_FOLLOWS_WINDOW = 0, 0
TOOLBAR_STYLE_UNIFIED = 3

SYMBOLS = [
    "sun.max", "clock.arrow.circlepath", "calendar", "calendar.badge.clock", "gearshape",
    "record.circle", "tag", "globe", "app", "stopwatch", "lock.shield", "chart.bar",
    "wand.and.stars", "info.circle", "checkmark.circle.fill", "exclamationmark.triangle.fill",
]
PRIVACY_URLS = {
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
}

WKScriptMessageHandler = objc.protocolNamed("WKScriptMessageHandler")
NSWindowDelegate = objc.protocolNamed("NSWindowDelegate")


class _Bridge(NSObject, protocols=[WKScriptMessageHandler, NSWindowDelegate]):
    """Empfängt Nachrichten aus der Oberfläche und das Schließen des Fensters."""

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            self.owner.handle(json.loads(str(message.body())))
        except Exception:
            log.exception("Nachricht aus der Oberfläche fehlgeschlagen")

    def windowWillClose_(self, notification):
        self.owner.closed()


class WebWindow:
    def __init__(self, controller: "Controller", mode: str):
        self.controller = controller
        self.mode = mode
        self.ready = False
        self.period = prefs.load()["last_period"]

        if mode == "main":
            style = TITLED | CLOSABLE | MINIATURIZABLE | RESIZABLE
            rect = NSMakeRect(0, 0, 1060, 740)
        else:  # HIG: Einstellungen ohne Minimieren/Zoomen, Größe folgt dem Bereich
            style = TITLED | CLOSABLE
            rect = NSMakeRect(0, 0, 560, 320)

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        win.setReleasedWhenClosed_(False)
        win.setTitle_("Zeitwerk" if mode == "main" else "Allgemein")
        if mode == "main":
            win.setMinSize_((720, 480))
            win.setFrameAutosaveName_("ZeitwerkMain")
            # Leere Werkzeugleiste im "unified"-Stil, damit Titel und Untertitel (Datum) erscheinen
            toolbar = NSToolbar.alloc().initWithIdentifier_("ZeitwerkToolbar")
            win.setToolbar_(toolbar)
            if hasattr(win, "setToolbarStyle_"):
                win.setToolbarStyle_(TOOLBAR_STYLE_UNIFIED)
        if not (mode == "main" and win.setFrameUsingName_("ZeitwerkMain")):
            win.center()

        # Durchscheinender Hintergrund (Vibrancy); die Seitenleiste in der Oberfläche ist transparent
        effect = NSVisualEffectView.alloc().initWithFrame_(win.contentView().bounds())
        effect.setMaterial_(MATERIAL_SIDEBAR if mode == "main" else MATERIAL_WINDOW_BG)
        effect.setBlendingMode_(BLEND_BEHIND_WINDOW)
        effect.setState_(STATE_FOLLOWS_WINDOW)
        effect.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        win.setContentView_(effect)

        self.bridge = _Bridge.alloc().init()
        self.bridge.owner = self
        config = WKWebViewConfiguration.alloc().init()
        config.userContentController().addScriptMessageHandler_name_(self.bridge, "zeitwerk")
        web = WKWebView.alloc().initWithFrame_configuration_(effect.bounds(), config)
        web.setValue_forKey_(False, "drawsBackground")  # transparent, damit die Vibrancy wirkt
        web.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        effect.addSubview_(web)
        win.setDelegate_(self.bridge)

        url = NSURL.URLWithString_(NSURL.fileURLWithPath_(str(UI)).absoluteString() + "#" + mode)
        web.loadFileURL_allowingReadAccessToURL_(url, NSURL.fileURLWithPath_(str(UI.parent)))
        self.window, self.web = win, web

    # ------------------------------------------------------------ Anzeigen
    def show(self) -> None:
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)

    def closed(self) -> None:
        # Brücke lösen, sonst halten sich WebView und Brücke gegenseitig im Speicher
        self.web.configuration().userContentController().removeScriptMessageHandlerForName_("zeitwerk")
        self.controller.window_closed(self)

    def js(self, fn: str, arg) -> None:
        self.web.evaluateJavaScript_completionHandler_(
            f"window.Zeitwerk && Zeitwerk.{fn}({json.dumps(arg, ensure_ascii=False)})", None)

    # ------------------------------------------------------------ Nachrichten
    def handle(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "ready":
            self.ready = True
            self.js("init", self.init_data())
        elif cmd == "load":
            self.load(msg.get("period", "today"))
        elif cmd == "title":
            self.window.setTitle_(msg.get("title", "Zeitwerk"))
            if hasattr(self.window, "setSubtitle_"):
                self.window.setSubtitle_(msg.get("subtitle") or "")
            if msg.get("height") and self.mode == "settings":
                self.fit_height(float(msg["height"]))
        elif cmd == "setPref":
            new = prefs.set_value(msg["key"], msg["value"])
            self.controller.apply_prefs(new, changed=msg["key"], source=self)
        elif cmd == "openRules":
            subprocess.Popen(["open", "-t", str(rules_path())])
        elif cmd == "openPrivacy":
            subprocess.Popen(["open", PRIVACY_URLS.get(msg.get("pane"), PRIVACY_URLS["screen"])])

    def init_data(self) -> dict:
        p = prefs.load()
        data = {
            "prefs": p,
            "symbols": {n: u for n in SYMBOLS if (u := macui.symbol_data_uri(n))},
            "welcome": self.mode == "main" and not p["onboarded"],
        }
        if APP_ICON.exists():
            data["appIcon"] = "data:image/png;base64," + base64.b64encode(APP_ICON.read_bytes()).decode()
        if self.mode == "settings":
            data["categories"] = payload.categories_overview(self.controller.classifier())
            data["permissions"] = {"screen": screen_capture_allowed()}
        return data

    def load(self, period: str) -> None:
        self.period = period
        if prefs.load()["last_period"] != period:
            prefs.set_value("last_period", period)
        data = payload.overview(db_path(), self.controller.classifier(), period)
        icons = {}
        for it in data.get("items", []):
            bid = it.get("bundle_id")
            if bid and not it.get("web") and (uri := macui.app_icon_data_uri(bid)):
                icons[bid] = uri
        if icons:
            self.js("setIcons", icons)
        self.js("render", data)

    def refresh(self) -> None:
        if self.ready and self.mode == "main" and self.window.isVisible():
            self.load(self.period)

    def push_prefs(self) -> None:
        if self.ready:
            self.js("setPrefs", prefs.load())
            if self.mode == "settings":
                self.js("setPermissions", {"screen": screen_capture_allowed()})

    def fit_height(self, content_h: float) -> None:
        """Fenster an den Inhalt des Bereichs anpassen, obere Kante bleibt stehen."""
        screen_h = (self.window.screen() or NSScreen.mainScreen()).visibleFrame().size.height
        target = min(max(content_h, 160), screen_h * 0.8)
        frame = self.window.frame()
        content = self.window.contentRectForFrameRect_(frame)
        dh = target - content.size.height
        frame.origin.y -= dh
        frame.size.height += dh
        self.window.setFrame_display_animate_(frame, True, self.window.isVisible())


def screen_capture_allowed() -> bool | None:
    try:
        import Quartz
        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return None


# ------------------------------------------------------------ Hauptmenü (nur für Tastenkürzel)
class _MenuTarget(NSObject):
    def openSettings_(self, sender):
        self.controller.open_settings()

    def openMain_(self, sender):
        self.controller.open_main()


def install_main_menu(controller: "Controller") -> None:
    """Als Menüleisten-App ist das Hauptmenü unsichtbar, aber ⌘W, ⌘C, ⌘, usw. funktionieren darüber."""
    target = _MenuTarget.alloc().init()
    target.controller = controller
    controller._menu_target = target  # Referenz halten

    def item(title, action, key, tgt=None):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if tgt is not None:
            it.setTarget_(tgt)
        return it

    main = NSMenu.alloc().initWithTitle_("Hauptmenü")
    for title, entries in [
        ("Zeitwerk", [("Einstellungen …", "openSettings:", ",", target),
                      ("Übersicht", "openMain:", "0", target)]),
        ("Bearbeiten", [("Kopieren", "copy:", "c", None), ("Alles auswählen", "selectAll:", "a", None)]),
        ("Fenster", [("Schließen", "performClose:", "w", None), ("Im Dock ablegen", "performMiniaturize:", "m", None)]),
    ]:
        sub = NSMenu.alloc().initWithTitle_(title)
        for t, a, k, tgt in entries:
            sub.addItem_(item(t, a, k, tgt))
        holder = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        holder.setSubmenu_(sub)
        main.addItem_(holder)
    NSApplication.sharedApplication().setMainMenu_(main)
