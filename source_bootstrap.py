"""Small frozen launcher contract. Source updates cannot replace this module."""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import json
import os
import re
import runpy
import subprocess
import sys
import uuid
from pathlib import Path

APPLICATION_ID = "PaddleOCR.PDFToMarkdown.GUI"
PROTECTED_MODULES = {"app_launcher", "source_bootstrap"}


def cache_root():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))) / "PaddleOCR" / "updates"


def requirements(text):
    return sorted(line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))


class SourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, directory):
        self.directory = directory

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in PROTECTED_MODULES:
            return None
        parts = fullname.split(".")
        base = self.directory.joinpath(*parts)
        if base.with_suffix(".py").is_file():
            return importlib.util.spec_from_file_location(fullname, base.with_suffix(".py"))
        if (base / "__init__.py").is_file():
            return importlib.util.spec_from_file_location(fullname, base / "__init__.py",
                                                        submodule_search_locations=[str(base)])
        return None


def validated_source(record, cache):
    if (not isinstance(record, dict) or record.get("application") != APPLICATION_ID
            or type(record.get("schema")) is not int or record.get("schema") != 1):
        raise ValueError("Unsupported source installation")
    if not re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,5}){3}", str(record.get("version", ""))):
        raise ValueError("Invalid source version")
    directory = Path(record["directory"]).resolve()
    directory.relative_to(cache.resolve())
    files = record.get("files", {})
    if not isinstance(files, dict) or "paddleocr_pdf_to_md_gui.py" not in files:
        raise ValueError("Missing source files")
    for name, digest in files.items():
        path = (directory / name).resolve()
        path.relative_to(directory)
        if not isinstance(digest, str) or path.stat().st_size > 512 * 1024 * 1024:
            raise ValueError("Source file changed")
        checksum = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                checksum.update(block)
        if checksum.hexdigest() != digest:
            raise ValueError("Source file changed")
    return directory


def run_installed_source(builtin_version):
    """Run updated Python through the bundled interpreter before app imports.

    Our finder precedes Nuitka's compiled-module finder, so updated application
    modules replace their bundled counterparts; bundled dependencies remain usable.
    """
    cache = cache_root()
    pointer = cache / "active-source.json"
    if not pointer.is_file():
        return False
    finder, previous = None, dict(sys.modules)
    previous_environment, previous_cwd = dict(os.environ), os.getcwd()
    try:
        if pointer.stat().st_size > 256 * 1024:
            raise ValueError("Source installation record is too large")
        record = json.loads(pointer.read_text(encoding="utf-8-sig"))
        if tuple(map(int, record["version"].split("."))) <= tuple(map(int, builtin_version.split("."))):
            return False
        if record.get("requirements") != getattr(sys, "_paddleocr_requirements", record.get("requirements")):
            raise ValueError("Installed source dependencies differ from the bundled runtime")
        directory = validated_source(record, cache)
        finder = SourceFinder(directory)
        sys.meta_path.insert(0, finder)
        for name, module in list(sys.modules.items()):
            if name not in PROTECTED_MODULES and getattr(module, "__file__", None):
                candidate = directory.joinpath(*name.split("."))
                if candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file():
                    del sys.modules[name]
        runpy.run_path(str(directory / "paddleocr_pdf_to_md_gui.py"), run_name="__main__")
        return True
    except Exception as exc:
        if os.environ.get("PADDLEOCR_UPDATE_HEALTH"):
            raise  # Installer owns the transaction and will restore its snapshot.
        # Keep the failing installation for diagnosis, and use the built-in app.
        try:
            pointer.replace(cache / ("failed-source-" + uuid.uuid4().hex + ".json"))
        except OSError:
            pass
        sys._paddleocr_source_error = type(exc).__name__
        launcher = getattr(sys, "_paddleocr_launcher", None)
        if finder is not None and launcher and sys.platform == "win32":
            # A partially initialized GUI may have changed process state. Restart
            # the built-in app in a clean process after disabling this source.
            environment = {key: value for key, value in previous_environment.items() if not key.upper().startswith("NUITKA_ONEFILE_")}
            environment["PADDLEOCR_SOURCE_FAILED"] = type(exc).__name__
            try:
                subprocess.Popen([launcher], env=environment, cwd=previous_cwd, close_fds=True)
                return True
            except OSError:
                pass
        return False
    finally:
        if finder is not None:
            sys.meta_path.remove(finder)
            for name in list(sys.modules):
                module = sys.modules[name]
                path = getattr(module, "__file__", "") or ""
                if name not in previous and str(cache) in str(path):
                    del sys.modules[name]
            for name, module in previous.items():
                sys.modules[name] = module
