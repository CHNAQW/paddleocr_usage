"""Stable EXE entry point: prefer a verified local source update when present."""
from __future__ import annotations

import sys
import os
from pathlib import Path

from source_bootstrap import requirements, run_installed_source

APP_VERSION = "26.10.19.01"


def main():
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        notice = os.environ.pop("PADDLEOCR_SOURCE_FAILED", "")
        if notice:
            sys._paddleocr_source_error = notice
        sys._paddleocr_launcher = str(Path(sys.argv[0] if "__compiled__" in globals() else sys.executable).resolve())
        sys._paddleocr_requirements = requirements(Path(__file__).with_name("requirements.txt").read_text(encoding="utf-8-sig"))
        if run_installed_source(APP_VERSION):
            return
    from paddleocr_pdf_to_md_gui import main as desktop_main
    desktop_main()


if __name__ == "__main__":
    main()
