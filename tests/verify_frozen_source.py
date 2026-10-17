"""Opt-in integration check: compile Nuitka onefile and override its bundled code.

Run with a Python environment containing Nuitka==2.7.12 and its build dependencies.
This builds a tiny probe, not the production GUI or Windows update installer.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix="paddleocr-frozen-check-") as temporary:
        folder = Path(temporary)
        shutil.copy2(Path(__file__).resolve().parents[1] / "source_bootstrap.py", folder)
        (folder / "probe_feature.py").write_text('VALUE="compiled-old"\n', encoding="utf-8")
        entry = folder / "probe.py"
        entry.write_text('''import sys
import probe_feature
from source_bootstrap import run_installed_source
sys._paddleocr_requirements = []
if not run_installed_source("1.0.0.0"):
    print("BUILTIN:" + probe_feature.VALUE)
''', encoding="utf-8")
        name = "probe.exe" if sys.platform == "win32" else "probe.bin"
        command = [sys.executable, "-m", "nuitka", "--mode=onefile", "--onefile-no-compression",
                   "--assume-yes-for-downloads", "--output-dir=" + str(folder / "build"),
                   "--output-filename=" + name]
        if sys.platform == "win32":
            command.append("--mingw64")
        subprocess.run(command + [str(entry)], check=True)
        executable = folder / "build" / name
        environment = dict(os.environ, LOCALAPPDATA=str(folder / "local"))
        cache = Path(environment["LOCALAPPDATA"]) / "PaddleOCR/updates"
        source = cache / "update-probe/source"
        source.mkdir(parents=True)
        def run():
            return subprocess.run([str(executable)], env=environment, capture_output=True,
                                  text=True, check=True).stdout.strip()
        assert run() == "BUILTIN:compiled-old"
        files = {"paddleocr_pdf_to_md_gui.py": 'import probe_feature\nprint("UPDATED:" + probe_feature.VALUE)\n',
                 "probe_feature.py": 'VALUE="source-new"\n'}
        for filename, value in files.items():
            (source / filename).write_text(value, encoding="utf-8")
        record = {"schema": 1, "application": "PaddleOCR.PDFToMarkdown.GUI", "version": "1.0.0.1",
                  "directory": str(source), "requirements": [],
                  "files": {filename: hashlib.sha256((source / filename).read_bytes()).hexdigest() for filename in files}}
        pointer = cache / "active-source.json"
        pointer.write_text(json.dumps(record), encoding="utf-8")
        assert run() == "UPDATED:source-new"
        (source / "probe_feature.py").write_text('VALUE="tampered"\n', encoding="utf-8")
        assert run() == "BUILTIN:compiled-old"
        assert not pointer.exists()
        print("Native onefile checks passed: built-in code, source override, tamper rejection and fallback.")


if __name__ == "__main__":
    main()
