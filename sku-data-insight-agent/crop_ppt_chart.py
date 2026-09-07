from __future__ import annotations

import os
import sys

from PIL import Image


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: crop_ppt_chart.py <slide-preview.png> <chart-output.png>")
    source_path, output_path = map(os.path.abspath, sys.argv[1:])
    with Image.open(source_path) as image:
        scale_x = image.width / 1280.0
        scale_y = image.height / 720.0
        box = (
            round(88 * scale_x),
            round(104 * scale_y),
            round(1192 * scale_x),
            round(382 * scale_y),
        )
        chart = image.crop(box)
        chart.save(output_path, format="PNG", optimize=True)


if __name__ == "__main__":
    main()
