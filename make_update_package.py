"""Build the optional full-EXE ZIP; ordinary GitHub source ZIPs need no repack."""
import argparse
import ast
from pathlib import Path

from app_updater import build_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    entry = Path(__file__).with_name("paddleocr_pdf_to_md_gui.py")
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    version = next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(name, ast.Name) and name.id == "APP_VERSION" for name in node.targets))
    print(build_package(args.executable, version, args.output or args.executable.parent))


if __name__ == "__main__":
    main()
