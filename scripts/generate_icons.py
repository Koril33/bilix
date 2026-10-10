"""Generate the shared PNG/ICO assets from the maintainer's SVG artwork.

Run in the GUI build environment. QtSvg is only used for asset generation;
the application loads PNGs and does not need an SVG plugin at runtime.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "src" / "djhx_bilix" / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(ASSETS / "bilix.svg"))
    if not renderer.isValid():
        raise RuntimeError("Invalid application SVG")
    entries = []
    payloads = []
    offset = 6 + 16 * len(SIZES)
    for size in (*SIZES, 512):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        if not image.save(str(ASSETS / f"bilix-{size}.png")):
            raise RuntimeError(f"Could not save {size}px PNG")
        if size not in SIZES:
            continue
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Could not encode {size}px icon")
        payload = bytes(data)
        entries.append(
            struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset)
        )
        payloads.append(payload)
        offset += len(payload)
    (ASSETS / "bilix.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(entries)) + b"".join(entries + payloads)
    )
    print(f"Generated PNGs and Windows ICO in {ASSETS}")
    application.quit()


if __name__ == "__main__":
    main()
