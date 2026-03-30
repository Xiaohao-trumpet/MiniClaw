"""Screenshot utilities."""

from __future__ import annotations

from pathlib import Path


def take_screenshot(output_path: Path) -> Path:
    """Capture the primary monitor to the specified output path."""
    from mss import mss
    from PIL import Image

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
        img.save(output_path)

    return output_path

