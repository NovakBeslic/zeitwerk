"""Widget auf dem Schreibtisch: Tagesübersicht, Top 5 Apps, letzte 7 Tage, aktive App.

Ein randloses Fenster auf Höhe der Schreibtischsymbole (hinter allen anderen
Fenstern), auf allen Spaces. Ziehen verschiebt es (Position wird gemerkt),
ein Klick öffnet die Übersicht. Gezeichnet mit dynamischen Systemfarben auf
Vibrancy, damit Hell/Dunkel automatisch stimmt.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Callable

import objc
from AppKit import (
    NSAttributedString, NSBackingStoreBuffered, NSBezierPath, NSColor, NSEvent, NSFont,
    NSFontAttributeName, NSForegroundColorAttributeName, NSImage, NSImageResizingModeStretch, NSMakeRect,
    NSInsetRect, NSMutableParagraphStyle, NSPanel, NSPointInRect, NSParagraphStyleAttributeName, NSScreen, NSView,
    NSTrackingArea, NSVisualEffectView, NSWorkspace,
)
from Quartz import CGWindowLevelForKey, kCGDesktopIconWindowLevelKey

from . import prefs
from .analysis import fmt_duration

if TYPE_CHECKING:
    from .summary import DeskSummary

log = logging.getLogger("zeitwerk")

W, H = 300, 332
P = 16                 # Innenabstand
ROW = 22               # Höhe einer App-Zeile
TOP_N = 5
MIN_APP_SECONDS = 60   # Apps unter einer Minute (z. B. Systemdialoge) nicht in die Top-Liste
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

BORDERLESS, NONACTIVATING = 0, 1 << 7
JOIN_ALL_SPACES, STATIONARY, IGNORES_CYCLE = 1 << 0, 1 << 4, 1 << 6
MATERIAL_POPOVER, BLEND_BEHIND_WINDOW, STATE_ACTIVE = 6, 0, 1
SOURCE_OVER = 2
WEIGHT_REGULAR, WEIGHT_MEDIUM, WEIGHT_SEMIBOLD, WEIGHT_BOLD = 0.0, 0.23, 0.3, 0.4
TRUNCATE_TAIL = 4
TRACK_ENTER_EXIT, TRACK_ALWAYS, TRACK_VISIBLE_RECT = 0x01, 0x80, 0x200
M = 9    # Rand ums Widget, damit der Ausblenden-Knopf wie bei macOS-Widgets auf der Ecke sitzt
CLOSE_D = 18
GRIP = 18                         # Ziehfläche unten links zum Skalieren (in Widget-Punkten)
MIN_SCALE, MAX_SCALE = 0.75, 1.8  # darunter wird es unlesbar, darüber füllt es den Schreibtisch


def scale_for_drag(start: float, dx: float, dy: float) -> float:
    """Neue Skalierung beim Ziehen am Griff unten links (dx nach rechts, dy nach oben in
    Bildschirmpunkten). Nach links/unten = größer. Seitenverhältnis bleibt; es zählt die
    Richtung, in die weiter gezogen wurde."""
    by_w = (W * start - dx) / W
    by_h = (H * start - dy) / H
    s = by_w if abs(by_w - start) >= abs(by_h - start) else by_h
    return round(min(MAX_SCALE, max(MIN_SCALE, s)), 3)


# ------------------------------------------------------------ Zeichen-Helfer
def _font(size: float, weight: float = WEIGHT_REGULAR, digits: bool = False):
    if digits:
        return NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)
    return NSFont.systemFontOfSize_weight_(size, weight)


def _text(s: str, font, color, truncate: bool = False):
    attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
    if truncate:
        para = NSMutableParagraphStyle.alloc().init()
        para.setLineBreakMode_(TRUNCATE_TAIL)
        attrs[NSParagraphStyleAttributeName] = para
    return NSAttributedString.alloc().initWithString_attributes_(s, attrs)


def _right(t, x_right: float, y: float) -> None:
    t.drawAtPoint_((x_right - t.size().width, y))


def _round(rect, r: float, color) -> None:
    color.setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, r, r).fill()


def fmt_hm(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60}:{m % 60:02d}"


def _short(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"


_icons: dict[str, object] = {}


def _icon(bundle_id: str | None):
    if not bundle_id:
        return None
    if bundle_id not in _icons:
        ws = NSWorkspace.sharedWorkspace()
        url = ws.URLForApplicationWithBundleIdentifier_(bundle_id)
        _icons[bundle_id] = ws.iconForFile_(url.path()) if url is not None else None
    return _icons[bundle_id]


def _score_color(score: float):
    if score >= 60:
        return NSColor.systemBlueColor()
    if score >= 40:
        return NSColor.labelColor()
    return NSColor.systemRedColor()


# ------------------------------------------------------------ Ansicht
class DeskView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(DeskView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.data = None
        self.pause = ""
        self.on_click = None
        self.on_moved = None
        self.widget = None
        self.hover = False
        self._drag = None
        self.setAccessibilityElement_(True)
        self.setAccessibilityRole_("AXGroup")
        return self

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    @objc.python_method
    def show(self, data: "DeskSummary", pause_text: str = "") -> None:
        self.data, self.pause = data, pause_text
        d = data.day
        label = ("Heute noch keine Daten" if d.empty else
                 f"Heute {fmt_duration(d.total)} am Laptop, Produktivitätswert {d.score:.0f}. Meiste Zeit: "
                 + ", ".join(f"{a} {fmt_duration(s)}" for a, _, s in data.top_apps if s >= MIN_APP_SECONDS))
        self.setAccessibilityLabel_(label)
        self.setNeedsDisplay_(True)

    # ---------------------------------------------------- Maus: ziehen = verschieben, klicken = öffnen
    @objc.python_method
    def _in_grip(self, event) -> bool:
        p = self.convertPoint_fromView_(event.locationInWindow(), None)  # in Widget-Punkten (W × H)
        return p.x <= GRIP and p.y >= H - GRIP

    def mouseDown_(self, event):
        if self.widget is not None and self._in_grip(event):
            self._drag = ("resize", NSEvent.mouseLocation(), self.widget.scale)
            return
        self._drag = (NSEvent.mouseLocation(), self.window().frame().origin, False)

    def mouseDragged_(self, event):
        if not self._drag:
            return
        if self._drag[0] == "resize":
            _, start, s0 = self._drag
            now = NSEvent.mouseLocation()
            self.widget.set_scale(scale_for_drag(s0, now.x - start.x, now.y - start.y))
            return
        start, origin, _ = self._drag
        now = NSEvent.mouseLocation()
        dx, dy = now.x - start.x, now.y - start.y
        if abs(dx) + abs(dy) > 3:
            self._drag = (start, origin, True)
        if self._drag[2]:
            self.window().setFrameOrigin_((origin.x + dx, origin.y + dy))

    def mouseUp_(self, event):
        if self._drag and self._drag[0] == "resize":
            self._drag = None
            self.widget.save()
            return
        moved = bool(self._drag and self._drag[2])
        self._drag = None
        cb = self.on_moved if moved else self.on_click
        if cb:
            cb()

    # ---------------------------------------------------- Zeichnen
    def drawRect_(self, rect):
        data = self.data
        if data is None:
            return
        day = data.day
        empty = day.empty
        label, second = NSColor.labelColor(), NSColor.secondaryLabelColor()
        caps = _font(10.5, WEIGHT_SEMIBOLD)
        y = 16

        # Kopf: Zeit heute, rechts Produktivitätswert
        _text("HEUTE AM LAPTOP", caps, second).drawAtPoint_((P, y))
        _right(_text("PRODUKTIV", caps, second), W - P, y)
        y += 14
        _text(fmt_duration(day.total) if not empty else "0 min", _font(26, WEIGHT_BOLD, True), label).drawAtPoint_((P, y))
        if not empty and day.score is not None:
            _right(_text(f"{day.score:.0f}", _font(24, WEIGHT_BOLD, True), _score_color(day.score)), W - P, y + 2)
        y += 36

        # Aufteilung produktiv / neutral / ablenkend
        bar = NSMakeRect(P, y, W - 2 * P, 7)
        _round(bar, 3.5, NSColor.quaternaryLabelColor())
        neutral = max(0.0, day.total - day.productive - day.distracting)
        if not empty and day.total > 0:
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bar, 3.5, 3.5).addClip()
            parts = [(v, c) for v, c in [(day.productive, NSColor.systemBlueColor()),
                                         (neutral, NSColor.systemGrayColor()),
                                         (day.distracting, NSColor.systemRedColor())] if v > 0]
            usable, x = bar.size.width - 2 * (len(parts) - 1), bar.origin.x
            for v, color in parts:
                seg = max(2.0, usable * v / day.total)
                color.setFill()
                NSBezierPath.fillRect_(NSMakeRect(x, bar.origin.y, seg, bar.size.height))
                x += seg + 2
            NSBezierPath.bezierPathWithRect_(self.bounds()).setClip()
        y += 12
        text = ("Noch keine Daten. Zeitwerk zeichnet automatisch auf." if empty else
                f"{fmt_hm(day.productive)} produktiv · {fmt_hm(neutral)} neutral · {fmt_hm(day.distracting)} ablenkend")
        _text(text, _font(11, WEIGHT_REGULAR, True), second).drawAtPoint_((P, y))
        y += 24

        # Top 5 Apps
        rows_top = y
        apps = [a for a in data.top_apps if a[2] >= MIN_APP_SECONDS][:TOP_N]
        longest = apps[0][2] if apps else 1
        name_w, time_w = 84, 40
        bar_x = P + 22 + name_w + 6
        bar_w = W - P - time_w - 6 - bar_x
        for name, bid, sec in apps:
            if (icon := _icon(bid)) is not None:
                icon.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                    NSMakeRect(P, y + 1, 16, 16), NSMakeRect(0, 0, 0, 0), SOURCE_OVER, 1.0, True, None)
            else:
                _round(NSMakeRect(P, y + 1, 16, 16), 4, NSColor.tertiaryLabelColor())
            _text(name, _font(12.5, WEIGHT_MEDIUM), label, truncate=True).drawInRect_(
                NSMakeRect(P + 22, y + 1, name_w, 17))
            track = NSMakeRect(bar_x, y + 6, bar_w, 6)
            _round(track, 3, NSColor.quaternaryLabelColor())
            _round(NSMakeRect(bar_x, y + 6, max(6.0, bar_w * sec / longest), 6), 3,
                   NSColor.controlAccentColor())
            _right(_text(fmt_hm(sec), _font(12, WEIGHT_REGULAR, True), second), W - P, y + 1)
            y += ROW
        if not apps:
            _text("Noch keine Apps erfasst", _font(12), NSColor.tertiaryLabelColor()).drawAtPoint_((P, y + 1))
        y = rows_top + TOP_N * ROW + 6

        # Letzte 7 Tage
        avg = f"LETZTE 7 TAGE · Ø {_short(data.week_avg)}" if data.week_avg else "LETZTE 7 TAGE"
        _text(avg, caps, second).drawAtPoint_((P, y))
        if not empty and data.yesterday_same_time:
            diff = day.total - data.yesterday_same_time
            sign = "+" if diff >= 0 else "−"
            _right(_text(f"{sign}{_short(abs(diff))} ggü. gestern", _font(10.5, WEIGHT_MEDIUM, True), second),
                   W - P, y)
        y += 18
        peak = max([s for _, s in data.week] + [1.0])
        gap, area = 6, 38
        bw = (W - 2 * P - gap * 6) / 7
        accent = NSColor.controlAccentColor()
        for i, (d, sec) in enumerate(data.week):
            x = P + i * (bw + gap)
            today = i == len(data.week) - 1
            h = max(3.0, area * sec / peak) if sec > 0 else 3.0
            color = accent if today else accent.colorWithAlphaComponent_(0.45)
            if sec <= 0:
                color = NSColor.quaternaryLabelColor()
            _round(NSMakeRect(x, y + area - h, bw, h), 3, color)
            wd = _text(WEEKDAYS[d.weekday()], _font(10, WEIGHT_SEMIBOLD if today else WEIGHT_REGULAR),
                       label if today else second)
            wd.drawAtPoint_((x + (bw - wd.size().width) / 2, y + area + 3))
        y += area + 20

        # Fußzeile: was gerade läuft
        NSColor.separatorColor().setFill()
        NSBezierPath.fillRect_(NSMakeRect(P, y, W - 2 * P, 1))
        y += 9
        if self.pause:
            dot, line = NSColor.systemOrangeColor(), _text(self.pause, _font(11.5), NSColor.systemOrangeColor())
        elif data.current:
            app, since = data.current
            mins = max(0, int((datetime.now() - since).total_seconds() // 60))
            dot = NSColor.systemGreenColor()
            line = _text(f"Gerade: {app} · seit {_short(mins * 60) if mins else 'gerade eben'}",
                         _font(11.5), second, truncate=True)
        else:
            dot, line = NSColor.tertiaryLabelColor(), _text("Gerade keine Aktivität", _font(11.5), second)
        dot.setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(P, y + 4.5, 7, 7)).fill()
        line.drawInRect_(NSMakeRect(P + 13, y, W - 2 * P - 13, 16))

        if self.hover:  # Griff zum Skalieren, wie die Ecke eines Fensters
            NSColor.tertiaryLabelColor().setStroke()
            grip = NSBezierPath.bezierPath()
            grip.setLineWidth_(1.3)
            grip.setLineCapStyle_(1)
            for k in (4, 8):
                grip.moveToPoint_((6 + k, H - 6)); grip.lineToPoint_((6, H - 6 - k))
            grip.stroke()



class CloseButton(NSView):
    """Runder ⓧ-Knopf auf der linken oberen Ecke, nur sichtbar, solange die Maus über dem Widget ist."""

    def initWithFrame_(self, frame):
        self = objc.super(CloseButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.on_click = None
        self.setAccessibilityElement_(True)
        self.setAccessibilityRole_("AXButton")
        self.setAccessibilityLabel_("Widget ausblenden")
        self.setToolTip_("Widget ausblenden")
        return self

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        pass

    def mouseUp_(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        if NSPointInRect(p, self.bounds()) and self.on_click:
            self.on_click()

    def accessibilityPerformPress(self):
        if self.on_click:
            self.on_click()
        return True

    def drawRect_(self, rect):
        b = NSInsetRect(self.bounds(), 0.5, 0.5)
        d = b.size.width
        NSColor.windowBackgroundColor().setFill()
        NSBezierPath.bezierPathWithOvalInRect_(b).fill()
        NSColor.quaternaryLabelColor().setFill()
        NSBezierPath.bezierPathWithOvalInRect_(b).fill()
        NSColor.separatorColor().setStroke()
        NSBezierPath.bezierPathWithOvalInRect_(b).stroke()
        NSColor.labelColor().setStroke()
        cross = NSBezierPath.bezierPath()
        cross.setLineWidth_(1.6)
        cross.setLineCapStyle_(1)  # rund
        x, y, i = b.origin.x, b.origin.y, d * 0.34
        cross.moveToPoint_((x + i, y + i)); cross.lineToPoint_((x + d - i, y + d - i))
        cross.moveToPoint_((x + d - i, y + i)); cross.lineToPoint_((x + i, y + d - i))
        cross.stroke()


class HoverRoot(NSView):
    """Durchsichtige Wurzel des Fensters: blendet den Knopf beim Überfahren ein."""

    def initWithFrame_(self, frame):
        self = objc.super(HoverRoot, self).initWithFrame_(frame)
        if self is None:
            return None
        self.button = None
        self.card = None
        self.addTrackingArea_(NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), TRACK_ENTER_EXIT | TRACK_ALWAYS | TRACK_VISIBLE_RECT, self, None))
        return self

    def mouseEntered_(self, event):
        self._hover(True)

    def mouseExited_(self, event):
        self._hover(False)

    @objc.python_method
    def _hover(self, on: bool) -> None:
        if self.button is not None:
            self.button.setHidden_(not on)
        if self.card is not None:
            self.card.hover = on
            self.card.setNeedsDisplay_(True)


# ------------------------------------------------------------ Fenster
def _mask(radius: float):
    def draw(rect):
        NSColor.blackColor().setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius).fill()
        return True
    img = NSImage.imageWithSize_flipped_drawingHandler_((W, H), False, draw)
    img.setCapInsets_((radius, radius, radius, radius))
    img.setResizingMode_(NSImageResizingModeStretch)
    return img


def _saved_scale() -> float:
    try:
        return min(MAX_SCALE, max(MIN_SCALE, float(prefs.load().get("desk_widget_scale") or 1)))
    except ValueError:
        return 1.0


def _default_origin(scale: float):
    vf = NSScreen.mainScreen().visibleFrame()
    return (vf.origin.x + vf.size.width - W * scale - M - 24, vf.origin.y + vf.size.height - H * scale - M - 24)


def _saved_origin():
    raw = prefs.load().get("desk_widget_origin") or ""
    try:
        x, y = (float(v) for v in raw.split(","))
    except ValueError:
        return None
    for screen in NSScreen.screens():  # nur, wenn der Platz noch auf einem Bildschirm liegt
        f = screen.frame()
        if f.origin.x <= x + W / 2 <= f.origin.x + f.size.width and f.origin.y <= y + H / 2 <= f.origin.y + f.size.height:
            return (x, y)
    return None


class DeskWidget:
    def __init__(self, on_click: Callable[[], None], on_close: Callable[[], None]):
        self.scale = _saved_scale()
        origin = _saved_origin() or _default_origin(self.scale)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(origin[0], origin[1], W + 2 * M, H + 2 * M), BORDERLESS | NONACTIVATING, NSBackingStoreBuffered, False)
        panel.setLevel_(CGWindowLevelForKey(kCGDesktopIconWindowLevelKey) + 1)
        panel.setCollectionBehavior_(JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setHidesOnDeactivate_(False)

        root = HoverRoot.alloc().initWithFrame_(NSMakeRect(0, 0, W + 2 * M, H + 2 * M))
        panel.setContentView_(root)

        fx = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(M, M, W, H))
        fx.setMaterial_(MATERIAL_POPOVER)
        fx.setBlendingMode_(BLEND_BEHIND_WINDOW)
        fx.setState_(STATE_ACTIVE)
        fx.setMaskImage_(_mask(22))
        root.addSubview_(fx)

        self.view = DeskView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        self.view.on_click = on_click
        self.view.on_moved = self.save
        self.view.widget = self
        self.view.setToolTip_("Klicken öffnet die Übersicht, Ziehen verschiebt das Widget")
        fx.addSubview_(self.view)

        # Knopf mittig auf der linken oberen Ecke der Karte (Fensterkoordinaten: unten links = 0,0)
        r = 6  # wie weit der Knopf in die Karte hineinragt (die Ecke ist abgerundet)
        self.close = CloseButton.alloc().initWithFrame_(
            NSMakeRect(M + r - CLOSE_D / 2, M + H - r - CLOSE_D / 2, CLOSE_D, CLOSE_D))
        self.close.on_click = on_close
        self.close.setHidden_(True)
        root.addSubview_(self.close)
        root.button = self.close
        root.card = self.view
        self.root, self.fx, self.panel = root, fx, panel
        self._layout(self.scale, keep_top_right=False)

    def _layout(self, scale: float, keep_top_right: bool = True) -> None:
        """Alles im gleichen Verhältnis skalieren: Die Karte zeichnet weiter in W × H Punkten,
        ihre Bounds bleiben gleich und nur der Rahmen wächst, damit Text scharf bleibt."""
        cw, ch = W * scale, H * scale
        old = self.panel.frame()
        top = old.origin.y + old.size.height
        right = old.origin.x + old.size.width
        x = right - (cw + 2 * M) if keep_top_right else old.origin.x
        y = top - (ch + 2 * M) if keep_top_right else old.origin.y
        self.panel.setFrame_display_(NSMakeRect(x, y, cw + 2 * M, ch + 2 * M), True)
        self.root.setFrame_(NSMakeRect(0, 0, cw + 2 * M, ch + 2 * M))
        self.fx.setFrame_(NSMakeRect(M, M, cw, ch))
        self.fx.setMaskImage_(_mask(22 * scale))
        self.view.setFrame_(NSMakeRect(0, 0, cw, ch))
        self.view.setBoundsSize_((W, H))
        r = 6 * scale
        self.close.setFrameOrigin_((M + r - CLOSE_D / 2, M + ch - r - CLOSE_D / 2))
        self.view.setNeedsDisplay_(True)
        self.scale = scale

    def set_scale(self, scale: float) -> None:
        if abs(scale - self.scale) >= 0.005:
            self._layout(scale)

    def save(self) -> None:
        o = self.panel.frame().origin
        try:
            prefs.set_value("desk_widget_origin", f"{o.x:.0f},{o.y:.0f}")
            prefs.set_value("desk_widget_scale", f"{self.scale:.3f}")
        except Exception:
            log.exception("Widget-Position nicht gespeichert")

    @property
    def visible(self) -> bool:
        return bool(self.panel.isVisible())

    def show(self) -> None:
        self.panel.orderFront_(None)

    def hide(self) -> None:
        self.root._hover(False)
        self.panel.orderOut_(None)

    def update(self, data: "DeskSummary", pause_text: str = "") -> None:
        self.view.show(data, pause_text)
