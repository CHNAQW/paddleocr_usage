"""Tk controls and worker coordination for the literature workspace."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import tkinter as tk
from task_runtime import drain_events

from dataclasses import asdict
from pathlib import Path
from tkinter import ttk

from ui_i18n import ChoiceVar, LocalizedVar, copy_text, filedialog, localize_widgets, messagebox, tr, ui_text
from responsive_ui import AdaptiveCheckbutton, AdaptiveLabel, ButtonToolbar, ResponsiveForm
from model_budget import DEFAULT_CONTEXT_LIMIT, ModelLimits, positive_integer

from literature_processing import (
    PROVIDERS, LANGUAGES, GitHubOptions, ModelProfile, ProcessingCancelled,
    TranslationOptions, find_markdown_files, ocr_verified, translate_document,
    translated_path, upload_verified_file, chat,
)


def scrollable_page(notebook, title):
    outer = ttk.Frame(notebook)
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)
    canvas = tk.Canvas(outer, highlightthickness=0, width=400, height=200,
                       background=ttk.Style().lookup("TFrame", "background"))
    canvas.grid(row=0, column=0, sticky="nsew")
    vertical = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(outer, orient="horizontal", command=canvas.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    content = ttk.Frame(canvas)
    content.columnconfigure(0, weight=1)
    window = canvas.create_window((0, 0), window=content, anchor="nw")

    def resize(_event=None):
        canvas.itemconfigure(window, width=max(1, canvas.winfo_width()))
        canvas.configure(scrollregion=canvas.bbox("all"))
        horizontal.grid_remove()
    content.bind("<Configure>", resize)
    canvas.bind("<Configure>", resize)

    def wheel(event):
        widget = event.widget
        while widget is not None and widget != outer:
            if isinstance(widget, (tk.Text, ttk.Combobox)):
                return
            widget = getattr(widget, "master", None)
        if widget == outer:
            delta = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
            canvas.yview_scroll(delta * 3, "units")
    # Add to the root bind tag; do not replace platform/default wheel handlers.
    outer.winfo_toplevel().bind("<MouseWheel>", wheel, add="+")
    outer.winfo_toplevel().bind("<Button-4>", wheel, add="+")
    outer.winfo_toplevel().bind("<Button-5>", wheel, add="+")
    notebook.add(outer, text=tr(title))
    return content


class ModelControls:
    def __init__(self, parent, title, saved, events, fetch, test):
        self.events, self.fetch, self.test = events, fetch, test
        self.box = ttk.Frame(parent, style="Paper.TFrame", padding=16)
        self.box.columnconfigure(0, weight=1)
        self.form = ResponsiveForm(self.box)
        self.form.grid(row=0, column=0, sticky="ew")
        saved = saved if isinstance(saved, dict) else {}
        self.url = tk.StringVar(value=saved.get("base_url", PROVIDERS["DeepSeek"]))
        self.key = tk.StringVar(value=saved.get("api_key", ""))
        self.model = tk.StringVar(value=saved.get("model", ""))
        self.manual_limit = tk.BooleanVar(value=saved.get("manual_limit", False))
        self.limit_value = tk.StringVar(value=str(saved.get("input_limit") or DEFAULT_CONTEXT_LIMIT))
        self.catalog_limits = {}
        detected = saved.get("detected_limits", {})
        if isinstance(detected, dict) and (detected.get("input_limit") or detected.get("context_limit")):
            self.catalog_limits[(self.url.get().strip(), self.model.get().strip())] = ModelLimits(
                *(positive_integer(detected.get(key)) for key in ("input_limit", "context_limit", "output_limit")))
        self.provider = ChoiceVar(value=next((name for name, url in PROVIDERS.items()
                                                if url and url == self.url.get()), tr('自定义 OpenAI compatible')))
        selector = ttk.Combobox(self.form, textvariable=self.provider, values=[ui_text(value) for value in PROVIDERS], state="readonly")
        self.provider_selector = selector
        selector.localized_choices = True
        self.form.add(tr('服务商预设'), selector)
        selector.bind("<<ComboboxSelected>>", self.preset)
        for row, label, variable, hidden in ((1, "Base URL", self.url, False), (2, "API Key", self.key, True)):
            entry = ttk.Entry(self.form, textvariable=variable, show="*" if hidden else "")
            self.form.add(label, entry)
            setattr(self, "key_entry" if hidden else "url_entry", entry)
        self.combo = ttk.Combobox(self.form, textvariable=self.model)
        self.form.add(tr('模型 / 接入点 ID'), self.combo)
        self.limit_entry = ttk.Entry(self.form, textvariable=self.limit_value)
        self.form.add(tr("输入上限（tokens）"), self.limit_entry)
        self.limit_status = LocalizedVar(master=self.box)
        actions = ButtonToolbar(self.box, ((tr('拉取模型'), lambda: self.request(False)),
                                           (tr('测试接口'), lambda: self.request(True))))
        actions.grid(row=1, column=0, sticky="ew", pady=8)
        AdaptiveLabel(self.box, text=tr('兼容 /chat/completions；不支持 /models 的服务可手填模型或接入点 ID。'),
                      style="Hint.TLabel").grid(row=2, column=0, sticky="ew", pady=4)
        AdaptiveCheckbutton(self.box, text=tr("手动设置输入上限"), variable=self.manual_limit,
                        command=self.refresh_limits).grid(row=3, column=0, sticky="ew")
        AdaptiveLabel(self.box, textvariable=self.limit_status, style="Hint.TLabel").grid(row=4, column=0, sticky="ew", pady=4)
        for variable in (self.url, self.model):
            variable.trace_add("write", self.identity_changed)
        self.refresh_limits()

    def identity_changed(self, *_):
        # A manual override belongs to the chosen endpoint/model, never a new one.
        self.manual_limit.set(False)
        self.refresh_limits()

    def refresh_limits(self):
        detected = self.catalog_limits.get((self.url.get().strip(), self.model.get().strip()))
        if not self.manual_limit.get():
            self.limit_value.set(str((detected.input_limit or detected.context_limit) if detected else DEFAULT_CONTEXT_LIMIT))
        self.limit_entry.configure(state="normal" if self.manual_limit.get() else "disabled")
        source = tr("手动设置") if self.manual_limit.get() else tr("接口元数据") if detected else tr("DeepSeek-V4.1-Flash 默认值")
        self.limit_status.set(tr("上限来源：{arg0}。未返回限制时使用 1,000,000 上下文 / 256,000 输出的默认值；可手动修改。", arg0=source))

    def config_data(self):
        data = asdict(self.profile())
        detected = self.catalog_limits.get((self.url.get().strip(), self.model.get().strip()))
        data.update(manual_limit=self.manual_limit.get(), detected_limits=asdict(detected) if detected else {})
        return data

    def preset(self, _event=None):
        value = PROVIDERS[self.provider.get()]
        if value:
            if value != self.url.get():
                self.key.set("")
            self.url.set(value)
            self.model.set("")
            self.combo.configure(values=())

    def profile(self):
        detected = self.catalog_limits.get((self.url.get().strip(), self.model.get().strip()))
        limits = detected or ModelLimits(limit_source="fallback")
        if self.manual_limit.get():
            value = positive_integer(self.limit_value.get().strip())
            if not value:
                raise ValueError(tr("模型 token 上限须为正整数。"))
            limits = ModelLimits(value, limits.context_limit, limits.output_limit, "manual")
        return ModelProfile(self.url.get().strip(), self.key.get().strip(), self.model.get().strip(), **asdict(limits))

    def request(self, testing):
        try:
            profile = self.profile()
        except ValueError as exc:
            messagebox.showerror(tr('配置不完整'), str(exc), parent=self.box)
            return
        if not profile.api_key or not profile.base_url:
            messagebox.showerror(tr('配置不完整'), tr('请填写 Base URL 和 API Key。'), parent=self.box)
            return
        def worker():
            try:
                result = chat(profile, "只回复 OK。", {}) if testing else self.fetch(profile.base_url, profile.api_key)
                self.events.put(("profile_result", (self, testing, result, None, profile)))
            except Exception as exc:
                self.events.put(("profile_result", (self, testing, None, str(exc), profile)))
        threading.Thread(target=worker, daemon=True).start()


class LiteratureControls:
    def __init__(self, app, page, fetch, test):
        self.app, self.page = app, page
        self.events = queue.Queue()
        self.thread = None
        self.closed = False
        self.pending = None
        self.snapshot = None
        self.cancel_event = threading.Event()
        saved = app.config.literature if isinstance(app.config.literature, dict) else {}
        self.formatting = None
        self.formatting_saved = saved.get("formatting", {})
        self.fetch, self.test = fetch, test
        shared = saved.get("llm_service", {})
        shared = shared if isinstance(shared, dict) else {}
        existing = next((saved[key] for key in ("translator", "reviewer", "proofreader", "arbiter")
                         if isinstance(saved.get(key), dict) and saved[key].get("api_key") and saved[key].get("base_url")), {})
        self.shared_llm = tk.BooleanVar(value=shared.get("enabled", False))
        self.shared_url = tk.StringVar(value=shared.get("base_url", existing.get("base_url") or app.config.llm_base_url or PROVIDERS["DeepSeek"]))
        self.shared_key = tk.StringVar(value=shared.get("api_key", existing.get("api_key") or (app.config.llm_api_key if app.config.llm_base_url else "")))
        self.shared_provider = ChoiceVar(value=next((name for name, url in PROVIDERS.items()
                                                   if url and url == self.shared_url.get()), "自定义 OpenAI compatible"))
        self.auto_translate = tk.BooleanVar(value=saved.get("auto_translate", False))
        self.input = tk.StringVar(value=saved.get("input", ""))
        self.output = tk.StringVar(value=saved.get("output", ""))
        self.same_folder = tk.BooleanVar(value=saved.get("same_folder", True))
        self.recursive = tk.BooleanVar(value=saved.get("recursive", True))
        self.prefix = ChoiceVar(value=saved.get("filename_position", "后缀 _TRANSLATED"))
        self.source = ChoiceVar(value=saved.get("source", "自动检测"))
        self.target = ChoiceVar(value=saved.get("target", "简体中文 (ch)"))
        self.secondary = tk.BooleanVar(value=saved.get("secondary", False))
        self.proofreading = tk.BooleanVar(value=saved.get("proofreading", False))
        self.arbitration = ChoiceVar(value=saved.get("arbitration", "用户自行裁决"))
        self.allow_arbiter_revision = tk.BooleanVar(value=saved.get("allow_arbiter_revision", False))
        self.force_auto = tk.BooleanVar(value=saved.get("force_auto") is True)
        self.input_percent = tk.StringVar(value=str(saved.get("input_percent", 50)))
        self.upload = tk.BooleanVar(value=saved.get("upload", False))
        self.upload_kind = ChoiceVar(value=saved.get("upload_kind", "同时上传"))
        self.upload_root = tk.StringVar(value=saved.get("upload_root", ""))
        self.repository = tk.StringVar(value=saved.get("repository", ""))
        self.branch = tk.StringVar(value=saved.get("branch", "main"))
        self.folder = tk.StringVar(value=saved.get("folder", ""))
        # Session-only token. Reuse a normal local GitHub binding when available.
        self.github_token = tk.StringVar(value=os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", "")))
        self.status = LocalizedVar(value=tr('选择 Markdown 文件夹后开始。'))
        self.profiles = {}
        self._build(saved, fetch, test)
        for variable in (self.shared_llm, self.shared_url, self.shared_key):
            variable.trace_add("write", self.sync_llm_service)
        self.sync_llm_service()
        for variable in (self.input, self.output, self.same_folder):
            variable.trace_add("write", lambda *_: self.app.workspace_layout.sync_output())
        self.force_auto.trace_add("write", self.sync_automatic)
        self.sync_automatic()
        self.pending = self.app.root.after(100, self.poll)
        self.app.root.bind("<Destroy>", self.cleanup, add="+")

    def sync_automatic(self, *_):
        if self.force_auto.get():
            self.proofreading.set(True)
            self.arbitration.set("大模型裁决")
            self.allow_arbiter_revision.set(True)

    def _build(self, saved, fetch, test):
        from workspace_ui import build_translation_page
        build_translation_page(self, saved, fetch, test)

    def choose_dir(self, variable):
        if variable is self.output and self.same_folder.get():
            if not messagebox.askyesno(tr('覆盖译文位置设置'), tr('您已选择“译文保存在原文文件夹”，是否需要强制覆盖设置？'),
                                       parent=self.app.root):
                return
        directory = filedialog.askdirectory(title=tr("选择文件夹"), initialdir=variable.get() or self.input.get() or None,
                                             parent=self.app.root)
        if directory:
            if variable is self.output:
                self.same_folder.set(False)
            variable.set(directory)
            self.app.workspace_layout.sync_output()

    def config_data(self):
        data = {"auto_translate": self.auto_translate.get(), "input": self.input.get(), "output": self.output.get(),
                "same_folder": self.same_folder.get(), "recursive": self.recursive.get(), "filename_position": self.prefix.get(),
                "source": self.source.get(), "target": self.target.get(), "secondary": self.secondary.get(),
                "proofreading": self.proofreading.get(), "arbitration": self.arbitration.get(), "upload": self.upload.get(),
                "allow_arbiter_revision": self.allow_arbiter_revision.get(), "force_auto": self.force_auto.get(),
                "repository": self.repository.get(), "branch": self.branch.get(), "folder": self.folder.get(),
                "upload_kind": self.upload_kind.get(), "upload_root": self.upload_root.get()}
        data["input_percent"] = self.chunk_percent()
        data["updates"] = self.app.updates.config_data()
        data["formatting"] = self.formatting.config_data() if self.formatting else self.formatting_saved
        data["llm_service"] = {"enabled": self.shared_llm.get(), "base_url": self.shared_url.get(), "api_key": self.shared_key.get()}
        data.update({key: value.config_data() for key, value in self.profiles.items()})
        return data

    def chunk_percent(self):
        value = self.input_percent.get().strip()
        if not value.isascii() or not value.isdecimal() or not 50 <= int(value) <= 80:
            raise ValueError(tr("分段比例须为 50%–80% 的整数。"))
        return int(value)

    def busy(self):
        manual = getattr(self.app, "manual_check_thread", None)
        return bool(self.thread and self.thread.is_alive()) or bool(manual and manual.is_alive()) or bool(getattr(self, "formatting", None) and self.formatting.busy)

    def open_formatting(self):
        if self.formatting is None:
            self.formatting = MarkdownFormatting(self)
            self.sync_llm_service()
        self.formatting.window.deiconify()
        self.formatting.window.lift()

    def shared_preset(self, _event=None):
        value = PROVIDERS[self.shared_provider.get()]
        if value and value != self.shared_url.get():
            self.shared_key.set("")
            self.shared_url.set(value)

    def sync_llm_service(self, *_):
        enabled = self.shared_llm.get()
        if not _ or _[0] != str(self.shared_key):
            self.shared_provider.set(next((name for name, url in PROVIDERS.items() if url and url == self.shared_url.get()), "自定义 OpenAI compatible"))
        models = list(self.profiles.values())
        if self.formatting:
            models += list(self.formatting.models.values())
        for model in models:
            if enabled:
                if model.url.get() != self.shared_url.get():
                    model.url.set(self.shared_url.get())
                model.key.set(self.shared_key.get())
                model.provider.set(next((name for name, url in PROVIDERS.items() if url and url == self.shared_url.get()), "自定义 OpenAI compatible"))
            model.provider_selector.configure(state="disabled" if enabled else "readonly")
            for entry in (model.url_entry, model.key_entry):
                entry.configure(state="disabled" if enabled else "normal")
            for widget in (model.provider_selector, model.url_entry, model.key_entry):
                if not getattr(widget, "_shared_override_bound", False):
                    widget.bind("<Button-1>", self.override_shared_llm, add="+")
                    widget._shared_override_bound = True
        if enabled:
            self.app.llm_base_url_var.set(self.shared_url.get())
            self.app.llm_api_key_var.set(self.shared_key.get())
        for entry in (self.app.shared_review_url_entry, self.app.shared_review_key_entry):
            entry.configure(state="disabled" if enabled else "normal")
            if not getattr(entry, "_shared_override_bound", False):
                entry.bind("<Button-1>", self.override_shared_llm, add="+")
                entry._shared_override_bound = True

    def override_shared_llm(self, event):
        if not self.shared_llm.get():
            return
        if not messagebox.askyesno(tr("覆盖统一 LLM 设置"),
                tr("您已选择“所有服务共用一个LLM服务商”，是否需要强制覆盖设置？"), parent=event.widget.winfo_toplevel()):
            return "break"
        self.shared_llm.set(False)
        event.widget.focus_set()

    def make_snapshot(self, translating=True):
        profiles = {key: value.profile() for key, value in self.profiles.items()}
        if translating:
            required = ["translator"]
            if self.secondary.get():
                required.append("reviewer")
            if self.proofreading.get():
                required.append("proofreader")
            if (self.secondary.get() or self.proofreading.get()) and self.arbitration.get() == "大模型裁决":
                required.append("arbiter")
            for key in required:
                try:
                    profiles[key].validate()
                except ValueError as exc:
                    role = tr({"translator": "翻译", "reviewer": "二次核对", "proofreader": "校对", "arbiter": "裁决"}[key])
                    raise ValueError(tr("{arg0}模型配置不完整：{arg1}", arg0=role, arg1=exc)) from None
            if not self.target.get().strip():
                raise ValueError(tr('请选择目标语言。'))
        github = None
        if self.upload.get():
            github = GitHubOptions(self.repository.get().strip(), self.github_token.get().strip(),
                                   self.branch.get().strip(), self.folder.get().strip())
            try:
                github.validate()
            except ValueError as exc:
                raise ValueError(tr("请先通过“偏好设置 → GitHub 上传”的向导完成上传设置：{arg0}", arg0=exc.args[0])) from None
        if translating and not self.same_folder.get() and not self.output.get().strip():
            raise ValueError(tr('请选择译文输出文件夹，或勾选输出到原文文件夹。'))
        return {"profiles": profiles, "options": TranslationOptions(self.target.get().strip(), self.source.get().strip() or "自动检测",
                    self.secondary.get(), self.proofreading.get(), self.arbitration.get(), self.chunk_percent(),
                    allow_arbiter_revision=self.allow_arbiter_revision.get(), force_auto=self.force_auto.get()),
                "output": None if self.same_folder.get() else Path(self.output.get()).expanduser().resolve(),
                "prefix": self.prefix.get().startswith("前缀"), "github": github,
                "auto_translate": self.auto_translate.get(), "upload_kind": self.upload_kind.get(), "force_auto": self.force_auto.get()}

    def input_paths(self, settings=None):
        source, recursive, target = settings if settings is not None else self.path_settings()
        if not source or not Path(source).is_dir():
            raise ValueError(tr('请选择有效的 Markdown 输入文件夹。'))
        root = Path(source).expanduser().resolve()
        output = Path(target).expanduser().resolve() if target else None
        return root, find_markdown_files(root, recursive, output)

    def path_settings(self):
        return self.input.get().strip(), self.recursive.get(), None if self.same_folder.get() else self.output.get().strip()

    def scan(self):
        settings = self.path_settings()
        self.status.set(tr("正在后台扫描或检查文件……"))
        def finished(result):
            message = tr('发现 {arg0} 个待检测的 Markdown 文件。', arg0=len(result[1]))
            self.status.set(message)
            self.log(message)
        self.app.run_background("md_scan", lambda: self.input_paths(settings), finished)

    def start(self):
        if self.busy() or (self.app.worker_thread and self.app.worker_thread.is_alive()):
            messagebox.showwarning(tr('正在运行'), tr('请等待当前 OCR / 翻译任务完成。'), parent=self.app.root)
            return
        try:
            settings = self.path_settings()
            snapshot = self.make_snapshot()
            self.app.save_current_config()
        except Exception as exc:
            messagebox.showerror(tr('无法开始翻译'), str(exc), parent=self.app.root)
            return
        self.cancel_event.clear()
        self.app.stop_requested = False
        self.app.file_progress_var.set(0)
        self.app.workspace_layout.translation_stop.configure(state="normal")
        self.start_button.configure(state="disabled")
        self.app.start_btn.configure(state="disabled")
        def worker():
            try:
                root, paths = self.input_paths(settings)
                if not paths:
                    raise ValueError(tr('没有发现待处理的 .md 文件。'))
                self.worker(root, paths, snapshot)
            except Exception as exc:
                self.events.put(("done", tr("后台任务失败：{arg0}", arg0=exc)))
        self.active_snapshot = snapshot
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel_event.set()
        if getattr(self, "formatting", None):
            self.formatting.cancel.set()
        if self.app.worker_thread and self.app.worker_thread.is_alive():
            self.app.stop_requested = True
        self.status.set(tr('已请求停止；正在结束等待，不再处理后续文件。'))

    def stopped(self):
        return getattr(self, "closed", False) or self.cancel_event.is_set() or self.app.stop_requested

    def log(self, text):
        self.app.log_queue.put(("log", text))

    def decide(self, payload, stop=None):
        stopped = stop or self.stopped
        response = queue.Queue(maxsize=1)
        self.events.put(("decision", (payload, response, stopped)))
        while not stopped():
            try:
                return response.get(timeout=0.2)
            except queue.Empty:
                continue
        raise ProcessingCancelled(tr('用户已停止。'))

    def run_with_issue_dialog(self, path, work, stop=None, automatic=False):
        stopped = stop or self.stopped
        attempts = 0
        while not stopped():
            attempts += 1
            try:
                return work()
            except ProcessingCancelled:
                raise
            except Exception as exc:
                if automatic:
                    self.log(tr("全自动处理失败：{arg0}；尝试 {arg1}/2；{arg2}", arg0=path.name, arg1=attempts, arg2=exc))
                    if attempts < 2:
                        continue
                    raise
                try:
                    source = path.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError):
                    source = ""
                choice = self.decide({"filename": path.name, "source": source, "first": None, "problem": str(exc)}, stopped)
                if choice != "retry":
                    raise
        raise ProcessingCancelled(tr("用户已停止。"))

    def maybe_upload(self, path, root, verified, snapshot, expected_hash=None, role="original"):
        from literature_processing import upload_kind_allows
        if not upload_kind_allows(snapshot.get("upload_kind", "同时上传"), role):
            return
        if not snapshot["github"]:
            return
        if not verified:
            self.log(tr('未上传（尚未核验通过）：{arg0}', arg0=path.name))
            return
        try:
            remote = upload_verified_file(path, path.relative_to(root).as_posix(), True, snapshot["github"],
                expected_hash or hashlib.sha256(path.read_bytes()).hexdigest(), self.stopped)
            self.log(tr('GitHub 上传成功：{arg0}', arg0=remote))
        except ProcessingCancelled:
            raise
        except Exception as exc:
            self.log(tr('GitHub 未上传，文件已保留本地：{arg0}；{arg1}', arg0=path.name, arg1=exc))

    def process(self, path, root, snapshot, upstream_ok=True):
        destination = translated_path(path, root, snapshot["output"], snapshot["prefix"])
        result = translate_document(path, destination, snapshot["options"],
            **snapshot["profiles"], decide=None if snapshot.get("force_auto") else self.decide, stop=self.stopped, log=self.log)
        labels = {"verified": tr('核验通过'), "needs_review": tr('核验尚未通过，请查看检查报告'), "unverified": tr('未启用质量检查'),
                  "target_language": tr('已是目标语言，跳过'), "existing": tr('译文已存在，跳过')}
        if result["status"] == "needs_review":
            reasons = result.get("pendingReasons", [])
            if reasons == ["proofreading_problem"]:
                labels["needs_review"] = tr("文本校对尚未通过，请查看检查报告")
            elif reasons == ["translation_dispute_unresolved"]:
                labels["needs_review"] = tr("翻译分歧尚未解决，请查看检查报告")
        self.log(tr('{arg0}：{arg1}', arg0=path.name, arg1=labels[result['status']]))
        self.events.put(("status", tr('{arg0}：{arg1}', arg0=path.name, arg1=labels[result['status']])))
        if result["status"] in {"verified", "needs_review", "unverified"}:
            result["upstreamVerified"] = upstream_ok
            destination.with_suffix(".translation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            upload_root = root if snapshot["output"] is None else snapshot["output"]
            self.maybe_upload(destination, upload_root, result["verified"] and upstream_ok, snapshot, result["outputSHA256"], role="translation")
        return result

    def after_ocr(self, path, root, raw_data, reviewed_markdown=None):
        snapshot = self.snapshot
        if not snapshot:
            return
        if self.stopped():
            raise ProcessingCancelled(tr('用户已停止。'))
        expected = None
        if reviewed_markdown is not None:
            # Compare normalized text because the legacy OCR writer uses Windows newlines.
            if path.read_text(encoding="utf-8").strip() != reviewed_markdown.strip():
                self.log(tr('OCR 核验后文件已改变，禁止上传：{arg0}', arg0=path.name))
                return
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
        self.maybe_upload(path, root, ocr_verified(raw_data), snapshot, expected)
        if snapshot["auto_translate"]:
            self.log(tr("OCR 后自动翻译沿用共用的翻译、核对和裁决设置。"))
            def warning(value):
                if isinstance(value, dict):
                    return bool(value.get("qualityWarning")) or any(warning(v) for v in value.values())
                return isinstance(value, list) and any(warning(v) for v in value)
            self.run_with_issue_dialog(path, lambda: self.process(path, root, snapshot, upstream_ok=not warning(raw_data)), automatic=snapshot.get("force_auto", False))

    def worker(self, root, paths, snapshot):
        self.active_snapshot = snapshot
        counts = {"verified": 0, "needs_review": 0, "unverified": 0, "target_language": 0, "existing": 0, "failed": 0}
        stopped = False
        try:
            for index, path in enumerate(paths, 1):
                if self.stopped():
                    stopped = True
                    break
                self.events.put(("status", tr('正在处理 {arg0}/{arg1}：{arg2}', arg0=index, arg1=len(paths), arg2=path.name)))
                self.events.put(("progress", (index - 1, len(paths))))
                try:
                    result = self.run_with_issue_dialog(path, lambda: self.process(path, root, snapshot), automatic=snapshot.get("force_auto", False))
                    counts[result["status"]] += 1
                except ProcessingCancelled:
                    stopped = True
                    break
                except Exception as exc:
                    counts["failed"] += 1
                    self.log(tr('文献处理失败：{arg0}；{arg1}', arg0=path.name, arg1=exc))
                self.events.put(("progress", (index, len(paths))))
        finally:
            summary = (tr('翻译{arg0}：核验通过 {arg1}，待处理 {arg2}，未核验 {arg3}，目标语言跳过 {arg4}，已有译文跳过 {arg5}，失败 {arg6}。', arg0=tr('已停止') if stopped else tr('完成'), arg1=counts['verified'], arg2=counts['needs_review'], arg3=counts['unverified'], arg4=counts['target_language'], arg5=counts['existing'], arg6=counts['failed']))
            self.events.put(("done", summary))

    def decision_dialog(self, payload, response, stop=None):
        from responsive_ui import ButtonToolbar
        stopped = stop or self.stopped
        if stopped():
            response.put("unresolved")
            return
        dialog = tk.Toplevel(self.app.root)
        dialog.localized_title = tr("处理问题：{arg0}", arg0=payload["filename"])
        dialog.title(dialog.localized_title)
        dialog.geometry("860x600")
        dialog.minsize(480, 360)
        dialog.rowconfigure(1, weight=1)
        dialog.columnconfigure(0, weight=1)
        problem = payload.get("problem", payload.get("comparison", {}))
        details = json.dumps(problem, ensure_ascii=False, indent=2) if isinstance(problem, (dict, list)) else str(problem)
        def reasons(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, list):
                return [item for child in value for item in reasons(child)]
            if isinstance(value, dict):
                return [item for key in ("contentIssues", "issues", "reviewError", "checkError", "reason", "summary",
                                        "review", "comparison", "proofreading", "arbitration", "revision", "verification", "error")
                        if key in value for item in reasons(value[key])]
            return []
        summary = "\n".join(dict.fromkeys(reasons(problem))) or details
        header = ttk.Frame(dialog, padding=12)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        AdaptiveLabel(header, text=tr("发现问题：{arg0}", arg0=summary), max_lines=3).grid(row=0, column=0, sticky="ew")
        AdaptiveLabel(header, text=tr("保留稿件会标记待处理；重试将丢弃本次生成稿，重做当前分段／文件，不删除原文。"),
                      style="Subtitle.TLabel", max_lines=2).grid(row=1, column=0, sticky="ew", pady=(8, 0))
        notebook = ttk.Notebook(dialog)
        notebook.grid(row=1, column=0, sticky="nsew", padx=12)
        drafts = [(tr("原文"), payload.get("source", ""))]
        if payload.get("first") is not None:
            drafts.append((tr("第一稿"), payload["first"]))
        if payload.get("second") is not None:
            drafts.append((tr("第二稿"), payload["second"]))
        drafts.append((tr("核对报告"), details))
        for title, text in drafts:
            frame = ttk.Frame(notebook)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            body = tk.Text(frame, wrap="word", background=ttk.Style(frame).lookup("TFrame", "background"),
                           foreground=ttk.Style(frame).lookup("TLabel", "foreground"))
            preview = str(text)
            if len(preview) > 100000:
                preview = preview[:100000] + "\n" + str(tr("预览已截短；使用复制全文查看完整内容。"))
            body.insert("1.0", preview)
            body.configure(state="disabled")
            body.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(frame, command=body.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            body.configure(yscrollcommand=scrollbar.set)
            ttk.Button(frame, text=tr("复制全文"), command=lambda value=text: copy_text(dialog, value)).grid(
                row=1, column=0, sticky="w", pady=(8, 0))
            notebook.add(frame, text=title)
        chosen = False
        timer = None
        def choose(value):
            nonlocal chosen
            if chosen:
                return
            chosen = True
            response.put(value)
            if timer:
                self.app.root.after_cancel(timer)
            dialog.destroy()
        actions = [(tr("保留第一稿"), lambda: choose("first"))] if payload.get("first") is not None else [(tr("跳过此文件"), lambda: choose("unresolved"))]
        actions.append((tr("删除并重试上一步"), lambda: choose("retry")))
        if payload.get("second") is not None:
            actions.append((tr("保留第二稿"), lambda: choose("second")))
        bar = ButtonToolbar(dialog, actions)
        bar.grid(row=2, column=0, sticky="ew", padx=12, pady=12)
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("unresolved"))
        def check_stop():
            nonlocal timer
            timer = None
            if not dialog.winfo_exists():
                return
            if stopped():
                choose("unresolved")
            else:
                timer = self.app.root.after(200, check_stop)
        timer = self.app.root.after(200, check_stop)
        localize_widgets(dialog)

    def poll(self):
        try:
            for kind, payload in drain_events(self.events):
                if kind == "decision":
                    self.decision_dialog(*payload)
                elif kind == "status":
                    self.status.set(payload)
                    self.app.status_var.set(payload)
                elif kind == "progress":
                    completed, total = payload
                    self.app.file_progress_var.set(100 * completed / total if total else 0)
                elif kind == "done":
                    self.status.set(payload)
                    self.app.status_var.set(payload)
                    self.log(payload)
                    self.start_button.configure(state="normal")
                    self.app.workspace_layout.translation_stop.configure(state="disabled")
                    self.app.start_btn.configure(state="normal")
                    if not getattr(self, "active_snapshot", {}).get("force_auto"):
                        messagebox.showinfo(tr('文献处理'), payload, parent=self.app.root)
                elif kind == "profile_result":
                    controls, testing, result, error, requested = payload
                    if not controls.box.winfo_exists():
                        continue
                    try:
                        unchanged = controls.profile() == requested
                    except ValueError:
                        unchanged = False
                    if not unchanged:
                        continue
                    if error:
                        messagebox.showerror(tr('模型接口'), error, parent=self.app.root)
                    elif testing:
                        messagebox.showinfo(tr('接口测试通过'), result, parent=self.app.root)
                    else:
                        controls.catalog_limits = {identity: limits for identity, limits in controls.catalog_limits.items()
                                                   if identity[0] != requested.base_url}
                        controls.catalog_limits.update({(requested.base_url, name): limits
                                                        for name, limits in getattr(result, "limits", {}).items()})
                        controls.combo.configure(values=result)
                        if controls.model.get() not in result:
                            controls.model.set(result[0])
                        controls.refresh_limits()
                        self.log(tr('已拉取 {arg0} 个模型。', arg0=len(result)))
        except queue.Empty:
            pass
        except Exception as exc:
            self.log(tr("后台事件处理失败：{arg0}", arg0=exc))
        if not self.closed:
            self.pending = self.app.root.after(100, self.poll)

    def cleanup(self, event):
        if event.widget != self.app.root:
            return
        self.closed = True
        self.cancel_event.set()
        if self.pending:
            self.app.root.after_cancel(self.pending)
            self.pending = None


class MarkdownFormatting:
    """A standalone single-pass formatter with a mandatory verification-only model."""
    def __init__(self, owner):
        from responsive_ui import ButtonToolbar
        self.owner, self.app = owner, owner.app
        self.root = self.app.root
        self.window = tk.Toplevel(self.root)
        self.window.title(tr("Markdown 整理与核验"))
        self.window.transient(self.root)
        self.window.minsize(540, 420)
        self.window.geometry(f"{min(820, self.root.winfo_screenwidth()-40)}x{min(800, self.root.winfo_screenheight()-60)}")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        saved = owner.formatting_saved if isinstance(owner.formatting_saved, dict) else {}
        self.input = tk.StringVar(master=self.root, value=saved.get("input", owner.input.get() or self.app.output_var.get()))
        self.output = tk.StringVar(master=self.root, value=saved.get("output", ""))
        self.same_folder = tk.BooleanVar(master=self.root, value=saved.get("same_folder", True))
        self.recursive = tk.BooleanVar(master=self.root, value=saved.get("recursive", True))
        self.prefix = ChoiceVar(master=self.root, value=saved.get("filename_position", "后缀 _FORMATTED"))
        self.status = LocalizedVar(master=self.root, value=tr("选择 Markdown 文件或文件夹，配置整理及核验模型后开始。"))
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.thread, self.busy, self.closed = None, False, False
        self.progress = tk.DoubleVar(master=self.root)
        self.models = {}
        head = ttk.Frame(self.window, padding=(16, 12))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        AdaptiveLabel(head, text=tr("Markdown 整理与核验"), style="WizardHeading.TLabel").grid(row=0, column=0, sticky="ew")
        AdaptiveLabel(head, text=tr("仅整理一次，再独立核验；保留原文，不翻译、不润色，不生成第二份整理稿。"),
                      style="Subtitle.TLabel", max_lines=2).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        notebook = ttk.Notebook(self.window, style="Workspace.TNotebook")
        notebook.grid(row=1, column=0, sticky="nsew")
        body = scrollable_page(notebook, tr("Markdown 整理"))
        files = ttk.LabelFrame(body, text=tr("文档与输出"), padding=12)
        files.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        files.columnconfigure(0, weight=1)
        form = ResponsiveForm(files)
        form.grid(row=0, column=0, sticky="ew")
        def path_row(variable, output=False):
            row = ttk.Frame(form)
            row.columnconfigure(0, weight=1)
            entry = ttk.Entry(row, textvariable=variable, width=1)
            entry.grid(row=0, column=0, sticky="ew")
            actions = ttk.Frame(row)
            actions.grid(row=0, column=1, sticky="e", padx=(6, 0))
            if not output:
                ttk.Button(actions, text=tr("选择 MD"), command=self.choose_file).pack(side="left", padx=(0, 6))
            ttk.Button(actions, text=tr("选择文件夹"), command=lambda: self.choose_folder(output)).pack(side="left")
            stacked = None
            def reflow(event):
                nonlocal stacked
                if event.widget != row:
                    return
                narrow = row.winfo_width() < actions.winfo_reqwidth() + 166
                if narrow == stacked:
                    return
                stacked = narrow
                entry.grid_configure(columnspan=2 if narrow else 1)
                actions.grid_configure(row=1 if narrow else 0, column=0 if narrow else 1,
                                       columnspan=2 if narrow else 1, padx=(0, 0) if narrow else (6, 0),
                                       pady=(4, 0) if narrow else (0, 0))
            row.bind("<Configure>", reflow, add="+")
            return row, entry
        row, self.input_entry = path_row(self.input)
        form.add(tr("Markdown 文件或文件夹"), row)
        row, self.output_entry = path_row(self.output, True)
        form.add(tr("整理稿位置"), row)
        values = ("前缀 FORMATTED_", "后缀 _FORMATTED")
        marker = ttk.Combobox(form, textvariable=self.prefix, values=[tr(v) for v in values], state="readonly")
        marker.localized_choices = values
        form.add(tr("文件名标记"), marker)
        percent = ttk.Spinbox(form, textvariable=owner.input_percent, from_=50, to=80, increment=1)
        form.add(tr("输入上限使用比例（50%–80%）"), percent)
        AdaptiveCheckbutton(files, text=tr("整理稿保存在原文件夹"), variable=self.same_folder).grid(row=1, column=0, sticky="ew", pady=4)
        AdaptiveCheckbutton(files, text=tr("包括子文件夹"), variable=self.recursive).grid(row=2, column=0, sticky="ew", pady=4)
        AdaptiveLabel(files, text=tr("与翻译共用分段比例；同时按整理和核验模型预算规划，完整代码块、公式和表格不拆开。"),
                      style="Subtitle.TLabel").grid(row=3, column=0, sticky="ew", pady=6)
        roles = ttk.Notebook(body)
        roles.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        for key, label, fallback in (("formatter", tr("整理模型"), "translator"), ("verifier", tr("核验模型（只校对）"), "proofreader")):
            tab = ttk.Frame(roles)
            tab.columnconfigure(0, weight=1)
            roles.add(tab, text=label)
            defaults = {}
            try:
                defaults = owner.profiles[fallback].config_data()
                if not defaults.get("model"):
                    defaults = owner.profiles["translator"].config_data()
            except ValueError:
                pass
            model = ModelControls(tab, label, saved.get(key, defaults), owner.events, owner.fetch, owner.test)
            model.box.grid(row=0, column=0, sticky="ew")
            self.models[key] = model
        hint = tr("核验只返回问题与结论。疑点或核验失败会保留整理稿及 .formatting.json 报告并标记待处理，不自动重新整理或上传。")
        AdaptiveLabel(body, text=hint, style="Subtitle.TLabel").grid(row=2, column=0, sticky="ew", padx=24, pady=8)
        ttk.Button(body, text=tr("统一 LLM 服务设置"), command=lambda: self.app.workspace_layout.show_settings(4)).grid(row=3, column=0, sticky="w", padx=24, pady=8)
        footer = ttk.Frame(self.window, padding=(16, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        AdaptiveLabel(footer, textvariable=self.status, max_lines=2).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Progressbar(footer, variable=self.progress, maximum=100).grid(row=1, column=0, sticky="ew")
        toolbar = ButtonToolbar(footer, ((tr("扫描 Markdown"), self.scan), (tr("开始整理并核验"), self.start),
                                        (tr("停止"), self.cancel.set)))
        toolbar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.scan_button, self.start_button, self.stop_button = toolbar.buttons
        self.traces = [(var, var.trace_add("write", self.sync_output)) for var in (self.input, self.output, self.same_folder)]
        self.sync_output()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self.cleanup, add="+")
        self.pending = self.root.after(100, self.poll)
        self.buttons()
        localize_widgets(self.window)

    def sync_output(self, *_):
        if self.same_folder.get():
            value = self.input.get().strip()
            expected = str(Path(value).parent) if value and Path(value).suffix.lower() == ".md" else value
            if self.output.get() != expected:
                self.output.set(expected)
        self.output_entry.configure(state="disabled" if self.same_folder.get() else "normal")

    def choose_file(self):
        path = filedialog.askopenfilename(parent=self.window, title=tr("选择 Markdown 文件"), filetypes=[("Markdown", "*.md *.MD")])
        if path:
            self.input.set(path)

    def choose_folder(self, output=False):
        if output and self.same_folder.get():
            if not messagebox.askyesno(tr("修改整理稿位置"), tr("已选择与原文件同目录，是否改用指定输出文件夹？"), parent=self.window):
                return
        path = filedialog.askdirectory(parent=self.window, title=tr("选择文件夹"))
        if path:
            if output:
                self.same_folder.set(False)
            (self.output if output else self.input).set(path)

    def config_data(self):
        return {"input": self.input.get(), "output": self.output.get(), "same_folder": self.same_folder.get(),
                "recursive": self.recursive.get(), "filename_position": self.prefix.get(),
                **{key: model.config_data() for key, model in self.models.items()}}

    def path_settings(self):
        return self.input.get().strip(), self.same_folder.get(), self.output.get().strip(), self.recursive.get()

    def paths(self, settings=None):
        from literature_processing import find_formatting_files
        source_value, same_folder, output_value, recursive = settings if settings is not None else self.path_settings()
        if not source_value:
            raise ValueError(tr("请选择有效的 Markdown 文件或文件夹。"))
        source = Path(source_value).expanduser().resolve()
        output = None
        if not same_folder:
            if not output_value:
                raise ValueError(tr("请选择整理稿输出文件夹。"))
            output = Path(output_value).expanduser().resolve()
            if output.exists() and not output.is_dir():
                raise ValueError(tr("请选择整理稿输出文件夹。"))
        if source.is_file() and source.suffix.lower() == ".md":
            return source.parent, [source], output
        if source.is_dir():
            return source, find_formatting_files(source, recursive, output), output
        raise ValueError(tr("请选择有效的 Markdown 文件或文件夹。"))

    def scan(self):
        settings = self.path_settings()
        self.status.set(tr("正在后台扫描或检查文件……"))
        def finished(result):
            if not self.closed:
                self.status.set(tr("发现 {arg0} 个可整理 Markdown；原文和译文均可，跳过已有整理稿。", arg0=len(result[1])))
        self.app.run_background("format_scan", lambda: self.paths(settings), finished)

    def start(self):
        from literature_processing import formatted_path, format_markdown_document
        if self.owner.busy() or (self.app.worker_thread and self.app.worker_thread.is_alive()):
            messagebox.showwarning(tr("正在运行"), tr("请等待 OCR、翻译或整理任务结束。"), parent=self.window)
            return
        try:
            settings = self.path_settings()
            models = {key: model.profile() for key, model in self.models.items()}
            for profile in models.values():
                profile.validate()
            percent, prefix = self.owner.chunk_percent(), self.prefix.get().startswith("前缀")
            automatic = self.owner.force_auto.get()
            arbiter = self.owner.profiles["arbiter"].profile() if automatic else None
            if arbiter:
                arbiter.validate()
            self.app.save_current_config()
        except Exception as exc:
            messagebox.showerror(tr("无法开始整理"), str(exc), parent=self.window)
            return
        self.cancel.clear()
        self.app.stop_requested = False
        self.busy = True
        self.progress.set(0)
        self.buttons()
        self.app.start_btn.configure(state="disabled")
        self.owner.start_button.configure(state="disabled")
        self.status.set(tr("整理与核验已开始；本次设置已固定。"))
        def worker():
            counts = {"verified": 0, "needs_review": 0, "existing": 0, "failed": 0}
            stopped = False
            try:
                root, paths, output = self.paths(settings)
                if not paths:
                    raise ValueError(tr("没有发现待整理的 Markdown。"))
                for index, path in enumerate(paths, 1):
                    if self.cancel.is_set():
                        stopped = True
                        break
                    try:
                        self.events.put(("status", tr("正在整理 {arg0}/{arg1}：{arg2}", arg0=index, arg1=len(paths), arg2=path.name)))
                        destination = formatted_path(path, root, output, prefix)
                        result = self.owner.run_with_issue_dialog(path,
                            lambda: format_markdown_document(path, destination, **models, input_percent=percent,
                                stop=self.cancel.is_set, log=self.owner.log,
                                decide=None if automatic else lambda payload: self.owner.decide(payload, self.cancel.is_set),
                                force_auto=automatic, arbiter=arbiter), self.cancel.is_set, automatic=automatic)
                        counts[result["status"]] += 1
                        label = {"verified": tr("整理核验通过"), "needs_review": tr("整理稿待核验处理"), "existing": tr("整理稿已存在，跳过")}[result["status"]]
                        self.owner.log(tr("{arg0}：{arg1}", arg0=path.name, arg1=label))
                    except ProcessingCancelled:
                        stopped = True
                        break
                    except Exception as exc:
                        counts["failed"] += 1
                        self.owner.log(tr("整理失败，原文已保留：{arg0}；{arg1}", arg0=path.name, arg1=exc))
                    self.events.put(("progress", 100 * index / len(paths)))
            except Exception as exc:
                counts["failed"] += 1
                self.owner.log(tr("后台任务失败：{arg0}", arg0=exc))
            finally:
                self.events.put(("done", (counts, stopped)))
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def buttons(self):
        for button in (self.scan_button, self.start_button):
            button.configure(state="disabled" if self.busy else "normal")
        self.stop_button.configure(state="normal" if self.busy else "disabled")

    def poll(self):
        self.pending = None
        try:
            for kind, value in drain_events(self.events):
                if kind == "status":
                    self.status.set(value)
                    self.app.status_var.set(value)
                elif kind == "progress":
                    self.progress.set(value)
                elif kind == "done":
                    self.busy = False
                    counts, stopped = value
                    message = tr("整理完成：通过 {arg0}，待处理 {arg1}，已有 {arg2}，失败 {arg3}。",
                                 arg0=counts["verified"], arg1=counts["needs_review"], arg2=counts["existing"], arg3=counts["failed"])
                    if stopped:
                        message = tr("已停止。") + " " + message
                    self.status.set(message)
                    self.app.status_var.set(message)
                    self.owner.log(message)
                    self.app.start_btn.configure(state="normal")
                    self.owner.start_button.configure(state="normal")
        except queue.Empty:
            pass
        except Exception as exc:
            self.status.set(tr("后台事件处理失败：{arg0}", arg0=exc))
        self.buttons()
        if not self.closed:
            self.pending = self.root.after(100, self.poll)

    def close(self):
        try:
            self.app.save_current_config()
        except Exception as exc:
            self.status.set(tr("无法保存整理设置：{arg0}", arg0=exc))
            return
        self.window.withdraw()

    def cleanup(self, event):
        if event.widget != self.window:
            return
        self.closed = True
        self.cancel.set()
        if self.pending:
            self.root.after_cancel(self.pending)
        for variable, token in self.traces:
            variable.trace_remove("write", token)
