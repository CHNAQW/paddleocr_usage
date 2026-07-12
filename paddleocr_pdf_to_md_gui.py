# -*- coding: utf-8 -*-
"""
PaddleOCR PDF -> Markdown 批处理图形化工具

本版要点：
1. 使用 PaddleOCR official API 异步任务接口（仅需 requests，不再依赖本地 paddleocr 包）：提交任务 -> 保存 jobId -> 轮询进度 -> 下载 Markdown。
2. 支持单个 PDF 内部页数进度：已解析页数 / 总页数。
3. 遇到“任务提交队列已满，请稍后重试”（错误码 10010）会自动等待并重新提交。
4. 提供“检测 API Key 是否有效”按钮。
5. 提供“手动查询当前结果”按钮，可打断轮询等待并立即查询一次。
6. 正确解析异步接口 jsonUrl 返回的 JSONL，并从 layoutParsingResults[*].markdown.text 提取 Markdown。
7. 新增“修复JSON为MD”功能，可把已有 .json/.jsonl/.raw.json 修复成可直接使用的 .md。
8. 超过 50MB 的 PDF 自动按页拆分，逐段 OCR 后合并为一个 .md 和一个 .json。
9. Access Token / API Key 保存到用户目录配置文件，不需要每次输入。
10. 默认模型保留 PaddleOCR-VL-1.6。
11. 图形界面随窗口大小自适应。
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

try:
    import requests
except Exception:  # pragma: no cover - 运行时给用户明确提示
    requests = None  # type: ignore

try:
    from pypdf import PdfReader, PdfWriter
except Exception:  # pragma: no cover - 运行时给用户明确提示
    PdfReader = None  # type: ignore
    PdfWriter = None  # type: ignore

APP_NAME = "PaddleOCR PDF批量转Markdown"
APP_VERSION = "26.7.12.02"
SCRIPT_PATH = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else Path(__file__).resolve()
CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "PaddleOCRBatchGUI"
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_FILE_NAME = "paddleocr_batch_log.txt"
MAX_LOCAL_UPLOAD_MB = 50.0
SPLIT_TARGET_MB = 45.0
MAX_PAGES_PER_SPLIT = 900
DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com"
JOB_PATH = "/api/v2/ocr/jobs"
DEFAULT_POLL_INTERVAL = 3.0
QUEUE_FULL_RETRY_SECONDS = 20.0
QUEUE_FULL_MAX_ATTEMPTS = 3
RATE_LIMIT_RETRY_SECONDS = 20.0
REQUEST_TIMEOUT_SECONDS = 300.0
TOKEN_CHECK_TIMEOUT_SECONDS = 20.0

DEFAULT_MODEL = "PaddleOCR-VL-1.6"
MODEL_CHOICES = [
    "PaddleOCR-VL-1.6",
    "PaddleOCR-VL-1.5",
    "PaddleOCR-VL",
    "PP-StructureV3",
]



def choose_cjk_font_family(root: tk.Tk) -> str:
    """Choose an installed font with reliable CJK coverage for the current OS."""
    try:
        installed = {name.lower(): name for name in tkfont.families(root)}
    except Exception:
        installed = {}

    if sys.platform.startswith("win"):
        candidates = [
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "SimHei",
            "SimSun",
            "Arial Unicode MS",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "PingFang SC",
            "Hiragino Sans GB",
            "Heiti SC",
            "Songti SC",
            "Arial Unicode MS",
        ]
    else:
        candidates = [
            "Noto Sans CJK SC",
            "Noto Sans CJK TC",
            "Source Han Sans SC",
            "WenQuanYi Micro Hei",
            "WenQuanYi Zen Hei",
            "Droid Sans Fallback",
            "DejaVu Sans",
        ]

    for candidate in candidates:
        actual = installed.get(candidate.lower())
        if actual:
            return actual

    try:
        return str(tkfont.nametofont("TkDefaultFont", root=root).cget("family"))
    except Exception:
        return "TkDefaultFont"


def configure_unicode_ui_fonts(root: tk.Tk) -> str:
    """Apply a Unicode-capable font to Tk and ttk widgets to prevent CJK garbling."""
    family = choose_cjk_font_family(root)

    named_font_sizes = {
        "TkDefaultFont": 10,
        "TkTextFont": 10,
        "TkFixedFont": 10,
        "TkMenuFont": 10,
        "TkHeadingFont": 10,
        "TkCaptionFont": 10,
        "TkSmallCaptionFont": 9,
        "TkIconFont": 10,
        "TkTooltipFont": 9,
    }
    for font_name, size in named_font_sizes.items():
        try:
            named = tkfont.nametofont(font_name, root=root)
            named.configure(family=family, size=size)
        except Exception:
            pass

    try:
        root.option_add("*Font", "TkDefaultFont")
        root.option_add("*Text.Font", "TkTextFont")
        root.option_add("*Menu.Font", "TkMenuFont")
        root.option_add("*Listbox.Font", "TkTextFont")
    except Exception:
        pass

    try:
        style = ttk.Style(root)
        style.configure(".", font=(family, 10))
        style.configure("TLabelframe.Label", font=(family, 10, "bold"))
        style.configure("TButton", font=(family, 10))
        style.configure("TCheckbutton", font=(family, 10))
        style.configure("TCombobox", font=(family, 10))
    except Exception:
        pass

    return family


@dataclass
class AppConfig:
    token: str = ""
    input_dir: str = ""
    output_dir: str = ""
    model: str = DEFAULT_MODEL
    recursive: bool = True
    preserve_subfolders: bool = True
    overwrite: bool = False
    request_timeout: float = REQUEST_TIMEOUT_SECONDS
    poll_timeout: float = 3600.0
    poll_interval: float = DEFAULT_POLL_INTERVAL
    base_url: str = DEFAULT_BASE_URL


class PaddleOCRAPIError(RuntimeError):
    def __init__(self, message: str, code: Optional[int] = None, payload: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


class StopRequested(RuntimeError):
    pass


class QueueFullSkipped(RuntimeError):
    pass


@dataclass
class SplitPdfPart:
    path: Path
    part_index: int
    page_start: int
    page_end: int
    size_mb: float

    @property
    def page_count(self) -> int:
        return self.page_end - self.page_start + 1


def require_pypdf() -> None:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError(
            "检测到超过 50MB 的 PDF，但当前环境缺少 pypdf，无法自动拆分。"
            "请运行：python -m pip install --upgrade pypdf"
        )


def _write_pdf_page_range(reader: Any, start_index: int, end_index: int, output_path: Path) -> float:
    """写出 [start_index, end_index) 页，并返回文件大小（MB）。"""
    writer = PdfWriter()
    for page_index in range(start_index, end_index):
        writer.add_page(reader.pages[page_index])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        writer.write(f)
    return get_file_size_mb(output_path)


def _split_range_to_limit(
    reader: Any,
    start_index: int,
    end_index: int,
    work_dir: Path,
    source_stem: str,
    target_mb: float,
    max_pages: int,
    output_ranges: list[tuple[int, int, Path, float]],
) -> None:
    """递归把页区间切到目标大小和页数限制以内，保持原始页序。"""
    page_count = end_index - start_index
    probe_path = work_dir / f"probe_{start_index + 1:06d}_{end_index:06d}.pdf"
    size_mb = _write_pdf_page_range(reader, start_index, end_index, probe_path)

    if size_mb <= target_mb and page_count <= max_pages:
        output_ranges.append((start_index, end_index, probe_path, size_mb))
        return

    try:
        probe_path.unlink()
    except Exception:
        pass

    if page_count <= 1:
        raise RuntimeError(
            f"原 PDF 第 {start_index + 1} 页单独拆分后仍有 {size_mb:.2f}MB，"
            f"超过单次上传安全目标 {target_mb:.0f}MB，无法自动拆分。"
        )

    mid = start_index + page_count // 2
    _split_range_to_limit(
        reader, start_index, mid, work_dir, source_stem, target_mb, max_pages, output_ranges
    )
    _split_range_to_limit(
        reader, mid, end_index, work_dir, source_stem, target_mb, max_pages, output_ranges
    )


def split_pdf_for_upload(
    pdf_path: Path,
    output_root: Path,
    log_callback,
    target_mb: float = SPLIT_TARGET_MB,
) -> tuple[list[SplitPdfPart], Path, int]:
    """把超限 PDF 自动拆成可上传的分段；中断后可复用现有拆分结果。"""
    require_pypdf()
    source_key = file_identity_key(pdf_path)
    work_dir = output_root / "_paddleocr_split_work" / f"{safe_filename(pdf_path.stem)}_{source_key}"
    manifest_path = work_dir / "manifest.json"

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            parts: list[SplitPdfPart] = []
            for item in manifest.get("parts", []):
                part_path = work_dir / str(item["filename"])
                if not part_path.exists():
                    raise FileNotFoundError(part_path)
                parts.append(
                    SplitPdfPart(
                        path=part_path,
                        part_index=int(item["partIndex"]),
                        page_start=int(item["pageStart"]),
                        page_end=int(item["pageEnd"]),
                        size_mb=float(item["sizeMB"]),
                    )
                )
            if parts:
                total_pages = int(manifest.get("totalPages") or parts[-1].page_end)
                log_callback(f"复用既有拆分结果：共 {len(parts)} 段，{total_pages} 页。")
                return parts, work_dir, total_pages
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)

    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"无法读取待拆分 PDF：{pdf_path}\n{e}") from e

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as e:
            raise RuntimeError(f"PDF 已加密，无法自动拆分：{pdf_path.name}") from e

    total_pages = len(reader.pages)
    if total_pages <= 0:
        raise RuntimeError(f"PDF 没有可拆分页面：{pdf_path.name}")

    source_size_mb = get_file_size_mb(pdf_path)
    estimated_pages = max(1, min(MAX_PAGES_PER_SPLIT, int(total_pages * target_mb / max(source_size_mb, 0.01))))
    ranges: list[tuple[int, int, Path, float]] = []
    start = 0
    while start < total_pages:
        end = min(total_pages, start + estimated_pages)
        _split_range_to_limit(
            reader, start, end, work_dir, pdf_path.stem, target_mb, MAX_PAGES_PER_SPLIT, ranges
        )
        start = end

    parts: list[SplitPdfPart] = []
    for index, (start_index, end_index, probe_path, size_mb) in enumerate(ranges, start=1):
        final_name = f"{safe_filename(pdf_path.stem)}__part_{index:03d}__p{start_index + 1}-{end_index}.pdf"
        final_path = work_dir / final_name
        if final_path.exists():
            final_path.unlink()
        probe_path.replace(final_path)
        parts.append(
            SplitPdfPart(
                path=final_path,
                part_index=index,
                page_start=start_index + 1,
                page_end=end_index,
                size_mb=size_mb,
            )
        )

    manifest = {
        "sourcePdf": str(pdf_path),
        "sourceSizeMB": source_size_mb,
        "sourceIdentity": source_key,
        "totalPages": total_pages,
        "targetPartMB": target_mb,
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "parts": [
            {
                "partIndex": part.part_index,
                "filename": part.path.name,
                "pageStart": part.page_start,
                "pageEnd": part.page_end,
                "sizeMB": round(part.size_mb, 4),
            }
            for part in parts
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log_callback(
        f"自动拆分完成：{pdf_path.name}（{source_size_mb:.2f}MB，{total_pages} 页）"
        f" -> {len(parts)} 段，每段不超过约 {target_mb:.0f}MB。"
    )
    return parts, work_dir, total_pages


def _compact_part_raw_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    """合并 JSON 时移除可由 parsed 结果替代的重复大文本，控制最终文件体积。"""
    compact = dict(raw_data)
    if compact.get("resultJsonParsed") is not None:
        compact.pop("resultJsonText", None)
    return compact


def process_split_pdf_async(
    pdf_path: Path,
    output_md_path: Path,
    output_root: Path,
    token: str,
    model_name: str,
    base_url: str,
    request_timeout: float,
    poll_timeout: float,
    poll_interval: float,
    overwrite: bool,
    stop_checker,
    progress_callback,
    log_callback,
    manual_query_event: Optional[threading.Event] = None,
) -> tuple[str, dict[str, Any]]:
    """拆分超限 PDF、逐段 OCR，并合并为一个 .md 和一个 .json。"""
    parts, work_dir, total_pages = split_pdf_for_upload(pdf_path, output_root, log_callback)
    merged_markdown_parts: list[str] = []
    merged_part_json: list[dict[str, Any]] = []

    for part in parts:
        if stop_checker():
            raise StopRequested("用户请求停止，已停止处理拆分文档。")
        log_callback(
            f"开始处理拆分段 {part.part_index}/{len(parts)}："
            f"原文第 {part.page_start}-{part.page_end} 页，{part.size_mb:.2f}MB"
        )
        part_md = work_dir / f"part_{part.part_index:03d}.md"

        def part_progress(state: str, done_pages: int, part_total: int, percent: float, message: str) -> None:
            completed_before = part.page_start - 1
            if state == "done":
                global_done = part.page_end
            elif part_total > 0:
                global_done = min(part.page_end, completed_before + done_pages)
            else:
                global_done = completed_before
            global_percent = global_done / total_pages * 100 if total_pages else 0.0
            progress_callback(
                state,
                global_done,
                total_pages,
                global_percent,
                f"第 {part.part_index}/{len(parts)} 段：{message}",
            )

        markdown, raw_data = process_one_pdf_async(
            pdf_path=part.path,
            output_md_path=part_md,
            output_root=output_root,
            token=token,
            model_name=model_name,
            base_url=base_url,
            request_timeout=request_timeout,
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
            overwrite=overwrite,
            stop_checker=stop_checker,
            progress_callback=part_progress,
            log_callback=log_callback,
            manual_query_event=manual_query_event,
        )
        merged_markdown_parts.append(
            f"<!-- 自动拆分 OCR：原 PDF 第 {part.page_start}-{part.page_end} 页 -->\n\n{markdown.strip()}"
        )
        merged_part_json.append(
            {
                "partIndex": part.part_index,
                "pageStart": part.page_start,
                "pageEnd": part.page_end,
                "splitPdfSizeMB": round(part.size_mb, 4),
                "rawResult": _compact_part_raw_data(raw_data),
            }
        )

    merged_markdown = "\n\n---\n\n".join(merged_markdown_parts).strip() + "\n"
    merged_json = {
        "programVersion": APP_VERSION,
        "sourcePdf": str(pdf_path),
        "sourceSizeMB": round(get_file_size_mb(pdf_path), 4),
        "autoSplit": True,
        "totalPages": total_pages,
        "partCount": len(parts),
        "model": model_name,
        "mergedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "parts": merged_part_json,
    }

    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text(merged_markdown, encoding="utf-8")
    merged_json_path = output_md_path.with_suffix(".json")
    merged_json_path.write_text(json.dumps(merged_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # 成功合并后移除中间 PDF、分段 Markdown 和分段 raw.json；job 缓存保留以便排错。
    shutil.rmtree(work_dir, ignore_errors=True)
    try:
        if work_dir.parent.exists() and not any(work_dir.parent.iterdir()):
            work_dir.parent.rmdir()
    except Exception:
        pass
    log_callback(f"拆分结果已合并：{output_md_path}；{merged_json_path}")
    return merged_markdown, merged_json


def load_config() -> AppConfig:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = AppConfig(**{**AppConfig().__dict__, **data})
            if cfg.model not in MODEL_CHOICES:
                cfg.model = DEFAULT_MODEL
            if not cfg.base_url:
                cfg.base_url = DEFAULT_BASE_URL
            return cfg
        except Exception:
            return AppConfig()
    return AppConfig()


def save_config(config: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "output"


def find_pdf_files(input_dir: Path, recursive: bool) -> list[Path]:
    files = list(input_dir.rglob("*.pdf")) if recursive else list(input_dir.glob("*.pdf"))
    return sorted([p for p in files if p.is_file()], key=lambda p: str(p).lower())


def get_file_size_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def split_oversized_pdfs(pdfs: list[Path], max_mb: float = MAX_LOCAL_UPLOAD_MB) -> tuple[list[Path], list[tuple[Path, float]]]:
    valid: list[Path] = []
    oversized: list[tuple[Path, float]] = []
    for pdf in pdfs:
        try:
            size_mb = get_file_size_mb(pdf)
        except OSError:
            valid.append(pdf)
            continue
        if size_mb > max_mb:
            oversized.append((pdf, size_mb))
        else:
            valid.append(pdf)
    return valid, oversized


def format_oversized_message(oversized: list[tuple[Path, float]]) -> str:
    lines = [
        "有单一文档超过50MB，请压缩后再行处理。超出限制的文档是：",
        "",
    ]
    for pdf, size_mb in oversized:
        lines.append(f"- {pdf}（{size_mb:.2f} MB）")
    return "\n".join(lines)


def build_output_path(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    preserve_subfolders: bool,
    existing: set[Path],
) -> Path:
    if preserve_subfolders:
        try:
            rel = pdf_path.relative_to(input_root)
        except ValueError:
            rel = Path(pdf_path.name)
        out = output_root / rel.with_suffix(".md")
    else:
        out = output_root / f"{pdf_path.stem}.md"

    out.parent.mkdir(parents=True, exist_ok=True)

    candidate = out
    idx = 2
    while candidate in existing:
        candidate = out.with_name(f"{out.stem}_{idx}{out.suffix}")
        idx += 1
    existing.add(candidate)
    return candidate


def file_identity_key(pdf_path: Path) -> str:
    try:
        stat = pdf_path.stat()
        raw = f"{pdf_path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    except Exception:
        raw = str(pdf_path.resolve())
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def get_job_cache_path(output_root: Path, pdf_path: Path) -> Path:
    cache_dir = output_root / "_paddleocr_jobs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{safe_filename(pdf_path.stem)}_{file_identity_key(pdf_path)}.job.json"


def get_job_url(base_url: str) -> str:
    base = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    return f"{base}{JOB_PATH}"


def auth_headers(token: str, json_content: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token.strip()}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def parse_response_json(resp: Any) -> dict[str, Any]:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"code": None, "msg": str(data), "data": data}
    except Exception:
        text = getattr(resp, "text", "")
        return {"code": None, "msg": text[:500], "data": None}


def api_error_message(data: dict[str, Any], status_code: Optional[int] = None) -> str:
    code = data.get("code")
    msg = data.get("msg") or data.get("message") or ""
    detail = ""
    if isinstance(data.get("data"), dict):
        detail = data["data"].get("errorMsg") or ""
    prefix = f"HTTP {status_code}，" if status_code else ""
    code_part = f"code={code}，" if code is not None else ""
    return f"{prefix}{code_part}{msg or detail or data}".strip("，")


def is_queue_full_error(data: dict[str, Any]) -> bool:
    code = data.get("code")
    msg = str(data.get("msg") or data.get("message") or "")
    detail = ""
    if isinstance(data.get("data"), dict):
        detail = str(data["data"].get("errorMsg") or "")
    text = f"{msg} {detail}"
    return code == 10010 or "任务提交队列已满" in text or "queue" in text.lower() and "full" in text.lower()


def is_rate_limit_error(data: dict[str, Any], status_code: Optional[int] = None) -> bool:
    return data.get("code") == 12002 or status_code == 429


def build_optional_payload(model_name: str) -> dict[str, Any]:
    if model_name == "PP-StructureV3":
        return {
            "useTableRecognition": True,
            "useFormulaRecognition": True,
            "useChartRecognition": False,
            "prettifyMarkdown": True,
        }
    return {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }


def validate_access_token(token: str, base_url: str = DEFAULT_BASE_URL) -> tuple[bool, str, dict[str, Any]]:
    """轻量检测 token。使用不存在的 jobId 查询：有效 token 通常返回 11001/jobId 不存在；无效 token 返回 401。"""
    if requests is None:
        return False, "缺少 requests 包。请运行：python -m pip install requests", {}
    if not token.strip():
        return False, "Access Token/API Key 为空。", {}

    url = f"{get_job_url(base_url)}/ocrjob-token-check-probe"
    try:
        resp = requests.get(url, headers=auth_headers(token, json_content=True), timeout=TOKEN_CHECK_TIMEOUT_SECONDS)
    except Exception as e:
        return False, f"检测请求失败：{e}", {}

    data = parse_response_json(resp)
    code = data.get("code")
    msg = str(data.get("msg") or data.get("message") or "")

    if resp.status_code == 401 or code == 401:
        return False, "Token 无效：接口返回 401。", data
    if code in {11001, 11002} or resp.status_code == 404:
        return True, "API Key/Access Token 有效：接口已通过鉴权。", data
    if resp.status_code in {200, 400} and code not in {401, None}:
        # 只要不是鉴权失败，多数情况下说明 token 已通过鉴权；保守提示具体返回。
        return True, f"API Key/Access Token 基本有效：接口返回 {api_error_message(data, resp.status_code)}。", data
    return False, f"无法确认 Token 是否有效：{api_error_message(data, resp.status_code)}。", data


def submit_document_job_once(
    pdf_path: Path,
    token: str,
    model_name: str,
    batch_id: str,
    base_url: str,
    request_timeout: float,
) -> dict[str, Any]:
    if requests is None:
        raise RuntimeError("缺少 requests 包。请运行：python -m pip install requests")

    job_url = get_job_url(base_url)
    optional_payload = build_optional_payload(model_name)
    headers = auth_headers(token)
    data = {
        "model": model_name,
        "optionalPayload": json.dumps(optional_payload, ensure_ascii=False),
        "batchId": batch_id,
    }

    try:
        with open(pdf_path, "rb") as f:
            files = {"file": f}
            resp = requests.post(job_url, headers=headers, data=data, files=files, timeout=float(request_timeout))
    except Exception as e:
        raise PaddleOCRAPIError(f"提交任务请求失败：{e}") from e

    payload = parse_response_json(resp)
    if resp.status_code == 401 or payload.get("code") == 401:
        raise PaddleOCRAPIError("Token 无效：接口返回 401。", code=401, payload=payload)
    if resp.status_code not in {200, 201} or payload.get("code") not in {0, None}:
        code = payload.get("code")
        raise PaddleOCRAPIError(api_error_message(payload, resp.status_code), code=code, payload=payload)

    job_id = None
    if isinstance(payload.get("data"), dict):
        job_id = payload["data"].get("jobId")
    if not job_id:
        raise PaddleOCRAPIError(f"提交成功但没有返回 jobId：{payload}", payload=payload)
    return payload


def submit_document_job_with_retry(
    pdf_path: Path,
    token: str,
    model_name: str,
    batch_id: str,
    base_url: str,
    request_timeout: float,
    stop_checker,
    log_callback,
) -> dict[str, Any]:
    attempt = 0
    while True:
        if stop_checker():
            raise StopRequested("用户请求停止，已取消提交任务。")
        attempt += 1
        try:
            return submit_document_job_once(
                pdf_path=pdf_path,
                token=token,
                model_name=model_name,
                batch_id=batch_id,
                base_url=base_url,
                request_timeout=request_timeout,
            )
        except PaddleOCRAPIError as e:
            payload = e.payload or {}
            if is_queue_full_error(payload):
                if attempt >= QUEUE_FULL_MAX_ATTEMPTS:
                    raise QueueFullSkipped(
                        f"任务提交队列已满，请稍后重试。已尝试 {QUEUE_FULL_MAX_ATTEMPTS} 次提交，跳过该文件：{pdf_path.name}"
                    ) from e
                log_callback(
                    f"任务提交队列已满，请稍后重试。第 {attempt}/{QUEUE_FULL_MAX_ATTEMPTS} 次提交未成功，"
                    f"{QUEUE_FULL_RETRY_SECONDS:.0f} 秒后自动重新提交：{pdf_path.name}"
                )
                wait_with_stop(QUEUE_FULL_RETRY_SECONDS, stop_checker)
                continue
            if is_rate_limit_error(payload):
                log_callback(
                    f"请求频率过高，{RATE_LIMIT_RETRY_SECONDS:.0f} 秒后自动重试提交：{pdf_path.name}"
                )
                wait_with_stop(RATE_LIMIT_RETRY_SECONDS, stop_checker)
                continue
            raise


def wait_with_stop(seconds: float, stop_checker) -> None:
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        if stop_checker():
            raise StopRequested("用户请求停止。")
        time.sleep(min(0.5, end - time.time()))


def wait_for_poll_interval(seconds: float, stop_checker, manual_query_event: Optional[threading.Event] = None) -> bool:
    """等待下一轮自动轮询；如果用户点击“手动查询当前结果”，立即返回 True。"""
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        if stop_checker():
            raise StopRequested("用户请求停止。")
        if manual_query_event is not None and manual_query_event.is_set():
            manual_query_event.clear()
            return True
        time.sleep(min(0.2, end - time.time()))
    return False


def get_job_status(job_id: str, token: str, base_url: str, request_timeout: float) -> dict[str, Any]:
    if requests is None:
        raise RuntimeError("缺少 requests 包。请运行：python -m pip install requests")
    url = f"{get_job_url(base_url)}/{job_id}"
    try:
        resp = requests.get(url, headers=auth_headers(token, json_content=True), timeout=float(request_timeout))
    except Exception as e:
        raise PaddleOCRAPIError(f"查询任务状态失败：{e}") from e
    payload = parse_response_json(resp)
    if resp.status_code == 401 or payload.get("code") == 401:
        raise PaddleOCRAPIError("Token 无效：接口返回 401。", code=401, payload=payload)
    if payload.get("code") not in {0, None} or resp.status_code not in {200, 201}:
        code = payload.get("code")
        raise PaddleOCRAPIError(api_error_message(payload, resp.status_code), code=code, payload=payload)
    return payload


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def poll_job_until_done(
    job_id: str,
    token: str,
    base_url: str,
    request_timeout: float,
    poll_timeout: float,
    poll_interval: float,
    stop_checker,
    progress_callback,
    log_callback,
    manual_query_event: Optional[threading.Event] = None,
) -> dict[str, Any]:
    start = time.time()
    last_done = -1
    last_total = 0
    while True:
        if stop_checker():
            raise StopRequested("用户请求停止，已停止轮询当前任务。")
        if poll_timeout and time.time() - start > float(poll_timeout):
            raise TimeoutError(f"任务 {job_id} 查询超时，超过 {poll_timeout:.0f} 秒。")

        payload = get_job_status(job_id, token, base_url, request_timeout)
        job = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        state = str(job.get("state") or "").lower()

        if state == "pending":
            progress_callback("pending", 0, 0, 0.0, "排队中")
        elif state == "running":
            progress = job.get("extractProgress") if isinstance(job.get("extractProgress"), dict) else {}
            total_pages = int_or_zero(progress.get("totalPages"))
            done_pages = int_or_zero(progress.get("extractedPages"))
            percent = done_pages / total_pages * 100 if total_pages else 0.0
            if total_pages and (done_pages != last_done or total_pages != last_total):
                log_callback(f"页数进度：{done_pages}/{total_pages} 页（{percent:.2f}%）")
                last_done = done_pages
                last_total = total_pages
            progress_callback("running", done_pages, total_pages, percent, f"正在解析：{done_pages}/{total_pages} 页")
        elif state == "done":
            progress = job.get("extractProgress") if isinstance(job.get("extractProgress"), dict) else {}
            total_pages = int_or_zero(progress.get("totalPages"))
            done_pages = int_or_zero(progress.get("extractedPages")) or total_pages
            progress_callback("done", done_pages or 1, total_pages or 1, 100.0, "解析完成")
            return payload
        elif state == "failed":
            err = job.get("errorMsg") or payload.get("msg") or payload
            raise PaddleOCRAPIError(f"任务解析失败：{err}", code=11003, payload=payload)
        else:
            log_callback(f"当前任务状态：{state or '未知'}")
            progress_callback(state or "unknown", 0, 0, 0.0, f"状态：{state or '未知'}")

        interrupted = wait_for_poll_interval(max(1.0, float(poll_interval)), stop_checker, manual_query_event)
        if interrupted:
            log_callback("收到手动查询请求，立即查询当前任务状态。")


def download_text_url(url: str, timeout: float) -> str:
    if requests is None:
        raise RuntimeError("缺少 requests 包。请运行：python -m pip install requests")
    resp = requests.get(url, timeout=float(timeout))
    resp.raise_for_status()
    if resp.encoding is None:
        resp.encoding = "utf-8"
    return resp.text


def download_binary_url(url: str, timeout: float) -> bytes:
    if requests is None:
        raise RuntimeError("缺少 requests 包。请运行：python -m pip install requests")
    resp = requests.get(url, timeout=float(timeout))
    resp.raise_for_status()
    return resp.content


def iter_dicts(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, dict):
        yield data
        for v in data.values():
            yield from iter_dicts(v)
    elif isinstance(data, list):
        for item in data:
            yield from iter_dicts(item)


def parse_json_or_jsonl_text(text: str) -> Any:
    """兼容普通 JSON 与官方异步接口返回的 JSONL。"""
    raw = (text or "").lstrip("\ufeff").strip()
    if not raw:
        return []

    # 先按普通 JSON 尝试。
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 再按 JSONL 尝试：一行一个 JSON。
    items: list[Any] = []
    bad_lines: list[tuple[int, str]] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            items.append(json.loads(line))
        except Exception:
            bad_lines.append((line_no, line[:120]))

    if items:
        return items

    # 保留原文，便于报错时写入排查文件。
    return {"_unparsed_text": raw, "_jsonl_bad_lines": bad_lines[:20]}


def read_json_or_jsonl_file(path: Path) -> Any:
    return parse_json_or_jsonl_text(path.read_text(encoding="utf-8", errors="replace"))


def text_looks_like_json_or_jsonl(value: str) -> bool:
    s = (value or "").lstrip("\ufeff").strip()
    if not s:
        return False
    if s[0] in "[{":
        return True
    first = next((line.strip() for line in s.splitlines() if line.strip()), "")
    return first.startswith("{") or first.startswith("[") or first.startswith("data:")


def is_http_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def is_probably_markdown(value: str) -> bool:
    s = (value or "").strip()
    if not s or is_http_url(s):
        return False
    if len(s) < 2:
        return False
    # 不把大段 JSON/JSONL 当作 Markdown 写进去。
    if text_looks_like_json_or_jsonl(s):
        return False
    return True


def _extract_markdown_text_from_markdown_obj(markdown_obj: Any) -> list[str]:
    parts: list[str] = []
    if isinstance(markdown_obj, str):
        if is_probably_markdown(markdown_obj):
            parts.append(markdown_obj.strip())
        return parts
    if isinstance(markdown_obj, dict):
        # 官方 JSONL 示例：res["markdown"]["text"]。
        for key in ("text", "markdown", "md", "content", "markdownText", "markdown_text"):
            value = markdown_obj.get(key)
            if isinstance(value, str) and is_probably_markdown(value):
                parts.append(value.strip())
        # 有些版本可能是 markdown["texts"] / markdown["pages"]。
        for key in ("texts", "markdownTexts", "markdown_texts", "pages", "items"):
            value = markdown_obj.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and is_probably_markdown(item):
                        parts.append(item.strip())
                    elif isinstance(item, dict):
                        parts.extend(_extract_markdown_text_from_markdown_obj(item))
    return parts


def _extract_from_ocr_results_as_plain_text(data: Any) -> list[str]:
    """PP-OCRv5 等没有 Markdown 时的兜底：提取识别文本，组合为普通 Markdown。"""
    parts: list[str] = []
    for d in iter_dicts(data):
        for key in ("ocrResults", "ocr_results", "recResults", "rec_results"):
            value = d.get(key)
            if isinstance(value, list):
                lines: list[str] = []
                for item in value:
                    if isinstance(item, dict):
                        for text_key in ("text", "recText", "rec_text", "recognizedText", "recognized_text"):
                            text = item.get(text_key)
                            if isinstance(text, str) and text.strip() and not is_http_url(text):
                                lines.append(text.strip())
                                break
                if lines:
                    parts.append("\n".join(lines))
    return parts


def extract_markdown_parts_from_data(data: Any, _depth: int = 0) -> list[str]:
    """
    从 PaddleOCR 异步 API 的普通 JSON / JSONL / raw.json 包装结构中提取 Markdown。

    重点兼容官方异步示例：
    JSONL 每行结构约为 {"result": {"layoutParsingResults": [{"markdown": {"text": "..."}}]}}
    """
    if _depth > 5:
        return []

    parts: list[str] = []

    if isinstance(data, str):
        if text_looks_like_json_or_jsonl(data):
            parsed = parse_json_or_jsonl_text(data)
            if parsed is not data:
                return extract_markdown_parts_from_data(parsed, _depth + 1)
        if is_probably_markdown(data):
            return [data.strip()]
        return []

    if isinstance(data, list):
        for item in data:
            parts.extend(extract_markdown_parts_from_data(item, _depth + 1))
        return parts

    if not isinstance(data, dict):
        return []

    # 先处理常见包装字段。raw.json 中经常会把 JSONL 放在 resultJsonText 里。
    for key in ("resultJson", "resultJsonText", "jsonl", "jsonlText", "jsonText", "result", "data", "output"):
        value = data.get(key)
        if value is not None:
            parts.extend(extract_markdown_parts_from_data(value, _depth + 1))

    # 官方结构：layoutParsingResults[*].markdown.text。
    for key in ("layoutParsingResults", "layout_parsing_results", "pageResults", "page_results", "pages", "results"):
        value = data.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    if "markdown" in item:
                        parts.extend(_extract_markdown_text_from_markdown_obj(item.get("markdown")))
                    parts.extend(extract_markdown_parts_from_data(item, _depth + 1))

    # 直接 markdown 字段。
    if "markdown" in data:
        parts.extend(_extract_markdown_text_from_markdown_obj(data.get("markdown")))

    # 常见直接字段。
    for key in ("markdownText", "markdown_text", "md", "content"):
        value = data.get(key)
        if isinstance(value, str) and is_probably_markdown(value):
            parts.append(value.strip())

    # 如果没有 Markdown，尝试把 OCR 纯文本拼起来。
    if not parts:
        parts.extend(_extract_from_ocr_results_as_plain_text(data))

    return parts


def join_markdown_parts(parts: list[str]) -> str:
    clean: list[str] = []
    seen: set[str] = set()
    for part in parts:
        part = (part or "").strip()
        if not part:
            continue
        # 递归提取时同一页的 markdown 可能被命中两次；这里做精确去重。
        if part in seen:
            continue
        clean.append(part)
        seen.add(part)
    return "\n\n---\n\n".join(clean).strip()


def extract_markdown_from_json_data(data: Any) -> str:
    return join_markdown_parts(extract_markdown_parts_from_data(data))


def output_md_name_for_json(json_path: Path) -> str:
    name = json_path.name
    lowered = name.lower()
    for suffix in (".raw.json", ".jsonl", ".json"):
        if lowered.endswith(suffix):
            return name[: -len(suffix)] + ".md"
    return json_path.stem + ".md"


def repair_json_file_to_markdown(json_path: Path, output_dir: Path) -> Path:
    payload = read_json_or_jsonl_file(json_path)
    markdown = extract_markdown_from_json_data(payload)
    if not markdown:
        raise RuntimeError(
            "没有从该 JSON/JSONL 中提取到 Markdown。"
            "请确认它是 PaddleOCR 返回的 jsonUrl 文件，或程序生成的 .raw.json 文件。"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / output_md_name_for_json(json_path)
    out_path.write_text(markdown.strip() + "\n", encoding="utf-8")
    return out_path


def collect_urls_by_key(data: Any, keywords: tuple[str, ...]) -> list[str]:
    urls: list[str] = []
    for d in iter_dicts(data):
        for key, value in d.items():
            lk = str(key).lower()
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                if any(word in lk for word in keywords):
                    urls.append(value)
    return list(dict.fromkeys(urls))


def save_result_resources(
    done_payload: dict[str, Any],
    output_md_path: Path,
    raw_json_path: Path,
    request_timeout: float,
) -> tuple[str, dict[str, Any]]:
    job = done_payload.get("data") if isinstance(done_payload.get("data"), dict) else {}
    result_url = job.get("resultUrl") if isinstance(job.get("resultUrl"), dict) else {}

    raw_data: dict[str, Any] = {"jobStatus": done_payload}
    markdown = ""

    markdown_url = result_url.get("markdownUrl") or result_url.get("mdUrl")
    json_url = result_url.get("jsonUrl")

    # 官方异步接口的 jsonUrl 对 PaddleOCR-VL / PP-StructureV3 常返回 JSONL：一行一个 JSON。
    # 关键字段通常是 result.layoutParsingResults[*].markdown.text。
    if json_url:
        try:
            json_text = download_text_url(json_url, request_timeout)
            raw_data["resultJsonText"] = json_text
            raw_data["resultJsonParsed"] = parse_json_or_jsonl_text(json_text)
        except Exception as e:
            raw_data["jsonDownloadError"] = str(e)

    if markdown_url:
        try:
            markdown_text = download_text_url(markdown_url, request_timeout).strip()
            raw_data["markdownUrlTextHead"] = markdown_text[:1000]
            # 有些返回虽然叫 markdownUrl，但内容仍可能是 JSON/JSONL；先判断再写。
            if markdown_text and not text_looks_like_json_or_jsonl(markdown_text):
                markdown = markdown_text
            elif markdown_text:
                raw_data["markdownUrlParsed"] = parse_json_or_jsonl_text(markdown_text)
        except Exception as e:
            raw_data["markdownDownloadError"] = str(e)

    if not markdown:
        markdown = extract_markdown_from_json_data(raw_data)

    if not markdown:
        markdown = (
            "<!-- 未能从接口返回结果中直接提取 Markdown。下面写入原始 JSON，便于排查字段结构。 -->\n\n"
            "```json\n"
            + json.dumps(raw_data, ensure_ascii=False, indent=2)
            + "\n```\n"
        )

    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text(markdown.strip() + "\n", encoding="utf-8")
    raw_json_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown, raw_data


def process_one_pdf_async(
    pdf_path: Path,
    output_md_path: Path,
    output_root: Path,
    token: str,
    model_name: str,
    base_url: str,
    request_timeout: float,
    poll_timeout: float,
    poll_interval: float,
    overwrite: bool,
    stop_checker,
    progress_callback,
    log_callback,
    manual_query_event: Optional[threading.Event] = None,
) -> tuple[str, dict[str, Any]]:
    job_cache_path = get_job_cache_path(output_root, pdf_path)
    raw_json_path = output_md_path.with_suffix(".raw.json")
    batch_id = f"batch-{datetime.now():%Y%m%d-%H%M%S}-{file_identity_key(pdf_path)}"

    job_id = ""
    if job_cache_path.exists() and not overwrite:
        try:
            cached = json.loads(job_cache_path.read_text(encoding="utf-8"))
            job_id = str(cached.get("jobId") or "")
            if job_id:
                log_callback(f"发现已保存 jobId，继续查询：{job_id}")
        except Exception:
            job_id = ""

    if not job_id:
        submitted = submit_document_job_with_retry(
            pdf_path=pdf_path,
            token=token,
            model_name=model_name,
            batch_id=batch_id,
            base_url=base_url,
            request_timeout=request_timeout,
            stop_checker=stop_checker,
            log_callback=log_callback,
        )
        data = submitted.get("data") if isinstance(submitted.get("data"), dict) else {}
        job_id = str(data.get("jobId") or "")
        if not job_id:
            raise PaddleOCRAPIError(f"提交任务后未返回 jobId：{submitted}", payload=submitted)
        job_cache_path.write_text(
            json.dumps(
                {
                    "pdf": str(pdf_path),
                    "output": str(output_md_path),
                    "jobId": job_id,
                    "batchId": batch_id,
                    "model": model_name,
                    "baseUrl": base_url,
                    "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log_callback(f"任务提交成功，jobId：{job_id}")

    try:
        done_payload = poll_job_until_done(
            job_id=job_id,
            token=token,
            base_url=base_url,
            request_timeout=request_timeout,
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
            stop_checker=stop_checker,
            progress_callback=progress_callback,
            log_callback=log_callback,
            manual_query_event=manual_query_event,
        )
    except PaddleOCRAPIError as e:
        # job 过期或不存在时，删除缓存重新提交一次。
        if e.code in {11001, 11002} and job_cache_path.exists():
            log_callback(f"旧 jobId 已失效，删除缓存并重新提交：{job_id}")
            try:
                job_cache_path.unlink()
            except Exception:
                pass
            return process_one_pdf_async(
                pdf_path=pdf_path,
                output_md_path=output_md_path,
                output_root=output_root,
                token=token,
                model_name=model_name,
                base_url=base_url,
                request_timeout=request_timeout,
                poll_timeout=poll_timeout,
                poll_interval=poll_interval,
                overwrite=overwrite,
                stop_checker=stop_checker,
                progress_callback=progress_callback,
                log_callback=log_callback,
                manual_query_event=manual_query_event,
            )
        raise

    return save_result_resources(done_payload, output_md_path, raw_json_path, request_timeout)


class PaddleOCRBatchGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME}｜{APP_VERSION}")
        self._set_adaptive_window_size()

        self.config = load_config()
        if self.config.model not in MODEL_CHOICES:
            self.config.model = DEFAULT_MODEL
        self.log_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.check_thread: Optional[threading.Thread] = None
        self.repair_thread: Optional[threading.Thread] = None
        self.stop_requested = False
        self.manual_query_event = threading.Event()

        self.input_var = tk.StringVar(value=self.config.input_dir)
        self.output_var = tk.StringVar(value=self.config.output_dir)
        self.model_var = tk.StringVar(value=self.config.model or DEFAULT_MODEL)
        self.recursive_var = tk.BooleanVar(value=self.config.recursive)
        self.preserve_var = tk.BooleanVar(value=self.config.preserve_subfolders)
        self.overwrite_var = tk.BooleanVar(value=self.config.overwrite)
        self.token_state_var = tk.StringVar(value=self.token_state_text())
        self.status_var = tk.StringVar(value="准备就绪。")
        self.file_progress_var = tk.DoubleVar(value=0)
        self.page_progress_var = tk.DoubleVar(value=0)
        self.page_progress_text_var = tk.StringVar(value="当前文件页数进度：未开始")

        self._build_ui()
        self.root.after(100, self._poll_log_queue)

        if not self.config.token:
            self.root.after(300, self.ask_token_if_missing)

    def _set_adaptive_window_size(self) -> None:
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            width = min(max(int(sw * 0.72), 980), 1320)
            height = min(max(int(sh * 0.76), 720), 920)
            x = max((sw - width) // 2, 0)
            y = max((sh - height) // 2, 0)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            self.root.geometry("1080x760")
        self.root.minsize(900, 650)

    def token_state_text(self) -> str:
        return "已保存 Access Token/API Key" if self.config.token else "尚未保存 Access Token/API Key"

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        top = ttk.LabelFrame(self.root, text="1. 选择项目文件夹")
        top.grid(row=0, column=0, sticky="ew", **pad)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="PDF输入文件夹：").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(top, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(top, text="选择…", command=self.choose_input_dir).grid(row=0, column=2, padx=8, pady=8)

        ttk.Label(top, text="Markdown输出文件夹：").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(top, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(top, text="选择…", command=self.choose_output_dir).grid(row=1, column=2, padx=8, pady=8)

        opts = ttk.LabelFrame(self.root, text="2. 设置")
        opts.grid(row=1, column=0, sticky="ew", **pad)
        opts.columnconfigure(0, weight=1)

        options_row = ttk.Frame(opts)
        options_row.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 0))
        options_row.columnconfigure(5, weight=1)
        ttk.Label(options_row, text="模型：").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.model_combo = ttk.Combobox(
            options_row, textvariable=self.model_var, values=MODEL_CHOICES, state="readonly", width=22
        )
        self.model_combo.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Checkbutton(options_row, text="递归处理子文件夹", variable=self.recursive_var).grid(
            row=0, column=2, sticky="w", padx=10, pady=4
        )
        ttk.Checkbutton(options_row, text="输出时保留子文件夹结构", variable=self.preserve_var).grid(
            row=0, column=3, sticky="w", padx=10, pady=4
        )
        ttk.Checkbutton(options_row, text="覆盖已存在 .md", variable=self.overwrite_var).grid(
            row=0, column=4, sticky="w", padx=10, pady=4
        )

        token_row = ttk.Frame(opts)
        token_row.grid(row=1, column=0, sticky="ew", padx=6, pady=2)
        token_row.columnconfigure(0, weight=1)
        ttk.Label(token_row, textvariable=self.token_state_var).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Button(token_row, text="输入/更新 Access Token", command=self.set_token).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(token_row, text="检测 API Key 是否有效", command=self.check_api_key).grid(row=0, column=2, padx=4, pady=4)
        ttk.Button(token_row, text="清除已保存 Token", command=self.clear_token).grid(row=0, column=3, padx=4, pady=4)

        utility_row = ttk.Frame(opts)
        utility_row.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))
        ttk.Button(utility_row, text="扫描PDF数量", command=self.scan_pdfs).pack(side="left", padx=4, pady=4)
        ttk.Button(utility_row, text="修复JSON为MD", command=self.repair_json_to_md).pack(side="left", padx=4, pady=4)
        ttk.Button(utility_row, text="打开输出文件夹", command=self.open_output_dir).pack(side="left", padx=4, pady=4)
        ttk.Button(utility_row, text="显示脚本位置", command=self.show_script_path).pack(side="left", padx=4, pady=4)
        ttk.Button(utility_row, text="显示配置位置", command=self.show_config_path).pack(side="left", padx=4, pady=4)

        run_box = ttk.LabelFrame(self.root, text="3. 批处理")
        run_box.grid(row=2, column=0, sticky="ew", **pad)
        run_box.columnconfigure(0, weight=1)

        ttk.Label(run_box, text="文件总进度：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 0))
        self.file_progress = ttk.Progressbar(run_box, mode="determinate", maximum=100, variable=self.file_progress_var)
        self.file_progress.grid(row=1, column=0, sticky="ew", padx=8, pady=6)

        ttk.Label(run_box, textvariable=self.page_progress_text_var).grid(row=2, column=0, sticky="w", padx=8, pady=(8, 0))
        self.page_progress = ttk.Progressbar(run_box, mode="determinate", maximum=100, variable=self.page_progress_var)
        self.page_progress.grid(row=3, column=0, sticky="ew", padx=8, pady=6)

        self.status_label = ttk.Label(run_box, textvariable=self.status_var, wraplength=900)
        self.status_label.grid(row=4, column=0, sticky="ew", padx=8, pady=(8, 2))

        action_row = ttk.Frame(run_box)
        action_row.grid(row=5, column=0, sticky="ew", padx=8, pady=(2, 8))
        action_row.columnconfigure(0, weight=1)
        self.manual_query_btn = ttk.Button(
            action_row, text="手动查询当前结果", command=self.manual_query_current_result, state="disabled"
        )
        self.manual_query_btn.grid(row=0, column=1, sticky="e", padx=(8, 4))
        self.stop_btn = tk.Button(
            action_row,
            text="停止转换",
            command=self.request_stop,
            state="disabled",
            bg="#c62828",
            fg="white",
            activebackground="#b71c1c",
            activeforeground="white",
            disabledforeground="#f4f4f4",
            relief="raised",
            padx=14,
            pady=3,
            font="TkDefaultFont",
        )
        self.stop_btn.grid(row=0, column=2, sticky="e", padx=4)
        self.start_btn = ttk.Button(action_row, text="开始批量转换", command=self.start_batch)
        self.start_btn.grid(row=0, column=3, sticky="e", padx=(4, 0))

        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.grid(row=3, column=0, sticky="nsew", **pad)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap="word", height=18, font="TkTextFont")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        yscroll.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        self.log_text.configure(yscrollcommand=yscroll.set)

        self.root.bind("<Configure>", self._on_resize)
        self.log("程序已启动。第一次运行请先输入 Access Token/API Key。")
        self.log(f"当前程序版本：{APP_VERSION}")
        self.log(f"脚本位置：{SCRIPT_PATH}")
        self.log(f"配置文件位置：{CONFIG_PATH}")
        self.log("提示：超过 50MB 的 PDF 会自动拆分、逐段 OCR，并合并为一个同名 .md 和 .json。")
        self.log("提示：运行中可点击“手动查询当前结果”，立即查询当前 OCR 任务状态。")
        self.log("提示：如果已经生成 .raw.json 或下载了 jsonUrl，可用“修复JSON为MD”重新提取 Markdown。")

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget == self.root:
            try:
                wrap = max(int(self.root.winfo_width()) - 240, 500)
                self.status_label.configure(wraplength=wrap)
            except Exception:
                pass

    def ask_token_if_missing(self) -> None:
        if not self.config.token:
            self.set_token()

    def set_token(self) -> None:
        value = simpledialog.askstring(
            "Access Token/API Key",
            "请输入 PaddleOCR official API 的 Access Token/API Key：\n\n"
            "这里会把它保存到本机用户配置文件，之后不用重复输入。",
            show="*",
            parent=self.root,
        )
        if value:
            self.config.token = value.strip()
            self.token_state_var.set(self.token_state_text())
            self.save_current_config()
            self.log("已保存 Access Token/API Key。")

    def clear_token(self) -> None:
        if messagebox.askyesno("确认", "确定清除已保存的 Access Token/API Key 吗？", parent=self.root):
            self.config.token = ""
            self.token_state_var.set(self.token_state_text())
            self.save_current_config()
            self.log("已清除 Access Token/API Key。")

    def check_api_key(self) -> None:
        self.save_current_config()
        if not self.config.token:
            self.set_token()
        if not self.config.token:
            messagebox.showerror("缺少 Token", "未输入 Access Token/API Key。", parent=self.root)
            return
        if self.check_thread and self.check_thread.is_alive():
            messagebox.showwarning("正在检测", "当前已经有 API Key 检测任务在运行。", parent=self.root)
            return
        self.status_var.set("正在检测 API Key 是否有效……")
        self.log("开始检测 API Key 是否有效。")
        self.check_thread = threading.Thread(target=self._check_api_key_worker, daemon=True)
        self.check_thread.start()

    def _check_api_key_worker(self) -> None:
        ok, msg, payload = validate_access_token(self.config.token, self.config.base_url)
        self.log_queue.put(("keycheck", {"ok": ok, "msg": msg, "payload": payload}))

    def repair_json_to_md(self) -> None:
        if self.repair_thread and self.repair_thread.is_alive():
            messagebox.showwarning("正在修复", "当前已经有 JSON 修复任务在运行。", parent=self.root)
            return
        initial = self.output_var.get() or self.input_var.get() or str(Path.home() / "Desktop")
        paths = filedialog.askopenfilenames(
            title="选择要修复的 PaddleOCR JSON/JSONL 文件",
            initialdir=initial,
            filetypes=[
                ("JSON / JSONL", "*.json *.jsonl"),
                ("Raw JSON", "*.raw.json"),
                ("All files", "*.*"),
            ],
            parent=self.root,
        )
        if not paths:
            return
        out_dir = filedialog.askdirectory(
            title="选择修复后的 Markdown 输出文件夹",
            initialdir=self.output_var.get() or str(Path(paths[0]).parent),
            parent=self.root,
        )
        if not out_dir:
            return
        self.status_var.set("正在修复 JSON 为 Markdown……")
        self.log(f"开始修复 {len(paths)} 个 JSON/JSONL 文件为 Markdown。")
        self.repair_thread = threading.Thread(
            target=self._repair_json_worker,
            args=([Path(p) for p in paths], Path(out_dir)),
            daemon=True,
        )
        self.repair_thread.start()

    def _repair_json_worker(self, paths: list[Path], output_dir: Path) -> None:
        ok = 0
        failed = 0
        outputs: list[str] = []
        for path in paths:
            try:
                out_path = repair_json_file_to_markdown(path, output_dir)
                ok += 1
                outputs.append(str(out_path))
                self.log_queue.put(("log", f"修复完成：{path} -> {out_path}"))
            except Exception as e:
                failed += 1
                self.log_queue.put(("log", f"修复失败：{path}\n{e}"))
                try:
                    err_path = output_dir / f"{path.stem}.repair_error.txt"
                    err_path.write_text(traceback.format_exc(), encoding="utf-8")
                except Exception:
                    pass
        summary = f"JSON修复结束：成功 {ok}，失败 {failed}。输出目录：{output_dir}"
        self.log_queue.put(("repair_done", {"summary": summary, "outputs": outputs}))

    def show_script_path(self) -> None:
        msg = f"当前正在运行的脚本位置：\n{SCRIPT_PATH}\n\n版本：{APP_VERSION}"
        self.log(msg)
        messagebox.showinfo("脚本位置", msg, parent=self.root)

    def show_config_path(self) -> None:
        msg = f"配置文件位置：\n{CONFIG_PATH}"
        self.log(msg)
        messagebox.showinfo("配置位置", msg, parent=self.root)

    def choose_input_dir(self) -> None:
        initial = self.input_var.get() or str(Path.home() / "Desktop")
        path = filedialog.askdirectory(title="选择PDF输入文件夹", initialdir=initial)
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                self.output_var.set(str(Path(path) / "_markdown_output"))
            self.save_current_config()

    def choose_output_dir(self) -> None:
        initial = self.output_var.get() or self.input_var.get() or str(Path.home() / "Desktop")
        path = filedialog.askdirectory(title="选择Markdown输出文件夹", initialdir=initial)
        if path:
            self.output_var.set(path)
            self.save_current_config()

    def open_output_dir(self) -> None:
        path = Path(self.output_var.get().strip() or str(Path.home()))
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            messagebox.showinfo("输出文件夹", str(path), parent=self.root)

    def save_current_config(self) -> None:
        self.config.input_dir = self.input_var.get().strip()
        self.config.output_dir = self.output_var.get().strip()
        self.config.model = self.model_var.get().strip() or DEFAULT_MODEL
        self.config.recursive = bool(self.recursive_var.get())
        self.config.preserve_subfolders = bool(self.preserve_var.get())
        self.config.overwrite = bool(self.overwrite_var.get())
        if not self.config.base_url:
            self.config.base_url = DEFAULT_BASE_URL
        save_config(self.config)

    def validate_paths(self) -> tuple[Path, Path]:
        input_dir = Path(self.input_var.get().strip())
        output_dir = Path(self.output_var.get().strip())
        if not input_dir.exists() or not input_dir.is_dir():
            raise ValueError("请选择有效的 PDF 输入文件夹。")
        if not str(output_dir):
            raise ValueError("请选择 Markdown 输出文件夹。")
        output_dir.mkdir(parents=True, exist_ok=True)
        return input_dir, output_dir

    def scan_pdfs(self) -> None:
        try:
            input_dir, _ = self.validate_paths()
            pdfs = find_pdf_files(input_dir, self.recursive_var.get())
            oversized = [(pdf, get_file_size_mb(pdf)) for pdf in pdfs if get_file_size_mb(pdf) > MAX_LOCAL_UPLOAD_MB]
            self.log(
                f"扫描完成：发现 {len(pdfs)} 个 PDF；其中超过 50MB、将自动拆分 {len(oversized)} 个。"
            )
            if oversized:
                lines = ["下列 PDF 将自动拆分后 OCR：", ""]
                lines.extend(f"- {pdf}（{size:.2f}MB）" for pdf, size in oversized)
                messagebox.showinfo("扫描完成", "\n".join(lines), parent=self.root)
            else:
                messagebox.showinfo("扫描完成", f"发现 {len(pdfs)} 个 PDF，无需拆分。", parent=self.root)
        except Exception as e:
            messagebox.showerror("扫描失败", str(e), parent=self.root)

    def start_batch(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("正在运行", "当前已有批处理任务在运行。", parent=self.root)
            return

        self.save_current_config()
        if not self.config.token:
            self.set_token()
            if not self.config.token:
                messagebox.showerror("缺少 Token", "未输入 Access Token/API Key，无法调用在线 API。", parent=self.root)
                return

        try:
            input_dir, output_dir = self.validate_paths()
        except Exception as e:
            messagebox.showerror("路径错误", str(e), parent=self.root)
            return

        pdfs = find_pdf_files(input_dir, self.recursive_var.get())
        if not pdfs:
            messagebox.showwarning("没有PDF", "输入文件夹中没有找到 PDF 文件。", parent=self.root)
            return

        oversized = [(pdf, get_file_size_mb(pdf)) for pdf in pdfs if get_file_size_mb(pdf) > MAX_LOCAL_UPLOAD_MB]
        if oversized and (PdfReader is None or PdfWriter is None):
            messagebox.showerror(
                "缺少自动拆分组件",
                "检测到超过 50MB 的 PDF，但环境中没有 pypdf。\n"
                "请重新运行启动 bat，或执行：python -m pip install --upgrade pypdf",
                parent=self.root,
            )
            return

        msg = (
            f"即将处理 {len(pdfs)} 个 PDF。\n"
            f"其中超过 50MB、将自动拆分：{len(oversized)} 个。\n\n"
            f"输入：{input_dir}\n"
            f"输出：{output_dir}\n"
            f"模型：{self.model_var.get()}\n\n"
            "大文件将按页拆分为约 45MB 的分段，逐段 OCR 后合并为一个 .md 和一个 .json。是否继续？"
        )
        if not messagebox.askyesno("确认开始", msg, parent=self.root):
            return

        self.stop_requested = False
        self.manual_query_event.clear()
        self.start_btn.config(state="disabled")
        self.manual_query_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self.file_progress.config(maximum=len(pdfs), value=0)
        self.file_progress_var.set(0)
        self.page_progress_var.set(0)
        self.page_progress_text_var.set("当前文件页数进度：未开始")
        self.status_var.set("批处理开始。")

        args = (
            pdfs, input_dir, output_dir, self.config.token, self.model_var.get(),
            self.config.base_url or DEFAULT_BASE_URL, self.preserve_var.get(), self.overwrite_var.get(),
            self.config.request_timeout, self.config.poll_timeout, self.config.poll_interval,
        )
        self.worker_thread = threading.Thread(target=self._worker, args=args, daemon=True)
        self.worker_thread.start()

    def manual_query_current_result(self) -> None:
        if not (self.worker_thread and self.worker_thread.is_alive()):
            messagebox.showwarning("没有运行中的任务", "当前没有正在运行的 OCR 批处理任务。", parent=self.root)
            return
        self.manual_query_event.set()
        self.log("已手动触发一次查询：将跳过等待时间，立即查询当前任务状态。")
        self.status_var.set("已触发手动查询，等待接口返回。")

    def request_stop(self) -> None:
        if not (self.worker_thread and self.worker_thread.is_alive()):
            return
        confirmed = messagebox.askyesno(
            "确认停止转换",
            "确定要停止当前批量转换吗？\n\n"
            "程序会尽快停止提交和查询；已经提交到 PaddleOCR 服务器的任务无法从本程序中撤销，"
            "但已保存的 jobId 可供下次继续查询。",
            parent=self.root,
            icon="warning",
        )
        if not confirmed:
            self.log("已取消停止操作，任务继续运行。")
            return
        self.stop_requested = True
        self.log("已确认停止：正在安全退出当前批处理。")
        self.status_var.set("已请求停止，正在尝试安全退出。")
        try:
            self.manual_query_btn.config(state="disabled")
            self.stop_btn.config(state="disabled")
        except Exception:
            pass

    def _worker(
        self,
        pdfs: list[Path],
        input_dir: Path,
        output_dir: Path,
        token: str,
        model_name: str,
        base_url: str,
        preserve_subfolders: bool,
        overwrite: bool,
        request_timeout: float,
        poll_timeout: float,
        poll_interval: float,
    ) -> None:
        start_time = datetime.now()
        ok = 0
        skipped = 0
        failed = 0
        split_count = 0
        existing: set[Path] = set()
        log_path = output_dir / LOG_FILE_NAME

        def write_log_line(line: str) -> None:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

        def log_callback(message: str) -> None:
            self.log_queue.put(("log", message))

        def stop_checker() -> bool:
            return bool(self.stop_requested)

        def progress_callback(state: str, done_pages: int, total_pages: int, percent: float, message: str) -> None:
            self.log_queue.put(("page_progress", (state, done_pages, total_pages, percent, message)))

        write_log_line("=" * 80)
        write_log_line(f"开始时间：{start_time:%Y-%m-%d %H:%M:%S}")
        write_log_line(f"程序版本：{APP_VERSION}")
        write_log_line(f"脚本位置：{SCRIPT_PATH}")
        write_log_line(f"输入目录：{input_dir}")
        write_log_line(f"输出目录：{output_dir}")
        write_log_line(f"模型：{model_name}")
        write_log_line(f"Base URL：{base_url}")
        write_log_line(f"PDF数量：{len(pdfs)}")

        for index, pdf in enumerate(pdfs, start=1):
            if self.stop_requested:
                self.log_queue.put(("log", "用户请求停止，批处理已中止。"))
                break

            out_path = build_output_path(pdf, input_dir, output_dir, preserve_subfolders, existing)
            self.log_queue.put(("status", f"正在处理 {index}/{len(pdfs)}：{pdf.name}"))
            self.log_queue.put(("page_progress", ("new", 0, 0, 0.0, "当前文件页数进度：等待提交")))
            self.log_queue.put(("log", f"[{index}/{len(pdfs)}] 开始：{pdf}"))

            size_mb = get_file_size_mb(pdf)
            large_final_json = out_path.with_suffix(".json")
            output_complete = out_path.exists() and out_path.stat().st_size > 0
            if size_mb > MAX_LOCAL_UPLOAD_MB:
                output_complete = output_complete and large_final_json.exists() and large_final_json.stat().st_size > 0

            if output_complete and not overwrite:
                skipped += 1
                self.log_queue.put(("log", f"跳过：输出已存在且完整 {out_path}"))
                write_log_line(f"SKIP\t{pdf}\t{out_path}\t输出已存在")
                self.log_queue.put(("file_progress", index))
                continue

            try:
                if size_mb > MAX_LOCAL_UPLOAD_MB:
                    split_count += 1
                    self.log_queue.put(("log", f"检测到大文件 {size_mb:.2f}MB，开始自动拆分：{pdf.name}"))
                    markdown, raw_data = process_split_pdf_async(
                        pdf_path=pdf, output_md_path=out_path, output_root=output_dir, token=token,
                        model_name=model_name, base_url=base_url, request_timeout=request_timeout,
                        poll_timeout=poll_timeout, poll_interval=poll_interval, overwrite=overwrite,
                        stop_checker=stop_checker, progress_callback=progress_callback,
                        log_callback=log_callback, manual_query_event=self.manual_query_event,
                    )
                    write_log_line(f"OK_SPLIT\t{pdf}\t{out_path}\t{out_path.with_suffix('.json')}")
                else:
                    markdown, raw_data = process_one_pdf_async(
                        pdf_path=pdf, output_md_path=out_path, output_root=output_dir, token=token,
                        model_name=model_name, base_url=base_url, request_timeout=request_timeout,
                        poll_timeout=poll_timeout, poll_interval=poll_interval, overwrite=overwrite,
                        stop_checker=stop_checker, progress_callback=progress_callback,
                        log_callback=log_callback, manual_query_event=self.manual_query_event,
                    )
                    write_log_line(f"OK\t{pdf}\t{out_path}")
                ok += 1
                self.log_queue.put(("log", f"完成：{out_path}"))
            except StopRequested as e:
                self.log_queue.put(("log", f"已停止：{e}"))
                write_log_line(f"STOP\t{pdf}\t{out_path}\t{e}")
                break
            except QueueFullSkipped as e:
                skipped += 1
                self.log_queue.put(("log", f"跳过：{pdf}\n{e}"))
                write_log_line(f"SKIP_QUEUE_FULL\t{pdf}\t{out_path}\t{e}")
            except Exception as e:
                failed += 1
                err = "".join(traceback.format_exception_only(type(e), e)).strip()
                self.log_queue.put(("log", f"失败：{pdf}\n{err}"))
                write_log_line(f"FAIL\t{pdf}\t{out_path}\t{err}")
                err_path = out_path.with_suffix(".error.txt")
                try:
                    err_path.parent.mkdir(parents=True, exist_ok=True)
                    err_path.write_text(traceback.format_exc(), encoding="utf-8")
                except Exception:
                    pass

            self.log_queue.put(("file_progress", index))

        end_time = datetime.now()
        elapsed = end_time - start_time
        summary = (
            f"批处理结束：成功 {ok}，跳过 {skipped}，失败 {failed}，"
            f"自动拆分大文件 {split_count} 个，耗时 {elapsed}。日志：{log_path}"
        )
        write_log_line(f"结束时间：{end_time:%Y-%m-%d %H:%M:%S}")
        write_log_line(summary)
        self.log_queue.put(("done", summary))

    def _poll_log_queue(self) -> None:
        try:
            while True:
                typ, payload = self.log_queue.get_nowait()
                if typ == "log":
                    self.log(str(payload))
                elif typ == "status":
                    self.status_var.set(str(payload))
                elif typ == "file_progress":
                    self.file_progress_var.set(float(payload))
                elif typ == "page_progress":
                    state, done_pages, total_pages, percent, message = payload
                    if total_pages and total_pages > 0:
                        self.page_progress.config(mode="determinate", maximum=100)
                        self.page_progress_var.set(float(percent))
                        self.page_progress_text_var.set(f"当前文件页数进度：{done_pages}/{total_pages} 页，{percent:.2f}%")
                    elif state in {"pending", "new"}:
                        self.page_progress.config(mode="determinate", maximum=100)
                        self.page_progress_var.set(0)
                        self.page_progress_text_var.set(f"当前文件页数进度：{message}")
                    elif state == "done":
                        self.page_progress.config(mode="determinate", maximum=100)
                        self.page_progress_var.set(100)
                        self.page_progress_text_var.set("当前文件页数进度：100.00%")
                    else:
                        self.page_progress_text_var.set(f"当前文件页数进度：{message}")
                elif typ == "keycheck":
                    ok = bool(payload.get("ok"))
                    msg = str(payload.get("msg"))
                    self.log(msg)
                    self.status_var.set(msg)
                    if ok:
                        messagebox.showinfo("API Key 检测", msg, parent=self.root)
                    else:
                        messagebox.showerror("API Key 检测", msg, parent=self.root)
                elif typ == "repair_done":
                    summary = str(payload.get("summary"))
                    self.log(summary)
                    self.status_var.set(summary)
                    messagebox.showinfo("JSON修复完成", summary, parent=self.root)
                elif typ == "done":
                    self.log(str(payload))
                    self.status_var.set(str(payload))
                    self.start_btn.config(state="normal")
                    self.manual_query_btn.config(state="disabled")
                    self.stop_btn.config(state="disabled")
                    messagebox.showinfo("完成", str(payload), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {message}\n")
        self.log_text.see("end")
        self.root.update_idletasks()


def main() -> None:
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass

    selected_font = configure_unicode_ui_fonts(root)
    app = PaddleOCRBatchGUI(root)
    app.log(f"界面字体：{selected_font}")
    root.mainloop()


if __name__ == "__main__":
    main()
