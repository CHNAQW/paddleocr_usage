"""Validated local/GitHub update packages and the Windows installation hand-off."""
from __future__ import annotations

import hashlib
import ast
import base64
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ui_translations import tr
from source_bootstrap import requirements, validated_source
from task_runtime import cancellable_call
from update_cleanup import mark_owned, start_maintenance

APPLICATION_ID = "PaddleOCR.PDFToMarkdown.GUI"
PLATFORM = "windows-x86_64"
MAX_PAYLOAD = 512 * 1024 * 1024
MAX_MANIFEST = 16 * 1024
BLOCK_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT = 15 * 60
METADATA_TIMEOUT = 60


class UpdateCancelled(RuntimeError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,5}){3}", value):
        raise ValueError(tr("更新包版本号须包含四段数字。"))
    result = tuple(int(part) for part in value.split("."))
    if any(part > 65535 for part in result):
        raise ValueError(tr("更新包版本号超出 Windows 支持范围。"))
    return result


def update_cache():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")))
    return base / "PaddleOCR" / "updates"


def running_executable(compiled=False):
    if sys.platform != "win32":
        return None
    # Nuitka onefile: argv[0] points to the original EXE, not its extracted child.
    launcher = getattr(sys, "_paddleocr_launcher", None)
    if launcher:
        path = Path(launcher).resolve()
    elif compiled:
        path = Path(sys.argv[0]).resolve()
    elif getattr(sys, "frozen", False):
        path = Path(sys.executable).resolve()
    else:
        return None
    return path if path.suffix.lower() == ".exe" and path.is_file() else None


@dataclass(frozen=True)
class UpdatePackage:
    version: str
    filename: str
    sha256: str
    size: int
    directory: Path
    source: Path

    @property
    def payload(self):
        return self.directory / self.filename


@dataclass(frozen=True)
class SourcePackage:
    version: str
    filename: str
    sha256: str
    size: int
    directory: Path
    source: Path
    record: dict


def _cancel(stop):
    if stop():
        raise UpdateCancelled(tr("已取消读取更新包。"))


def _read_manifest(data, current_version):
    try:
        manifest = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(tr("无法读取更新清单，请使用重新生成的更新包。")) from exc
    if (not isinstance(manifest, dict) or type(manifest.get("schema")) is not int
            or manifest.get("schema") != 1 or manifest.get("application") != APPLICATION_ID
            or manifest.get("platform") != PLATFORM):
        raise ValueError(tr("更新包不适用于本软件的 Windows 64 位版本。"))
    version = manifest.get("version")
    if version_tuple(version) <= version_tuple(current_version):
        raise ValueError(tr("更新包版本 {arg0} 不高于当前版本 {arg1}。", arg0=version, arg1=current_version))
    filename = "PaddleOCR_PDF_to_MD_" + version + ".exe"
    if manifest.get("filename") != filename:
        raise ValueError(tr("更新清单中的程序文件名不正确。"))
    digest, size = manifest.get("sha256"), manifest.get("size")
    if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
            or type(size) is not int or not 256 <= size <= MAX_PAYLOAD):
        raise ValueError(tr("更新清单缺少有效的 SHA-256 或文件大小。"))
    return version, filename, digest.lower(), size


def verify_payload(path, digest, size, stop=lambda: False):
    """Check integrity and a basic AMD64 executable header, never execute it."""
    _cancel(stop)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise ValueError(tr("更新程序大小不符或文件已改变，请重新导入更新包。"))
    with path.open("rb") as handle:
        header = handle.read(64)
        offset = int.from_bytes(header[60:64], "little")
        if header[:2] != b"MZ" or not 64 <= offset <= min(size - 26, BLOCK_SIZE):
            raise ValueError(tr("更新包内不是有效的 Windows 64 位程序。"))
        handle.seek(offset)
        pe = handle.read(26)
        if (pe[:4] != b"PE\0\0" or int.from_bytes(pe[4:6], "little") != 0x8664
                or not int.from_bytes(pe[22:24], "little") & 2
                or int.from_bytes(pe[22:24], "little") & 0x2000
                or pe[24:26] != b"\x0b\x02"):
            raise ValueError(tr("更新包内不是有效的 Windows 64 位程序。"))
        handle.seek(0)
        checksum = hashlib.sha256()
        for block in iter(lambda: handle.read(BLOCK_SIZE), b""):
            _cancel(stop)
            checksum.update(block)
    if checksum.hexdigest() != digest:
        raise ValueError(tr("更新程序 SHA-256 不符，请重新获取更新包。"))


def discard_package(package):
    # This directory is created exclusively for one import, never the source ZIP.
    shutil.rmtree(package.directory, ignore_errors=True)


def import_package(source, current_version, cache=None, stop=lambda: False, progress=lambda done, total: None):
    """Extract only declared files into a fresh cache directory, with size limits."""
    source = Path(source).resolve()
    cache = Path(cache) if cache is not None else update_cache()
    directory = None
    try:
        _cancel(stop)
        with zipfile.ZipFile(source) as archive:
            items = archive.infolist()
            names = [item.filename for item in items]
            if "update.json" not in names:
                return import_source(archive, source, current_version, cache, stop, progress)
            if len(items) not in {2, 3} or len({name.casefold() for name in names}) != len(names):
                raise ValueError(tr("更新包包含重复文件或多余内容。"))
            for item in items:
                mode = stat.S_IFMT(item.external_attr >> 16)
                if (item.flag_bits & 1 or mode not in {0, stat.S_IFREG}
                        or "/" in item.filename or "\\" in item.filename):
                    raise ValueError(tr("更新包包含不支持的路径、加密文件或链接。"))
            info = archive.getinfo("update.json")
            if info.file_size > MAX_MANIFEST:
                raise ValueError(tr("更新清单过大。"))
            version, filename, digest, size = _read_manifest(archive.read(info), current_version)
            if not set(names) <= {"update.json", filename, filename + ".sha256.txt"} or filename not in names:
                raise ValueError(tr("更新包中的文件与清单不一致。"))
            payload_info = archive.getinfo(filename)
            if payload_info.file_size != size:
                raise ValueError(tr("更新程序大小与清单不一致。"))
            checksum_name = filename + ".sha256.txt"
            if checksum_name in names:
                checksum_info = archive.getinfo(checksum_name)
                if checksum_info.file_size > MAX_MANIFEST:
                    raise ValueError(tr("更新清单过大。"))
                checksum = archive.read(checksum_info).decode("ascii").split()
                if checksum != [digest, filename]:
                    raise ValueError(tr("校验文件与更新清单不一致。"))
            cache.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="update-", dir=cache))
            mark_owned(directory, "package")
            payload = directory / filename
            written = 0
            with archive.open(payload_info) as incoming, payload.open("xb") as outgoing:
                while True:
                    _cancel(stop)
                    block = incoming.read(BLOCK_SIZE)
                    if not block:
                        break
                    written += len(block)
                    if written > size:
                        raise ValueError(tr("更新程序大小与清单不一致。"))
                    outgoing.write(block)
                    progress(written, size)
            verify_payload(payload, digest, size, stop)
            return UpdatePackage(version, filename, digest, size, directory, source)
    except (zipfile.BadZipFile, UnicodeError, KeyError) as exc:
        raise ValueError(tr("更新 ZIP 已损坏或内容不完整，请重新获取。")) from exc
    finally:
        if directory is not None and sys.exc_info()[0] is not None:
            shutil.rmtree(directory, ignore_errors=True)


def build_package(executable, version, output):
    """Publisher-side helper: bundle the compiled EXE, manifest and checksum."""
    version_tuple(version)
    executable, output = Path(executable).resolve(), Path(output).resolve()
    size = executable.stat().st_size
    if not 256 <= size <= MAX_PAYLOAD:
        raise ValueError(tr("更新程序大小超出支持范围。"))
    checksum = hashlib.sha256()
    with executable.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_SIZE), b""):
            checksum.update(block)
    digest = checksum.hexdigest()
    verify_payload(executable, digest, size)
    filename = "PaddleOCR_PDF_to_MD_" + version + ".exe"
    manifest = {"schema": 1, "application": APPLICATION_ID, "platform": PLATFORM,
                "version": version, "filename": filename, "sha256": digest, "size": size}
    output.mkdir(parents=True, exist_ok=True)
    target = output / ("PaddleOCR_Update_" + version + ".zip")
    temporary = output / (target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("update.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.write(executable, filename)
            archive.writestr(filename + ".sha256.txt", digest + "  " + filename + "\n")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def launch_install(package, current_exe, current_version, cache=None):
    if sys.platform != "win32":
        raise RuntimeError(tr("自动安装仅支持 Windows EXE；源码运行可检查更新包。"))
    current_exe = Path(current_exe).resolve()
    if current_exe.suffix.lower() != ".exe" or not current_exe.is_file() or current_exe.is_symlink():
        raise ValueError(tr("无法定位正在运行的 EXE，请使用完整的 Windows 程序。"))
    if version_tuple(package.version) <= version_tuple(current_version):
        raise ValueError(tr("更新包版本 {arg0} 不高于当前版本 {arg1}。", arg0=package.version, arg1=current_version))
    source_update = isinstance(package, SourcePackage)
    if source_update:
        validated_source(package.record, Path(cache) if cache is not None else update_cache())
    else:
        verify_payload(package.payload, package.sha256, package.size)
    if not source_update and getattr(current_exe.stat(), "st_file_attributes", 0) & 1:
        raise PermissionError(tr("程序文件或所在目录不可写，请将 EXE 移到可写文件夹后重试。"))
    stamp = uuid.uuid4().hex[:12]
    probe = (package.directory if source_update else current_exe.parent) / (".paddleocr-update-" + stamp + ".tmp")
    try:
        with probe.open("xb"):
            pass
    except OSError as exc:
        raise PermissionError(tr("程序文件或所在目录不可写，请将 EXE 移到可写文件夹后重试。")) from exc
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
    helper = Path(__file__).resolve().with_name("update_helper.ps1")
    script = helper.read_text(encoding="utf-8-sig")
    cache = Path(cache) if cache is not None else update_cache()
    cache.mkdir(parents=True, exist_ok=True)
    plan = {"pid": os.getpid(), "target": str(current_exe), "payload": str(package.directory if source_update else package.payload),
            "backup": str(current_exe.with_name(current_exe.stem + ".before-update-" + stamp + ".exe")),
            "ready": str(current_exe.parent / (".paddleocr-update-" + stamp + ".exe")),
            "health": str(package.directory / "ready"), "result": str(cache / "last-update.json"),
            "log": str(package.directory / "install.log"), "version": package.version,
            "previous_version": current_version, "sha256": package.sha256, "size": package.size,
            "health_timeout": 120, "cwd": str(Path.cwd()),
            "handshake": str(package.directory / ("helper-ready-" + stamp)),
            "helper_output": str(package.directory / ("helper-output-" + stamp + ".log"))}
    plan.update(kind="source" if source_update else "exe", active=str(cache / "active-source.json"),
                source_record=package.record if source_update else None,
                source_backup=str(package.directory / ("previous-source-" + stamp + ".json")))
    plan_path = package.directory / "install.json"
    with plan_path.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False)
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("NUITKA_ONEFILE_")}
    environment["PADDLEOCR_UPDATE_PLAN"] = str(plan_path)
    # Paths and package data are passed as JSON, never interpolated into shell code.
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    log_path = Path(plan["log"])
    output_path = Path(plan["helper_output"])
    with log_path.open("a", encoding="utf-8") as log:
        log.write("Starting Windows update helper.\nProcess output: " + str(output_path) + "\n")
    # PowerShell does not share the C runtime's command-line quoting rules.
    # Encode the entire Unicode script instead of passing multiline -Command
    # text through list2cmdline. No user path is interpolated into the script.
    command = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        with output_path.open("xb") as output:
            process = subprocess.Popen([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", "-EncodedCommand", command],
                             env=environment, stdin=subprocess.DEVNULL, stdout=output,
                             stderr=subprocess.STDOUT, close_fds=True, creationflags=0x08000000)
            deadline = time.monotonic() + 15
            while not Path(plan["handshake"]).is_file():
                code = process.poll()
                if code is not None or time.monotonic() >= deadline:
                    if code is None:
                        process.terminate()
                    raise RuntimeError("PowerShell exit code: " + str(code) if code is not None else "PowerShell startup timed out (15 seconds).")
                time.sleep(.05)
    except (OSError, RuntimeError) as exc:
        plan_path.unlink(missing_ok=True)
        diagnostic = str(exc)
        try:
            # Bound the displayed tail; the full process output remains on disk.
            with output_path.open("rb") as output:
                output.seek(max(0, output_path.stat().st_size - 4096))
                diagnostic += "\n" + output.read().decode("utf-8", errors="replace").strip()
        except OSError:
            pass
        with log_path.open("a", encoding="utf-8") as log:
            log.write(diagnostic + "\nProcess output: " + str(output_path) + "\n")
        raise RuntimeError(tr("更新助手未能启动，当前程序保持运行。日志：{arg0}\n详情：{arg1}",
                              arg0=log_path, arg1=diagnostic.strip())) from exc
    return plan


def import_source(archive, source, current_version, cache, stop, progress):
    """Accept GitHub's ordinary source ZIP, including its single enclosing folder."""
    entries = archive.infolist()
    if len(entries) > 5000:
        raise ValueError(tr("源码包文件过多。"))
    roots = []
    for info in entries:
        parts = info.filename.split("/")
        if parts[-1] == "paddleocr_pdf_to_md_gui.py" and len(parts) in {1, 2}:
            roots.append("/".join(parts[:-1]))
    if len(roots) != 1:
        raise ValueError(tr("未找到唯一的软件源码入口，请选择本仓库的源码 ZIP 或完整更新包。"))
    prefix = roots[0] + "/" if roots[0] else ""
    selected, names, total = [], set(), 0
    for info in entries:
        _cancel(stop)
        if info.is_dir():
            continue
        name = info.filename
        if (not name.startswith(prefix) or "\\" in name or name.startswith("/")
                or any(part in {".", ".."} or ":" in part for part in name.split("/"))):
            raise ValueError(tr("源码包包含不安全或不一致的路径。"))
        relative = name[len(prefix):]
        if relative.split("/")[0] in {"tests", "docs", "scripts", "build", ".github", ".git", "__pycache__"}:
            continue
        if relative in {"app_launcher.py", "source_bootstrap.py", "make_update_package.py"}:
            continue
        if relative != "License" and Path(relative).suffix.lower() not in {".py", ".json", ".png", ".ico", ".ps1", ".txt"}:
            continue
        mode = stat.S_IFMT(info.external_attr >> 16)
        if info.flag_bits & 1 or mode not in {0, stat.S_IFREG} or relative.casefold() in names:
            raise ValueError(tr("源码包包含重复文件、加密文件或链接。"))
        names.add(relative.casefold())
        total += info.file_size
        selected.append((info, relative))
    if total > MAX_PAYLOAD or len(selected) > 500:
        raise ValueError(tr("源码包内容超出支持范围。"))
    required = {"paddleocr_pdf_to_md_gui.py", "requirements.txt", "app_icon.png", "app_icon.ico",
                "literature_processing.py", "literature_ui.py", "workspace_ui.py", "ui_translations.py", "ui_i18n.py",
                "responsive_ui.py", "github_ui.py", "model_budget.py", "app_updater.py", "update_ui.py", "update_helper.ps1"}
    mapping = {name: info for info, name in selected}
    if not required <= mapping.keys() or mapping["paddleocr_pdf_to_md_gui.py"].file_size > BLOCK_SIZE or mapping["requirements.txt"].file_size > MAX_MANIFEST:
        raise ValueError(tr("源码包缺少运行所需文件，或入口文件过大。"))
    entry = archive.read(mapping["paddleocr_pdf_to_md_gui.py"]).decode("utf-8-sig")
    try:
        tree = ast.parse(entry)
        versions = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        if len(versions) != 1:
            raise ValueError()
    except (SyntaxError, ValueError) as exc:
        raise ValueError(tr("无法识别源码版本，或源码需要更高版本的 Python。")) from exc
    version = versions[0]
    if version_tuple(version) <= version_tuple(current_version):
        raise ValueError(tr("更新包版本 {arg0} 不高于当前版本 {arg1}。", arg0=version, arg1=current_version))
    # New application modules must travel with their source version. Otherwise
    # validation on a newer runtime could silently fall back to an older bundled
    # module and install an incomplete source archive.
    for introduced, modules in (
        ("26.10.20.01", {"task_runtime.py"}),
        ("26.10.20.02", {"update_cleanup.py"}),
        ("26.10.20.03", {"prompt_templates.py", "advanced_settings.py"}),
    ):
        if version_tuple(version) >= version_tuple(introduced) and not modules <= mapping.keys():
            raise ValueError(tr("源码包缺少运行所需文件，或入口文件过大。"))
    if version_tuple(version) >= (26, 10, 20, 3) and not {"License", "License.txt"} & mapping.keys():
        raise ValueError(tr("源码包缺少运行所需文件，或入口文件过大。"))
    requested = requirements(archive.read(mapping["requirements.txt"]).decode("utf-8-sig"))
    available = getattr(sys, "_paddleocr_requirements", requirements(Path(__file__).with_name("requirements.txt").read_text(encoding="utf-8-sig")))
    if requested != available:
        raise ValueError(tr("源码依赖已改变，需要包含新依赖的完整 EXE 更新包；不会自动联网安装依赖。"))
    source_modules = {name.split("/")[0].removesuffix(".py") for _, name in selected if name.endswith(".py")}
    imported = set()
    for info, name in selected:
        _cancel(stop)
        if name.endswith(".py"):
            if info.file_size > 4 * BLOCK_SIZE:
                raise ValueError(tr("源码包内容超出支持范围。"))
            try:
                module_tree = tree if name == "paddleocr_pdf_to_md_gui.py" else ast.parse(archive.read(info).decode("utf-8-sig"))
            except (SyntaxError, UnicodeError) as exc:
                raise ValueError(tr("无法识别源码版本，或源码需要更高版本的 Python。")) from exc
            for node in ast.walk(module_tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
    for name in imported - source_modules - {"__future__"}:
        _cancel(stop)
        if importlib.util.find_spec(name) is None:
            raise ValueError(tr("当前运行时未包含模块 {arg0}，请使用完整 EXE 更新包。", arg0=name))
    cache.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="update-", dir=cache))
    try:
        mark_owned(directory, "source")
        target = directory / "source"
        hashes, done = {}, 0
        for info, name in selected:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            checksum = hashlib.sha256()
            with archive.open(info) as incoming, path.open("xb") as outgoing:
                while True:
                    _cancel(stop)
                    block = incoming.read(BLOCK_SIZE)
                    if not block:
                        break
                    done += len(block)
                    if done > total:
                        raise ValueError(tr("源码包内容超出支持范围。"))
                    checksum.update(block)
                    outgoing.write(block)
                    progress(done, total)
            # Syntax/imports were checked above. ZipFile verifies the same CRC
            # while extracting; hashing these bytes remains the activation guard.
            hashes[name] = checksum.hexdigest()
        record = {"schema": 1, "application": APPLICATION_ID, "version": version,
                  "directory": str(target), "files": hashes, "requirements": requested}
        checksum = hashlib.sha256()
        with source.open("rb") as handle:
            for block in iter(lambda: handle.read(BLOCK_SIZE), b""):
                _cancel(stop)
                checksum.update(block)
        return SourcePackage(version, source.name, checksum.hexdigest(), total, directory, source, record)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def signal_ready(version):
    marker = os.environ.pop("PADDLEOCR_UPDATE_HEALTH", "")
    acknowledged = None
    if marker:
        try:
            path = Path(marker).resolve()
            path.relative_to(update_cache().resolve())
            if path.name == "ready" and path.parent.name.startswith("update-"):
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(version)
                acknowledged = path
        except (OSError, ValueError):
            pass
    start_maintenance(update_cache(), version, acknowledged,
                      running_source=Path(__file__).absolute().parent,
                      current_exe=running_executable())


def last_result(cache=None):
    path = (Path(cache) if cache is not None else update_cache()) / "last-update.json"
    try:
        if path.stat().st_size > MAX_MANIFEST:
            return None
        result = json.loads(path.read_text(encoding="utf-8-sig"))
        return result if isinstance(result, dict) and result.get("status") in {"installed", "failed"} else None
    except (OSError, ValueError):
        return None


GITHUB_REPOSITORY = "CHNAQW/paddleocr_usage"
DOWNLOAD_HOSTS = {"api.github.com", "github.com", "codeload.github.com", "raw.githubusercontent.com",
                  "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


@dataclass(frozen=True)
class OnlineUpdate:
    version: str
    url: str
    notes: str
    page: str
    sha256: str = ""
    size: int = 0


class GitHubHTTPError(RuntimeError):
    def __init__(self, status, url):
        self.status, self.url = status, url
        message = (tr("GitHub 拒绝了更新请求（HTTP {arg0}），可能遇到 API 限流或网络／代理拦截。请稍后重试；正式发行版检查失败时可尝试 main 渠道。\n地址：{arg1}", arg0=status, arg1=url)
                   if status in {403, 429} else
                   tr("GitHub 更新请求失败（HTTP {arg0}）。请稍后重试。\n地址：{arg1}", arg0=status, arg1=url))
        super().__init__(message)


def _close_response(response):
    """A transport cleanup error must not replace the result or skip file cleanup."""
    try:
        response.close()
    except Exception:
        pass


def _github_response(url, *, stream=False, stop=lambda: False, accept="application/vnd.github+json",
                     _worker_owned=False):
    """Follow only GitHub HTTPS redirects, without forwarding application credentials."""
    from urllib.parse import urlsplit, urljoin
    import requests
    for _ in range(6):
        _cancel(stop)
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in DOWNLOAD_HOSTS or parsed.username
                or parsed.password or parsed.port not in {None, 443}):
            raise ValueError(tr("更新下载地址不属于受支持的 GitHub HTTPS 地址。"))
        try:
            def request():
                return requests.get(url, headers={"Accept": accept, "User-Agent": "PaddleOCR-Updater"},
                                    timeout=(10, 30), stream=stream, allow_redirects=False)
            # Metadata already owns a bounded worker for the entire response
            # lifecycle. A nested acquisition could exhaust the same slot pool.
            response = request() if _worker_owned else cancellable_call(
                request, stop, timeout=50, cancelled=UpdateCancelled)
        except requests.RequestException:
            raise RuntimeError(tr("无法连接 GitHub，请检查网络或代理后重试。")) from None
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location", "")
            _close_response(response)
            if not location:
                break
            url = urljoin(url, location)
            continue
        if response.status_code != 200:
            status = response.status_code
            _close_response(response)
            if status == 404:
                raise ValueError(tr("GitHub 尚无可用发行版或找不到目标代码，请切换更新渠道后重试。"))
            raise GitHubHTTPError(status, url)
        return response
    raise RuntimeError(tr("GitHub 下载重定向次数过多。"))


def _github_bytes(url, stop, limit=4 * BLOCK_SIZE, accept="application/vnd.github+json"):
    # One bounded worker owns headers, redirects, body and close. In particular,
    # cancellation before body reading must never close a response on the caller.
    import threading
    abandoned = threading.Event()
    def stopped():
        return abandoned.is_set() or stop()
    def read():
        response = _github_response(url, stream=True, stop=stopped, accept=accept, _worker_owned=True)
        try:
            _cancel(stopped)
            data = bytearray()
            for block in response.iter_content(64 * 1024):
                _cancel(stopped)
                data.extend(block)
                if len(data) > limit:
                    raise ValueError(tr("GitHub 更新元数据过大。"))
            _cancel(stopped)
            return bytes(data)
        finally:
            _close_response(response)
    try:
        return cancellable_call(read, stop, timeout=METADATA_TIMEOUT, cancelled=UpdateCancelled)
    except BaseException:
        # Reusing/resetting the UI's stop event must not revive an old request.
        abandoned.set()
        raise


def _github_json(path, stop):
    return json.loads(_github_bytes("https://api.github.com/repos/" + GITHUB_REPOSITORY + path, stop))


def _main_commit_from_feed(stop):
    """Public Atom metadata does not consume the unauthenticated REST API quota."""
    from xml.etree import ElementTree
    data = _github_bytes(f"https://github.com/{GITHUB_REPOSITORY}/commits/main.atom", stop,
                         accept="application/atom+xml")
    try:
        root = ElementTree.fromstring(data)
        entry = root.find("{http://www.w3.org/2005/Atom}entry")
        identifier = entry.findtext("{http://www.w3.org/2005/Atom}id", "")
        match = re.fullmatch(r"tag:github\.com,2008:Grit::Commit/([0-9a-f]{40})", identifier)
        if not match:
            raise ValueError()
        return match.group(1), entry.findtext("{http://www.w3.org/2005/Atom}title", "")[:1500]
    except (ElementTree.ParseError, AttributeError, ValueError) as exc:
        raise ValueError(tr("GitHub 返回的提交标识无效。")) from exc


def _main_source_version(sha, stop, use_api=True):
    if use_api:
        try:
            entry = _github_json("/contents/paddleocr_pdf_to_md_gui.py?ref=" + sha, stop)
            if entry.get("encoding") != "base64" or entry.get("size", MAX_PAYLOAD) > BLOCK_SIZE:
                raise ValueError(tr("GitHub 源码入口无法读取。"))
            code = base64.b64decode(entry["content"])
        except GitHubHTTPError as exc:
            if exc.status not in {403, 429}:
                raise
            use_api = False
    if not use_api:
        code = _github_bytes(f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/{sha}/paddleocr_pdf_to_md_gui.py",
                             stop, BLOCK_SIZE, accept="text/plain")
    try:
        if len(code) > BLOCK_SIZE:
            raise ValueError()
        tree = ast.parse(code.decode("utf-8-sig"))
        versions = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in node.targets)
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        if len(versions) != 1:
            raise ValueError()
        version_tuple(versions[0])
        return versions[0]
    except (SyntaxError, UnicodeError, ValueError) as exc:
        raise ValueError(tr("GitHub 源码入口无法读取。")) from exc


def _source_archive(sha):
    # REST zipball downloads also consume the API quota and can return 403
    # after a successful version check. Use GitHub's archive host directly.
    return f"https://codeload.github.com/{GITHUB_REPOSITORY}/zip/{sha}"


def check_github_update(current_version, channel="release", stop=lambda: False):
    """Only explicit checks perform network I/O. Pin source downloads to an immutable commit."""
    page = f"https://github.com/{GITHUB_REPOSITORY}"
    if channel == "main":
        use_api = True
        try:
            commit = _github_json("/commits/main", stop)
            sha, notes = commit.get("sha", ""), str(commit.get("commit", {}).get("message", ""))[:1500]
        except GitHubHTTPError as exc:
            if exc.status not in {403, 429}:
                raise
            use_api = False
            sha, notes = _main_commit_from_feed(stop)
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError(tr("GitHub 返回的提交标识无效。"))
        version = _main_source_version(sha, stop, use_api)
        offer = OnlineUpdate(version, _source_archive(sha), notes, page + "/commit/" + sha)
    elif channel == "release":
        release = _github_json("/releases/latest", stop)
        if release.get("draft") or release.get("prerelease"):
            raise ValueError(tr("GitHub 尚无可用发行版或找不到目标代码，请切换更新渠道后重试。"))
        version = str(release.get("tag_name", "")).removeprefix("v")
        if version_tuple(version) <= version_tuple(current_version):
            return None
        expected = "PaddleOCR_Update_" + version + ".zip"
        assets = [a for a in release.get("assets", []) if a.get("name") == expected and a.get("state", "uploaded") == "uploaded"]
        notes = str(release.get("body") or "")[:1500]
        tag = str(release.get("tag_name", ""))
        from urllib.parse import quote
        if assets:
            asset = assets[0]
            size = asset.get("size", 0)
            if not isinstance(size, int) or not 0 < size <= MAX_PAYLOAD:
                raise ValueError(tr("在线更新包大小超出支持范围。"))
            digest = str(asset.get("digest") or "")
            if digest and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
                raise ValueError(tr("GitHub 更新包校验值无效。"))
            url = page + "/releases/download/" + quote(tag, safe="") + "/" + quote(expected, safe="")
            offer = OnlineUpdate(version, url, notes, page + "/releases/tag/" + quote(tag, safe=""), digest[7:].lower(), size)
        else:
            commit = _github_json("/commits/" + quote(tag, safe=""), stop)
            sha = commit.get("sha", "")
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError(tr("GitHub 返回的提交标识无效。"))
            offer = OnlineUpdate(version, _source_archive(sha), notes, page + "/releases/tag/" + quote(tag, safe=""))
    else:
        raise ValueError(tr("请选择有效的更新渠道。"))
    return offer if version_tuple(offer.version) > version_tuple(current_version) else None


class _DownloadedPackage:
    """Transfer staging ownership only if a bounded download was not abandoned."""
    def __init__(self, package):
        self.package = package

    def take(self):
        package, self.package = self.package, None
        return package

    def close(self):
        package = self.take()
        if package is not None:
            discard_package(package)


def download_github_update(offer, current_version, cache=None, stop=lambda: False, progress=lambda done, total: None):
    """Return promptly on stop/deadline; the transport retains its own staging files."""
    if not isinstance(offer, OnlineUpdate) or version_tuple(offer.version) <= version_tuple(current_version):
        raise ValueError(tr("没有可下载的新版。"))
    import threading
    abandoned = threading.Event()

    def stopped():
        return abandoned.is_set() or stop()

    def download():
        return _DownloadedPackage(_download_github_update(offer, current_version, cache, stopped, progress))

    try:
        delivery = cancellable_call(download, stop, timeout=DOWNLOAD_TIMEOUT, cancelled=UpdateCancelled)
        return delivery.take()
    except BaseException:
        # The UI may reuse/reset its stop event for another task. Keep the old
        # transport cancelled until its socket unblocks and its own finally runs.
        abandoned.set()
        raise


def _download_github_update(offer, current_version, cache, stop, progress):
    """The sole owner of downloading/extracting files, including after cancellation."""
    cache = Path(cache) if cache is not None else update_cache()
    cache.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="download-", dir=cache))
    package, response = None, None
    try:
        mark_owned(directory, "download")
        response = _github_response(offer.url, stream=True, stop=stop, accept="application/zip")
        declared = int(response.headers.get("Content-Length", 0))
        if declared < 0 or declared > MAX_PAYLOAD or (offer.size and declared and declared != offer.size):
            raise ValueError(tr("在线更新包大小超出支持范围。"))
        source = directory / "github-update.zip"
        digest, size = hashlib.sha256(), 0
        with source.open("xb") as output:
            for block in response.iter_content(256 * 1024):
                _cancel(stop)
                size += len(block)
                if size > MAX_PAYLOAD:
                    raise ValueError(tr("在线更新包大小超出支持范围。"))
                output.write(block)
                digest.update(block)
                progress(size, declared or offer.size or MAX_PAYLOAD)
        if (not size or (declared and size != declared) or (offer.size and size != offer.size)
                or (offer.sha256 and digest.hexdigest() != offer.sha256)):
            raise ValueError(tr("下载大小或 SHA-256 校验失败，请重新下载。"))
        package = import_package(source, current_version, cache=cache, stop=stop, progress=progress)
        _cancel(stop)
        if package.version != offer.version:
            raise ValueError(tr("下载内容的版本与检查结果不一致，未安装。"))
        # Keep the downloaded ZIP alongside the staged payload until installation/discard.
        target = package.directory / "download.zip"
        shutil.move(str(source), target)
        from dataclasses import replace
        return replace(package, source=target)
    except BaseException:
        if package:
            discard_package(package)
        raise
    finally:
        if response is not None:
            _close_response(response)
        shutil.rmtree(directory, ignore_errors=True)
