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
from tkinter import filedialog, messagebox, ttk

from literature_processing import (
    PROVIDERS, LANGUAGES, GitHubOptions, ModelProfile, ProcessingCancelled,
    TranslationOptions, find_markdown_files, ocr_verified, translate_document,
    translated_path, upload_verified_file, chat,
)


def scrollable_page(notebook, title):
    outer = ttk.Frame(notebook)
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)
    canvas = tk.Canvas(outer, highlightthickness=0, width=400, height=200)
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
    notebook.add(outer, text=title)
    return content


class ModelControls:
    def __init__(self, parent, title, saved, events, fetch, test):
        self.events, self.fetch, self.test = events, fetch, test
        self.box = ttk.LabelFrame(parent, text=title)
        self.box.columnconfigure(1, weight=1)
        saved = saved if isinstance(saved, dict) else {}
        self.url = tk.StringVar(value=saved.get("base_url", PROVIDERS["DeepSeek"]))
        self.key = tk.StringVar(value=saved.get("api_key", ""))
        self.model = tk.StringVar(value=saved.get("model", ""))
        self.provider = tk.StringVar(value=next((name for name, url in PROVIDERS.items()
                                                if url and url == self.url.get()), "自定义 OpenAI compatible"))
        selector = ttk.Combobox(self.box, textvariable=self.provider, values=list(PROVIDERS), state="readonly")
        selector.grid(row=0, column=1, sticky="ew", padx=6, pady=3)
        ttk.Label(self.box, text="服务商预设").grid(row=0, column=0, padx=6)
        selector.bind("<<ComboboxSelected>>", self.preset)
        for row, label, variable, hidden in ((1, "Base URL", self.url, False), (2, "API Key", self.key, True)):
            ttk.Label(self.box, text=label).grid(row=row, column=0, sticky="w", padx=6)
            ttk.Entry(self.box, textvariable=variable, show="*" if hidden else "").grid(row=row, column=1, sticky="ew", padx=6, pady=3)
        ttk.Label(self.box, text="模型 / 接入点 ID").grid(row=3, column=0, padx=6)
        self.combo = ttk.Combobox(self.box, textvariable=self.model)
        self.combo.grid(row=3, column=1, sticky="ew", padx=6, pady=3)
        actions = ttk.Frame(self.box)
        actions.grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        ttk.Button(actions, text="拉取模型", command=lambda: self.request(False)).pack(side="left", padx=3)
        ttk.Button(actions, text="测试接口", command=lambda: self.request(True)).pack(side="left", padx=3)
        ttk.Label(self.box, text="兼容 /chat/completions；不支持 /models 的服务可手填模型或接入点 ID。",
                  wraplength=480).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=4)

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
            messagebox.showerror("配置不完整", "请填写 Base URL 和 API Key。", parent=self.box)
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
        self.prefix = tk.StringVar(value=saved.get("filename_position", "后缀 _TRANSLATED"))
        self.source = tk.StringVar(value=saved.get("source", "自动检测"))
        self.target = tk.StringVar(value=saved.get("target", "简体中文 (ch)"))
        self.secondary = tk.BooleanVar(value=saved.get("secondary", False))
        self.proofreading = tk.BooleanVar(value=saved.get("proofreading", False))
        self.arbitration = tk.StringVar(value=saved.get("arbitration", "用户自行裁决"))
        self.upload = tk.BooleanVar(value=saved.get("upload", False))
        self.repository = tk.StringVar(value=saved.get("repository", ""))
        self.branch = tk.StringVar(value=saved.get("branch", "main"))
        self.folder = tk.StringVar(value=saved.get("folder", ""))
        # Session-only token. Reuse a normal local GitHub binding when available.
        self.github_token = tk.StringVar(value=os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", "")))
        self.status = tk.StringVar(value="选择 Markdown 文件夹后开始。")
        self.profiles = {}
        self._build(saved, fetch, test)
        self.app.root.after(100, self.poll)

    def _build(self, saved, fetch, test):
        box = ttk.LabelFrame(self.page, text="1. Markdown 文献与翻译设置")
        box.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
        box.columnconfigure(1, weight=1)
        for row, label, variable in ((0, "MD 输入文件夹", self.input), (1, "译文输出文件夹", self.output)):
            ttk.Label(box, text=label).grid(row=row, column=0, padx=6)
            ttk.Entry(box, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=6, pady=4)
            ttk.Button(box, text="选择…", command=lambda v=variable: self.choose_dir(v)).grid(row=row, column=2, padx=6)
        ttk.Checkbutton(box, text="输出到原文所在文件夹", variable=self.same_folder).grid(row=2, column=0, columnspan=2, sticky="w", padx=6)
        ttk.Checkbutton(box, text="递归扫描子文件夹", variable=self.recursive).grid(row=3, column=0, columnspan=2, sticky="w", padx=6)
        for row, label, variable, values, readonly in (
            (4, "来源语言", self.source, ["自动检测"] + list(LANGUAGES), False),
            (5, "目标语言", self.target, list(LANGUAGES), False),
            (6, "译文文件名标记", self.prefix, ["前缀 TRANSLATED_", "后缀 _TRANSLATED"], True),
        ):
            ttk.Label(box, text=label).grid(row=row, column=0, padx=6, pady=4)
            ttk.Combobox(box, textvariable=variable, values=values, state="readonly" if readonly else "normal").grid(row=row, column=1, columnspan=2, sticky="ew", padx=6)
        ttk.Label(box, text="每份文献先用前 300 字符判断目标语言；语言框可手填，语言代码参考 PaddleOCR。\n已生成的 TRANSLATED 文件会排除，已有同名译文不会覆盖。",
                  wraplength=500).grid(row=7, column=0, columnspan=3, sticky="w", padx=6, pady=6)
        checks = ttk.LabelFrame(self.page, text="2. 可选质量检查")
        checks.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
        checks.columnconfigure(0, weight=1)
        ttk.Checkbutton(checks, text="二次翻译核对（独立重译，再比较两份译文）", variable=self.secondary).grid(row=0, column=0, sticky="w")
        ttk.Combobox(checks, textvariable=self.arbitration, values=["用户自行裁决", "大模型裁决"], state="readonly").grid(row=1, column=0, sticky="ew", padx=6, pady=4)
        ttk.Checkbutton(checks, text="文本校对（语句不通、缺字、漏译等）", variable=self.proofreading).grid(row=2, column=0, sticky="w")
        ttk.Label(checks, text="发现问题的译文与 JSON 检查报告仍会保存；未解决问题时禁止自动上传。", wraplength=500).grid(row=3, column=0, sticky="w", padx=6, pady=4)
        model_box = ttk.LabelFrame(self.page, text="3. 为各步骤指定模型（按需设置）")
        model_box.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        model_tabs = ttk.Notebook(model_box)
        model_tabs.pack(fill="both", expand=True)
        for key, label in (("translator", "翻译 / 语言识别"), ("reviewer", "二次翻译核对"),
                           ("proofreader", "文本校对"), ("arbiter", "大模型裁决")):
            tab = ttk.Frame(model_tabs)
            tab.columnconfigure(0, weight=1)
            model_tabs.add(tab, text=label)
            controls = ModelControls(tab, label, saved.get(key, {}), self.events, fetch, test)
            controls.box.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
            self.profiles[key] = controls
        github = ttk.LabelFrame(self.page, text="4. 核验通过后上传 GitHub（两个入口共用）")
        github.grid(row=3, column=0, sticky="ew", padx=10, pady=6)
        github.columnconfigure(1, weight=1)
        ttk.Checkbutton(github, text="自动上传核验无误的 Markdown", variable=self.upload).grid(row=0, column=0, columnspan=2, sticky="w")
        for row, label, variable in ((1, "仓库 owner/repository", self.repository), (2, "已有目标分支", self.branch),
                                      (3, "仓库内目录（可空）", self.folder), (4, "GitHub Token（仅本次运行）", self.github_token)):
            ttk.Label(github, text=label).grid(row=row, column=0, sticky="w", padx=6)
            ttk.Entry(github, textvariable=variable, show="*" if row == 4 else "").grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(github, text="Token 需目标仓库 Contents 写入权限；保留子目录，远端同名文件不覆盖。\nOCR 输出要求启用并通过 LLM 核验；译文至少启用一项检查且全部通过。",
                  wraplength=500).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=6)
        actions = ttk.Frame(self.page)
        actions.grid(row=4, column=0, sticky="ew", padx=10, pady=6)
        ttk.Button(actions, text="扫描 .md", command=self.scan).grid(row=0, column=0, padx=4)
        self.start_button = ttk.Button(actions, text="开始翻译", command=self.start, style="Accent.TButton")
        self.start_button.grid(row=0, column=1, padx=4)
        ttk.Button(actions, text="停止文献处理", command=self.stop).grid(row=0, column=2, padx=4)
        ttk.Button(actions, text="保存设置", command=self.app.save_current_config).grid(row=0, column=3, padx=4)
        ttk.Label(self.page, textvariable=self.status, wraplength=500).grid(row=5, column=0, sticky="ew", padx=10, pady=6)
        ttk.Label(self.page, text="模型 API Key 沿用本程序的本机配置保存方式（明文）；勿共享配置文件。",
                  wraplength=500).grid(row=6, column=0, sticky="w", padx=10, pady=6)

    def choose_dir(self, variable):
        directory = filedialog.askdirectory(parent=self.app.root)
        if directory:
            variable.set(directory)

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
                raise ValueError("请选择目标语言。")
        github = None
        if self.upload.get():
            github = GitHubOptions(self.repository.get().strip(), self.github_token.get().strip(),
                                   self.branch.get().strip(), self.folder.get().strip())
            github.validate()
        if translating and not self.same_folder.get() and not self.output.get().strip():
            raise ValueError("请选择译文输出文件夹，或勾选输出到原文文件夹。")
        return {"profiles": profiles, "options": TranslationOptions(self.target.get().strip(), self.source.get().strip() or "自动检测",
                    self.secondary.get(), self.proofreading.get(), self.arbitration.get()),
                "output": None if self.same_folder.get() else Path(self.output.get()).expanduser().resolve(),
                "prefix": self.prefix.get().startswith("前缀"), "github": github,
                "auto_translate": self.auto_translate.get()}

    def input_paths(self):
        if not self.input.get().strip() or not Path(self.input.get()).is_dir():
            raise ValueError("请选择有效的 Markdown 输入文件夹。")
        root = Path(self.input.get()).expanduser().resolve()
        output = None if self.same_folder.get() or not self.output.get().strip() else Path(self.output.get()).expanduser().resolve()
        return root, find_markdown_files(root, self.recursive.get(), output)

    def scan(self):
        try:
            _, paths = self.input_paths()
            messagebox.showinfo("扫描完成", f"发现 {len(paths)} 个待检测的 Markdown 文件。", parent=self.app.root)
        except Exception as exc:
            messagebox.showerror("扫描失败", str(exc), parent=self.app.root)

    def start(self):
        if self.busy() or (self.app.worker_thread and self.app.worker_thread.is_alive()):
            messagebox.showwarning("正在运行", "请等待当前 OCR / 翻译任务完成。", parent=self.app.root)
            return
        try:
            root, paths = self.input_paths()
            snapshot = self.make_snapshot()
            self.app.save_current_config()
            if not paths:
                raise ValueError("没有发现待处理的 .md 文件。")
        except Exception as exc:
            messagebox.showerror("无法开始翻译", str(exc), parent=self.app.root)
            return
        self.cancel_event.clear()
        self.app.stop_requested = False
        self.start_button.configure(state="disabled")
        self.app.start_btn.configure(state="disabled")
        self.thread = threading.Thread(target=self.worker, args=(root, paths, snapshot), daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel_event.set()
        if self.app.worker_thread and self.app.worker_thread.is_alive():
            self.app.stop_requested = True
        self.status.set("已请求停止；等待当前 API 请求返回后退出。")

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
        raise ProcessingCancelled("用户已停止。")

    def maybe_upload(self, path, root, verified, snapshot, expected_hash=None):
        if not snapshot["github"]:
            return
        if not verified:
            self.log(f"未上传（尚未核验通过）：{path.name}")
            return
        try:
            remote = upload_verified_file(path, path.relative_to(root).as_posix(), True, snapshot["github"],
                expected_hash or hashlib.sha256(path.read_bytes()).hexdigest(), self.stopped)
            self.log(f"GitHub 上传成功：{remote}")
        except ProcessingCancelled:
            raise
        except Exception as exc:
            self.log(f"GitHub 未上传，文件已保留本地：{path.name}；{exc}")

    def process(self, path, root, snapshot, upstream_ok=True):
        destination = translated_path(path, root, snapshot["output"], snapshot["prefix"])
        result = translate_document(path, destination, snapshot["options"],
            **snapshot["profiles"], decide=self.decide, stop=self.stopped, log=self.log)
        labels = {"verified": "核验通过", "needs_review": "发现问题，待人工处理", "unverified": "未启用质量检查",
                  "target_language": "已是目标语言，跳过", "existing": "译文已存在，跳过"}
        self.log(f"{path.name}：{labels[result['status']]}")
        self.events.put(("status", f"{path.name}：{labels[result['status']]}"))
        if result["status"] in {"verified", "needs_review", "unverified"}:
            upload_root = root if snapshot["output"] is None else snapshot["output"]
            self.maybe_upload(destination, upload_root, result["verified"] and upstream_ok, snapshot, result["outputSHA256"])
        return result

    def after_ocr(self, path, root, raw_data, reviewed_markdown=None):
        snapshot = self.snapshot
        if not snapshot:
            return
        if self.stopped():
            raise ProcessingCancelled("用户已停止。")
        expected = None
        if reviewed_markdown is not None:
            # Compare normalized text because the legacy OCR writer uses Windows newlines.
            if path.read_text(encoding="utf-8").strip() != reviewed_markdown.strip():
                self.log(f"OCR 核验后文件已改变，禁止上传：{path.name}")
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
                self.events.put(("status", f"正在处理 {index}/{len(paths)}：{path.name}"))
                try:
                    result = self.process(path, root, snapshot)
                    counts[result["status"]] += 1
                except ProcessingCancelled:
                    stopped = True
                    break
                except Exception as exc:
                    counts["failed"] += 1
                    self.log(f"文献处理失败：{path.name}；{exc}")
        finally:
            summary = (f"翻译{'已停止' if stopped else '完成'}：核验通过 {counts['verified']}，"
                       f"待处理 {counts['needs_review']}，未核验 {counts['unverified']}，"
                       f"目标语言跳过 {counts['target_language']}，已有译文跳过 {counts['existing']}，失败 {counts['failed']}。")
            self.events.put(("done", summary))

    def decision_dialog(self, payload, response):
        if self.stopped():
            response.put("unresolved")
            return
        dialog = tk.Toplevel(self.app.root)
        dialog.title(f"翻译争议裁决：{payload['filename']} 第 {payload['chunk']} 段")
        dialog.geometry("860x600")
        dialog.minsize(480, 360)
        dialog.rowconfigure(1, weight=1)
        dialog.columnconfigure(0, weight=1)
        ttk.Label(dialog, text="请对照原文与两份译文；只有确认所选译文无误时才接受。", wraplength=450).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        notebook = ttk.Notebook(dialog)
        notebook.grid(row=1, column=0, sticky="nsew", padx=8)
        for title, text in (("原文", payload["source"]), ("首次译文", payload["first"]), ("二次译文", payload["second"]),
                            ("核对报告", json.dumps(payload["comparison"], ensure_ascii=False, indent=2))):
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
        for label, value in (("接受首次译文", "first"), ("接受二次译文", "second"), ("保留首次译文，标记待处理", "unresolved")):
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

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "decision":
                    self.decision_dialog(*payload)
                elif kind == "status":
                    self.status.set(payload)
                    self.app.status_var.set(payload)
                elif kind == "done":
                    self.status.set(payload)
                    self.app.status_var.set(payload)
                    self.log(payload)
                    self.start_button.configure(state="normal")
                    self.app.start_btn.configure(state="normal")
                    messagebox.showinfo("文献处理", payload, parent=self.app.root)
                elif kind == "profile_result":
                    controls, testing, result, error, requested = payload
                    if controls.profile() != requested:
                        continue
                    if error:
                        messagebox.showerror("模型接口", error, parent=self.app.root)
                    elif testing:
                        messagebox.showinfo("接口测试通过", result, parent=self.app.root)
                    else:
                        controls.combo.configure(values=result)
                        if controls.model.get() not in result:
                            controls.model.set(result[0])
                        self.log(f"已拉取 {len(result)} 个模型。")
        except queue.Empty:
            pass
        self.app.root.after(100, self.poll)
