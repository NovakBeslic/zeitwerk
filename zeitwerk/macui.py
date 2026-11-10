"""Kleine AppKit-Helfer: SF Symbols, App-Symbole und Farbpunkte als Bilder."""

from __future__ import annotations

import base64
from functools import lru_cache

from AppKit import (
    NSBezierPath, NSBitmapImageRep, NSColor, NSDeviceRGBColorSpace, NSGraphicsContext,
    NSImage, NSMakeRect, NSWorkspace,
)

try:  # macOS 11+
    from AppKit import NSImageSymbolConfiguration
except ImportError:  # pragma: no cover
    NSImageSymbolConfiguration = None

PNG = 4  # NSBitmapImageFileTypePNG


def symbol(name: str, point_size: float = 0, template: bool = True):
    """SF Symbol als NSImage (oder None, wenn es den Namen auf diesem macOS nicht gibt)."""
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        return None
    if point_size and NSImageSymbolConfiguration is not None:
        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(point_size, 0.0)
        img = img.imageWithSymbolConfiguration_(cfg) or img
    img.setTemplate_(template)
    return img


def _png(img, width: float, height: float, scale: int = 2) -> bytes:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, int(width * scale), int(height * scale), 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0)
    rep.setSize_((width, height))
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    img.drawInRect_(NSMakeRect(0, 0, width, height))
    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(PNG, {}))


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


@lru_cache(maxsize=64)
def symbol_data_uri(name: str) -> str | None:
    """Schwarzes SF Symbol als PNG. Die Oberfläche nutzt es als Maske und färbt es selbst."""
    img = symbol(name, point_size=32)
    if img is None:
        return None
    w, h = img.size().width, img.size().height
    return data_uri(_png(img, w, h))


@lru_cache(maxsize=256)
def app_icon_data_uri(bundle_id: str) -> str | None:
    url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(bundle_id)
    if url is None:
        return None
    icon = NSWorkspace.sharedWorkspace().iconForFile_(url.path())
    return data_uri(_png(icon, 32, 32))


@lru_cache(maxsize=8)
def dot(color_name: str, size: float = 9):
    """Runder Farbpunkt (z. B. 'systemBlueColor') für Menüeinträge, passt sich Hell/Dunkel an."""
    color = getattr(NSColor, color_name, NSColor.systemTealColor)()  # Cyan erst ab macOS 12

    def draw(rect):
        color.setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(1, 1, size - 2, size - 2)).fill()
        return True

    return NSImage.imageWithSize_flipped_drawingHandler_((size, size), False, draw)


LEVEL_COLORS = {
    "p2": "systemBlueColor", "p1": "systemCyanColor", "n": "systemGrayColor",
    "m1": "systemOrangeColor", "m2": "systemRedColor",
}
