#!/usr/bin/env python3
"""Generate platform icon files (PNG, ICO, ICNS) from icon.svg.

Run before PyInstaller to ensure icon files exist:

    QT_QPA_PLATFORM=offscreen uv run python scripts/create_icons.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

# Must be set before Qt import so rendering works on headless CI runners.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RESOURCES = Path(__file__).resolve().parent.parent / "mailsweep" / "resources"
SVG_PATH = RESOURCES / "icon.svg"


def _app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _render_png(size: int) -> bytes:
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    _app()
    renderer = QSvgRenderer(str(SVG_PATH))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()

    buf = QByteArray()
    buf_io = QBuffer(buf)
    buf_io.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf_io, "PNG")
    buf_io.close()
    return bytes(buf)


def create_png(path: Path, size: int = 256) -> None:
    path.write_bytes(_render_png(size))
    print(f"  {path}")


def create_ico(path: Path) -> None:
    """Build a multi-resolution .ico (16, 32, 48, 256 px) from the SVG."""
    sizes = [16, 32, 48, 256]
    images = [_render_png(s) for s in sizes]

    header_size = 6 + 16 * len(sizes)
    offsets: list[int] = []
    off = header_size
    for data in images:
        offsets.append(off)
        off += len(data)

    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(sizes)))
        for size, data, offset in zip(sizes, images, offsets):
            w = size if size < 256 else 0  # ICO uses 0 to mean 256
            h = size if size < 256 else 0
            f.write(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset))
        for data in images:
            f.write(data)
    print(f"  {path}")


def create_icns(path: Path) -> None:
    """Build a .icns using macOS iconutil (macOS only)."""
    import shutil
    import subprocess
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    iconset = tmp / "MailSweep.iconset"
    iconset.mkdir()

    for size in [16, 32, 64, 128, 256, 512]:
        (iconset / f"icon_{size}x{size}.png").write_bytes(_render_png(size))
        (iconset / f"icon_{size}x{size}@2x.png").write_bytes(_render_png(size * 2))

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(path)],
        check=True,
    )
    shutil.rmtree(tmp)
    print(f"  {path}")


if __name__ == "__main__":
    if not SVG_PATH.exists():
        print(f"ERROR: {SVG_PATH} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Generating icons from {SVG_PATH}")
    create_png(RESOURCES / "icon.png")
    create_ico(RESOURCES / "icon.ico")
    if sys.platform == "darwin":
        create_icns(RESOURCES / "icon.icns")
    print("Done.")
