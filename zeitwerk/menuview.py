"""Kopf des Menüleisten-Menüs: Tagesübersicht mit Balken, wie die Regler im Ton-Menü.

Gezeichnet mit dynamischen Systemfarben, damit Hell/Dunkel automatisch stimmt.
"""

from __future__ import annotations

import objc
from AppKit import (
    NSAttributedString, NSBezierPath, NSColor, NSFont, NSFontAttributeName,
    NSForegroundColorAttributeName, NSMakeRect, NSView,
)

from .analysis import fmt_duration

PAD = 14
GAP = 2


def _text(s: str, size: float, color, bold: bool = False):
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    return NSAttributedString.alloc().initWithString_attributes_(
        s, {NSFontAttributeName: font, NSForegroundColorAttributeName: color})


class HeaderView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(HeaderView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.day = None
        self.pause = ""
        self.setAccessibilityElement_(True)
        self.setAccessibilityRole_("AXStaticText")
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def show_day(self, day, pause_text: str = "") -> None:
        self.day, self.pause = day, pause_text
        if day is None or day.empty:
            label = "Heute noch keine Daten"
        else:
            label = (f"Heute {fmt_duration(day.total)} erfasst, {fmt_duration(day.productive)} produktiv, "
                     f"{fmt_duration(day.distracting)} ablenkend, Produktivitätswert {day.score:.0f}")
        self.setAccessibilityLabel_(f"{pause_text}. {label}" if pause_text else label)
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        w = self.bounds().size.width
        day = self.day
        empty = day is None or day.empty

        # Zeile 1: "Heute" links, Wert rechts
        _text("Heute", 13, NSColor.labelColor(), bold=True).drawAtPoint_((PAD, 6))
        if not empty and day.score is not None:
            value = _text(f"{day.score:.0f}", 13, NSColor.labelColor(), bold=True)
            unit = _text(" / 100", 11, NSColor.secondaryLabelColor())
            vw, uw = value.size().width, unit.size().width
            value.drawAtPoint_((w - PAD - uw - vw, 6))
            unit.drawAtPoint_((w - PAD - uw, 8))

        # Zeile 2: Verteilung als Balken (produktiv, neutral, ablenkend), 2 pt Abstand zwischen Teilen
        bar = NSMakeRect(PAD, 28, w - 2 * PAD, 6)
        NSColor.quaternaryLabelColor().setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bar, 3, 3).fill()
        if not empty and day.total > 0:
            parts = [(day.productive, NSColor.systemBlueColor()),
                     (max(0.0, day.total - day.productive - day.distracting), NSColor.systemGrayColor()),
                     (day.distracting, NSColor.systemRedColor())]
            parts = [(v, c) for v, c in parts if v > 0]
            usable = bar.size.width - GAP * (len(parts) - 1)
            x = bar.origin.x
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bar, 3, 3).addClip()
            for v, color in parts:
                seg = max(2.0, usable * v / day.total)
                color.setFill()
                NSBezierPath.fillRect_(NSMakeRect(x, bar.origin.y, seg, bar.size.height))
                x += seg + GAP

        # Zeile 3: Klartext, damit die Farbe nie allein die Information trägt
        if self.pause:
            line = _text(self.pause, 11, NSColor.systemOrangeColor())
        elif empty:
            line = _text("Noch keine Daten. Zeitwerk zeichnet automatisch auf.", 11, NSColor.secondaryLabelColor())
        else:
            line = _text(f"{fmt_duration(day.productive)} produktiv, {fmt_duration(day.distracting)} ablenkend",
                         11, NSColor.secondaryLabelColor())
        line.drawAtPoint_((PAD, 42))
