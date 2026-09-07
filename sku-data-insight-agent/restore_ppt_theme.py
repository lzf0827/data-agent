from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile


def is_theme_part(name: str) -> bool:
    return name.startswith("ppt/theme/theme") and name.endswith(".xml")


def copy_entry(source: zipfile.ZipFile, target: zipfile.ZipFile, info: zipfile.ZipInfo) -> None:
    target.writestr(info, source.read(info.filename))


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: restore_ppt_theme.py <reference.pptx> <generated.pptx>")
    reference_path, generated_path = map(os.path.abspath, sys.argv[1:])
    output_dir = os.path.dirname(generated_path)
    with tempfile.TemporaryDirectory(dir=output_dir) as work_dir:
        reference_copy = os.path.join(work_dir, "reference.pptx")
        rebuilt_path = os.path.join(work_dir, "rebuilt.pptx")
        shutil.copy2(reference_path, reference_copy)
        with zipfile.ZipFile(reference_copy, "r") as reference_zip, zipfile.ZipFile(generated_path, "r") as generated_zip, zipfile.ZipFile(rebuilt_path, "w") as rebuilt_zip:
            theme_infos = [info for info in reference_zip.infolist() if is_theme_part(info.filename)]
            if not theme_infos:
                raise RuntimeError("Reference presentation has no theme parts")
            for info in generated_zip.infolist():
                if not is_theme_part(info.filename):
                    copy_entry(generated_zip, rebuilt_zip, info)
            for info in theme_infos:
                copy_entry(reference_zip, rebuilt_zip, info)
        os.replace(rebuilt_path, generated_path)


if __name__ == "__main__":
    main()
