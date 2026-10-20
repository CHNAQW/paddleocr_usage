"""Conservative, bounded maintenance of files owned by the desktop updater.

An installation owns its staging directory, never the ZIP selected by the user.
Running sources and the immediate rollback source remain intact. Unknown files,
links and live transactions are left alone.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import sys
import threading
import time
from pathlib import Path

APPLICATION_ID = "PaddleOCR.PDFToMarkdown.GUI"
OWNER = ".update-owner.json"
MAX_JSON = 256 * 1024
MAX_LOG = 64 * 1024
STALE_SECONDS = 24 * 60 * 60
_maintenance_lock = threading.Lock()


def _plain(path):
    """Reject symbolic links and Windows junctions, including parent paths."""
    try:
        for item in (path, *path.parents):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return False
        return True
    except OSError:
        return False


def _read(path):
    try:
        if not _plain(path) or path.stat().st_size > MAX_JSON:
            return None
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _write(path, value):
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def mark_owned(directory, kind):
    _write(Path(directory) / OWNER, {
        "application": APPLICATION_ID, "schema": 1, "kind": kind,
        "pid": os.getpid(), "created": time.time(),
    })


def _alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() != 87  # Access denied is not proof of death.
            try:
                code = wintypes.DWORD()
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
            finally:
                kernel.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


@contextlib.contextmanager
def _installation_idle():
    """Use the install helper's mutex without waiting or stealing ownership."""
    if sys.platform != "win32":
        yield True
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateMutexW(None, False, "Local\\PaddleOCRLocalUpdate")
    owned = bool(handle) and kernel.WaitForSingleObject(handle, 0) in (0, 0x80)
    try:
        yield owned
    finally:
        if owned:
            kernel.ReleaseMutex(handle)
        if handle:
            kernel.CloseHandle(handle)


def _stage(cache, source):
    try:
        path = Path(source)
        if (path.parent.parent == cache and path.name == "source"
                and path.parent.name.startswith("update-") and _plain(path)):
            return path.parent
    except (TypeError, ValueError):
        pass
    return None


def _record_stage(cache, record):
    if (isinstance(record, dict) and record.get("application") == APPLICATION_ID
            and record.get("schema") == 1 and isinstance(record.get("files"), dict)
            and "paddleocr_pdf_to_md_gui.py" in record["files"]):
        return _stage(cache, record.get("directory"))
    return None


def _plan(directory, cache):
    plan = _read(directory / "install.json")
    if not plan:
        return None
    try:
        target, backup, payload = (Path(plan[key]) for key in ("target", "backup", "payload"))
        match = re.fullmatch(re.escape(target.stem) + r"\.before-update-([0-9a-f]{12})\.exe", backup.name)
        if (target.suffix.lower() != ".exe" or backup.parent != target.parent or not match
                or Path(plan["log"]) != directory / "install.log"
                or Path(plan["health"]) != directory / "ready"
                or Path(plan["active"]) != cache / "active-source.json"
                or Path(plan["source_backup"]) != directory / ("previous-source-" + match[1] + ".json")
                or (plan.get("kind") == "source" and payload != directory)
                or (plan.get("kind") == "exe" and payload.parent != directory)
                or plan.get("kind") not in {"source", "exe"}):
            return None
        return plan
    except (KeyError, TypeError, ValueError):
        return None


def _runtime_leases(directory):
    live = False
    entries = list(directory.glob(".running-*.json"))
    if len(entries) > 256:
        return True
    for entry in entries:
        record = _read(entry)
        if not record or record.get("application") != APPLICATION_ID:
            live = True  # An unreadable lease must not authorize deletion.
        elif _alive(record.get("pid")):
            live = True
        else:
            entry.unlink(missing_ok=True)
    return live


def _remove(path):
    """No traversal through links; refusal only leaves redundant cache files."""
    if not _plain(path):
        return False
    try:
        if path.is_dir():
            count = 0
            for root, directories, files in os.walk(path, followlinks=False):
                for name in directories + files:
                    count += 1
                    if count > 10000 or not _plain(Path(root) / name):
                        return False
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError:
        return False


def _trim_log(path):
    try:
        if not _plain(path) or path.stat().st_size <= MAX_LOG:
            return
        with path.open("rb") as handle:
            handle.seek(-MAX_LOG, os.SEEK_END)
            tail = handle.read(MAX_LOG)
        path.write_bytes(tail)
    except OSError:
        pass


def _clean_failed_records(cache):
    records = []
    for path in cache.glob("failed-source-*.json"):
        if not re.fullmatch(r"failed-source-[0-9a-f]{32}\.json", path.name):
            continue
        record = _read(path)
        try:
            source = Path(record["directory"])
            if (record.get("application") != APPLICATION_ID or record.get("schema") != 1
                    or source.name != "source" or source.parent.parent != cache
                    or not source.parent.name.startswith("update-")
                    or not isinstance(record.get("files"), dict)
                    or "paddleocr_pdf_to_md_gui.py" not in record["files"]):
                continue
            records.append(path)
        except (KeyError, TypeError, ValueError):
            continue
        if len(records) >= 1000:
            break
    records.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(path) for path in records[3:] if _remove(path)]


def cleanup_updates(cache, running_source=None, current_exe=None, now=None):
    """Return removed paths; preserve current/rollback data and three small logs."""
    cache = Path(cache).absolute()
    if not _plain(cache) or not _maintenance_lock.acquire(blocking=False):
        return []
    removed = []
    try:
        with _installation_idle() as idle:
            if not idle:
                return removed
            now = time.time() if now is None else now
            active_record = _read(cache / "active-source.json")
            active = _record_stage(cache, active_record)
            if (cache / "active-source.json").exists() and not active:
                return removed  # Corrupt activation metadata cannot authorize cleanup.
            protected = {path for path in (active, _stage(cache, running_source)) if path}
            if active:
                plan = _plan(active, cache)
                if plan:
                    previous = _record_stage(cache, _read(Path(plan["source_backup"])))
                    if previous:
                        protected.add(previous)
            entries = []
            for directory in list(cache.iterdir())[:2000]:
                if not directory.is_dir() or not _plain(directory):
                    continue
                owner, plan = _read(directory / OWNER), _plan(directory, cache)
                owned = (owner and owner.get("application") == APPLICATION_ID
                         and owner.get("schema") == 1)
                if not (owned or plan):
                    continue
                if not directory.name.startswith(("update-", "download-")):
                    continue
                age = now - directory.stat().st_mtime
                leases = _runtime_leases(directory)
                if plan and not owned and (directory / "source").is_dir():
                    # Releases before ownership/leases existed may still run in
                    # another process. Reclaim their ZIPs, never guess that their
                    # source is unused. A future run registers explicit ownership.
                    protected.add(directory)
                # A staged package can still be selected in a different window.
                if directory not in protected and (leases or
                        (owned and _alive(owner.get("pid"))) or
                        (plan and _alive(plan.get("pid")))):
                    continue
                successful = False
                if plan:
                    try:
                        ready = directory / "ready"
                        successful = (_plain(ready) and ready.stat().st_size < 256
                                      and ready.read_text(encoding="utf-8-sig").strip() == plan["version"])
                    except (OSError, KeyError, UnicodeError):
                        pass
                if directory not in protected and not successful and age < STALE_SECONDS:
                    continue
                entries.append((directory, plan, successful))
            # Keep the newest three transactions' small diagnostics. Their payloads
            # are handled independently, so a failed 500 MB download is not retained.
            diagnostics = {d for d, p, _ in sorted(entries, key=lambda e: (e[0] / "install.json").stat().st_mtime
                           if e[1] else 0, reverse=True)[:3] if p}
            result = _read(cache / "last-update.json")
            if result and isinstance(result.get("log"), str):
                last_log = Path(result["log"])
                if last_log.parent.parent == cache and last_log.name == "install.log":
                    diagnostics.add(last_log.parent)
            diagnostics.update(protected)
            backups = []
            for directory, plan, successful in entries:
                if (plan and successful and plan["kind"] == "exe" and current_exe
                        and Path(plan["target"]) == Path(current_exe).absolute()):
                    backup = Path(plan["backup"])
                    if _plain(backup) and backup.is_file():
                        backups.append((backup, (directory / "install.json").stat().st_mtime))
            for backup, _ in sorted(backups, key=lambda item: item[1], reverse=True)[1:]:
                if _remove(backup):
                    removed.append(str(backup))
            # An external EXE backup must retain its ownership record even after
            # many intervening source updates; otherwise a later EXE update
            # could never prove that it is safe to retire that backup.
            for directory, plan, _ in entries:
                if plan and plan["kind"] == "exe":
                    backup = Path(plan["backup"])
                    if _plain(backup) and backup.is_file():
                        diagnostics.add(directory)
            for directory, plan, _ in entries:
                if directory not in protected and directory not in diagnostics:
                    if _remove(directory):
                        removed.append(str(directory))
                    continue
                keep = {"install.json", OWNER, "ready"}
                if directory in protected:
                    keep.add("source")
                    if plan:
                        keep.add(Path(plan["source_backup"]).name)
                logs = sorted((p for p in directory.glob("*.log") if _plain(p)),
                              key=lambda p: p.stat().st_mtime, reverse=True)
                keep_logs = {directory / "install.log", *logs[:2]}
                for child in list(directory.iterdir())[:1000]:
                    if child.name in keep or child.name.startswith(".running-"):
                        continue
                    if child in keep_logs and directory in diagnostics:
                        _trim_log(child)
                    elif _remove(child):
                        removed.append(str(child))
            removed.extend(_clean_failed_records(cache))
            return removed
    except (OSError, ValueError, TypeError):
        return removed
    finally:
        _maintenance_lock.release()


def start_maintenance(cache, version, marker=None, running_source=None, current_exe=None):
    """Wait for confirmed helper success on a daemon, then reclaim old artifacts."""
    cache = Path(cache).absolute()
    stage = _stage(cache, running_source)
    if stage:
        try:
            mark_owned(stage, "installed-source")
            _write(stage / (".running-" + str(os.getpid()) + ".json"),
                   {"application": APPLICATION_ID, "pid": os.getpid()})
        except OSError:
            pass

    def maintain():
        if marker:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                result = _read(cache / "last-update.json")
                if (result and result.get("version") == version
                        and result.get("log") == str(Path(marker).parent / "install.log")):
                    if result.get("status") != "installed":
                        return
                    # The result is written just before the helper releases its
                    # mutex. Retrying an idle check is safe; stealing it is not.
                    for _ in range(20):
                        with _installation_idle() as idle:
                            if idle:
                                break
                        time.sleep(.25)
                    break
                time.sleep(.25)
            else:
                return
        cleanup_updates(cache, running_source, current_exe)

    threading.Thread(target=maintain, name="update-cache-maintenance", daemon=True).start()
