"""Tk controls and worker coordination for the literature workspace."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import ttk

from ui_i18n import ChoiceVar, LocalizedVar, filedialog, localize_widgets, messagebox, tr, ui_text
from responsive_ui import AdaptiveLabel, ResponsiveForm

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
        canvas.itemconfigure(window, width=max(canvas.winfo_width(), content.winfo_reqwidth()))
        canvas.configure(scrollregion=canvas.bbox("all"))
        if content.winfo_reqwidth() > canvas.winfo_width():
            horizontal.grid()
        else:
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
        self.provider = ChoiceVar(value=next((name for name, url in PROVIDERS.items()
                                                if url and url == self.url.get()), tr('自定义 OpenAI compatible')))
        selector = ttk.Combobox(self.form, textvariable=self.provider, values=[ui_text(value) for value in PROVIDERS], state="readonly")
        selector.localized_choices = True
        self.form.add(tr('服务商预设'), selector)
        selector.bind("<<ComboboxSelected>>", self.preset)
        for row, label, variable, hidden in ((1, "Base URL", self.url, False), (2, "API Key", self.key, True)):
            self.form.add(label, ttk.Entry(self.form, textvariable=variable, show="*" if hidden else ""))
        self.combo = ttk.Combobox(self.form, textvariable=self.model)
        self.form.add(tr('模型 / 接入点 ID'), self.combo)
        actions = ttk.Frame(self.box, style="Paper.TFrame")
        actions.grid(row=1, column=0, sticky="w", pady=8)
        ttk.Button(actions, text=tr('拉取模型'), command=lambda: self.request(False)).pack(side="left", padx=3)
        ttk.Button(actions, text=tr('测试接口'), command=lambda: self.request(True)).pack(side="left", padx=3)
        AdaptiveLabel(self.box, text=tr('兼容 /chat/completions；不支持 /models 的服务可手填模型或接入点 ID。'),
                      style="Hint.TLabel").grid(row=2, column=0, sticky="ew", pady=4)

    def preset(self, _event=None):
        value = PROVIDERS[self.provider.get()]
        if value:
            if value != self.url.get():
                self.key.set("")
            self.url.set(value)
            self.model.set("")
            self.combo.configure(values=())

    def profile(self):
        return ModelProfile(self.url.get().strip(), self.key.get().strip(), self.model.get().strip())

    def request(self, testing):
        profile = self.profile()
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
        self.snapshot = None
        self.cancel_event = threading.Event()
        saved = app.config.literature if isinstance(app.config.literature, dict) else {}
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
        self.upload = tk.BooleanVar(value=saved.get("upload", False))
        self.repository = tk.StringVar(value=saved.get("repository", ""))
        self.branch = tk.StringVar(value=saved.get("branch", "main"))
        self.folder = tk.StringVar(value=saved.get("folder", ""))
        # Session-only token. Reuse a normal local GitHub binding when available.
        self.github_token = tk.StringVar(value=os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", "")))
        self.status = LocalizedVar(value=tr('选择 Markdown 文件夹后开始。'))
        self.profiles = {}
        self._build(saved, fetch, test)
        for variable in (self.input, self.output, self.same_folder):
            variable.trace_add("write", lambda *_: self.app.workspace_layout.sync_output())
        self.app.root.after(100, self.poll)

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
                "repository": self.repository.get(), "branch": self.branch.get(), "folder": self.folder.get()}
        data.update({key: asdict(value.profile()) for key, value in self.profiles.items()})
        return data

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def make_snapshot(self, translating=True):
        profiles = {key: value.profile() for key, value in self.profiles.items()}
        if translating:
            required = ["translator"]
            if self.secondary.get():
                required.append("reviewer")
                if self.arbitration.get() == "大模型裁决":
                    required.append("arbiter")
            if self.proofreading.get():
                required.append("proofreader")
            for key in required:
                profiles[key].validate()
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
                    self.secondary.get(), self.proofreading.get(), self.arbitration.get()),
                "output": None if self.same_folder.get() else Path(self.output.get()).expanduser().resolve(),
                "prefix": self.prefix.get().startswith("前缀"), "github": github,
                "auto_translate": self.auto_translate.get()}

    def input_paths(self):
        if not self.input.get().strip() or not Path(self.input.get()).is_dir():
            raise ValueError(tr('请选择有效的 Markdown 输入文件夹。'))
        root = Path(self.input.get()).expanduser().resolve()
        output = None if self.same_folder.get() or not self.output.get().strip() else Path(self.output.get()).expanduser().resolve()
        return root, find_markdown_files(root, self.recursive.get(), output)

    def scan(self):
        try:
            _, paths = self.input_paths()
            messagebox.showinfo(tr('扫描完成'), tr('发现 {arg0} 个待检测的 Markdown 文件。', arg0=len(paths)), parent=self.app.root)
        except Exception as exc:
            messagebox.showerror(tr('扫描失败'), str(exc), parent=self.app.root)

    def start(self):
        if self.busy() or (self.app.worker_thread and self.app.worker_thread.is_alive()):
            messagebox.showwarning(tr('正在运行'), tr('请等待当前 OCR / 翻译任务完成。'), parent=self.app.root)
            return
        try:
            root, paths = self.input_paths()
            snapshot = self.make_snapshot()
            self.app.save_current_config()
            if not paths:
                raise ValueError(tr('没有发现待处理的 .md 文件。'))
        except Exception as exc:
            messagebox.showerror(tr('无法开始翻译'), str(exc), parent=self.app.root)
            return
        self.cancel_event.clear()
        self.app.stop_requested = False
        self.app.file_progress_var.set(0)
        self.app.workspace_layout.translation_stop.configure(state="normal")
        self.start_button.configure(state="disabled")
        self.app.start_btn.configure(state="disabled")
        self.thread = threading.Thread(target=self.worker, args=(root, paths, snapshot), daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel_event.set()
        if self.app.worker_thread and self.app.worker_thread.is_alive():
            self.app.stop_requested = True
        self.status.set(tr('已请求停止；等待当前 API 请求返回后退出。'))

    def stopped(self):
        return self.cancel_event.is_set() or self.app.stop_requested

    def log(self, text):
        self.app.log_queue.put(("log", text))

    def decide(self, payload):
        response = queue.Queue(maxsize=1)
        self.events.put(("decision", (payload, response)))
        while not self.stopped():
            try:
                return response.get(timeout=0.2)
            except queue.Empty:
                continue
        raise ProcessingCancelled(tr('用户已停止。'))

    def maybe_upload(self, path, root, verified, snapshot, expected_hash=None):
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
            **snapshot["profiles"], decide=self.decide, stop=self.stopped, log=self.log)
        labels = {"verified": tr('核验通过'), "needs_review": tr('发现问题，待人工处理'), "unverified": tr('未启用质量检查'),
                  "target_language": tr('已是目标语言，跳过'), "existing": tr('译文已存在，跳过')}
        self.log(tr('{arg0}：{arg1}', arg0=path.name, arg1=labels[result['status']]))
        self.events.put(("status", tr('{arg0}：{arg1}', arg0=path.name, arg1=labels[result['status']])))
        if result["status"] in {"verified", "needs_review", "unverified"}:
            upload_root = root if snapshot["output"] is None else snapshot["output"]
            self.maybe_upload(destination, upload_root, result["verified"] and upstream_ok, snapshot, result["outputSHA256"])
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
            def warning(value):
                if isinstance(value, dict):
                    return bool(value.get("qualityWarning")) or any(warning(v) for v in value.values())
                return isinstance(value, list) and any(warning(v) for v in value)
            self.process(path, root, snapshot, upstream_ok=not warning(raw_data))

    def worker(self, root, paths, snapshot):
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
                    result = self.process(path, root, snapshot)
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

    def decision_dialog(self, payload, response):
        if self.stopped():
            response.put("unresolved")
            return
        dialog = tk.Toplevel(self.app.root)
        dialog.localized_title = tr('翻译争议裁决：{arg0} 第 {arg1} 段', arg0=payload['filename'], arg1=payload['chunk'])
        dialog.title(dialog.localized_title)
        dialog.geometry("860x600")
        dialog.minsize(480, 360)
        dialog.rowconfigure(1, weight=1)
        dialog.columnconfigure(0, weight=1)
        ttk.Label(dialog, text=tr('请对照原文与两份译文；只有确认所选译文无误时才接受。'), wraplength=450).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        notebook = ttk.Notebook(dialog)
        notebook.grid(row=1, column=0, sticky="nsew", padx=8)
        for title, text in ((tr('原文'), payload["source"]), (tr('首次译文'), payload["first"]), (tr('二次译文'), payload["second"]),
                            (tr('核对报告'), json.dumps(payload["comparison"], ensure_ascii=False, indent=2))):
            frame = ttk.Frame(notebook)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            body = tk.Text(frame, wrap="word")
            body.insert("1.0", text)
            body.configure(state="disabled")
            body.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(frame, command=body.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            body.configure(yscrollcommand=scrollbar.set)
            notebook.add(frame, text=title)
        actions = ttk.Frame(dialog)
        actions.grid(row=2, column=0, sticky="ew", padx=8, pady=6)
        def choose(value):
            response.put(value)
            dialog.destroy()
        for label, value in ((tr('接受首次译文'), "first"), (tr('接受二次译文'), "second"), (tr('保留首次译文，标记待处理'), "unresolved")):
            ttk.Button(actions, text=label, command=lambda v=value: choose(v)).pack(side="left", padx=3)
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("unresolved"))
        def close_if_stopped():
            if not dialog.winfo_exists():
                return
            if self.stopped():
                choose("unresolved")
            else:
                dialog.after(200, close_if_stopped)
        dialog.after(200, close_if_stopped)
        localize_widgets(dialog)

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
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
                    messagebox.showinfo(tr('文献处理'), payload, parent=self.app.root)
                elif kind == "profile_result":
                    controls, testing, result, error, requested = payload
                    if controls.profile() != requested:
                        continue
                    if error:
                        messagebox.showerror(tr('模型接口'), error, parent=self.app.root)
                    elif testing:
                        messagebox.showinfo(tr('接口测试通过'), result, parent=self.app.root)
                    else:
                        controls.combo.configure(values=result)
                        if controls.model.get() not in result:
                            controls.model.set(result[0])
                        self.log(tr('已拉取 {arg0} 个模型。', arg0=len(result)))
        except queue.Empty:
            pass
        self.app.root.after(100, self.poll)
