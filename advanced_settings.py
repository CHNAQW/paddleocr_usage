"""Prompt preferences and the bundled license, using the existing desktop theme."""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from prompt_templates import PROMPTS, normalize_overrides, snapshot
from responsive_ui import AdaptiveLabel, ButtonToolbar, ResponsiveForm
from ui_i18n import ChoiceVar, LocalizedVar, copy_text, messagebox, tr


PROMPT_LABELS = {
    "ocr_review": "OCR 质量核验",
    "language_detection": "文献语言检测",
    "translation": "文献翻译",
    "translation_second_pass": "二次独立翻译",
    "translation_compare": "两稿翻译核对",
    "translation_arbitrate": "翻译分歧裁决",
    "translation_arbitrate_revise": "翻译裁决与修订",
    "proofreading": "译文文本校对",
    "proofreading_arbitrate": "校对疑点裁决",
    "proofreading_arbitrate_revise": "校对裁决与修订",
    "revision_verify": "修订结果核验",
    "markdown_format": "Markdown 格式整理",
    "markdown_verify": "Markdown 整理核验",
    "markdown_arbitrate": "Markdown 核验裁决",
}


class FlexibleText(ttk.Frame):
    """Use the page's spare height; short windows can still scroll the whole page."""
    def __init__(self, page, *, readonly=False):
        super().__init__(page, height=180)
        self.page, self.canvas = page, page.master
        self.pending = None
        self.compact = None
        self.hide_when_short = []
        self.grid_propagate(False)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        style = ttk.Style(page)
        self.text = tk.Text(self, width=1, height=1, wrap="word", undo=not readonly,
            font="TkTextFont", background=style.lookup("TFrame", "background"),
            foreground=style.lookup("TLabel", "foreground"),
            insertbackground=style.lookup("TLabel", "foreground"),
            relief="flat", highlightthickness=1,
            highlightbackground=style.lookup("TEntry", "bordercolor"), padx=10, pady=8)
        self.text.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self, command=self.text.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=bar.set)
        page.bind("<Configure>", self.schedule, add="+")
        self.canvas.bind("<Configure>", self.schedule, add="+")
        self.bind("<Destroy>", self.cleanup, add="+")

    def schedule(self, _event=None):
        if self.pending is None:
            self.pending = self.after_idle(self.resize)

    def resize(self):
        self.pending = None
        compact = self.canvas.winfo_height() < 300
        if compact != self.compact:
            self.compact = compact
            for widget in self.hide_when_short:
                widget.grid_remove() if compact else widget.grid()
        remaining = self.canvas.winfo_height() - (self.page.winfo_reqheight() - self.winfo_reqheight())
        height = max(120, remaining)
        if int(self.cget("height")) != height:
            self.configure(height=height)

    def cleanup(self, event):
        if event.widget == self and self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None


class AdvancedPromptSettings:
    def __init__(self, page, saved=None):
        self.page = page
        self.overrides = dict(saved) if isinstance(saved, dict) else {}
        # Unknown settings from a newer release must not make this editor fail to open.
        self.overrides = {key: value for key, value in self.overrides.items()
                          if key in PROMPTS and isinstance(value, str)}
        self.current_role = next(iter(PROMPT_LABELS))
        page.configure(padding=(14, 10))
        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        AdaptiveLabel(header, text=tr("自定义 LLM 提示词"), style="CardTitle.TLabel").grid(row=0, column=0, sticky="ew")
        AdaptiveLabel(header, text=tr("修改后保存即可复用；运行中的任务使用开始时的提示词，下次任务才应用修改。"),
                      style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=(5, 0))
        form = ResponsiveForm(page)
        form.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.role = ChoiceVar(master=page, value=PROMPT_LABELS[self.current_role])
        self.selector = ttk.Combobox(form, textvariable=self.role, state="readonly",
                                     values=[tr(value) for value in PROMPT_LABELS.values()])
        self.selector.localized_choices = tuple(PROMPT_LABELS.values())
        self.selector.bind("<<ComboboxSelected>>", self.choose_role)
        form.add(tr("任务角色"), self.selector)
        self.area = FlexibleText(page)
        self.area.grid(row=2, column=0, sticky="nsew")
        self.editor = self.area.text
        actions = ButtonToolbar(page, (
            (tr("恢复此项默认"), self.restore_current),
            (tr("恢复全部默认"), self.restore_all),
            (tr("复制提示词"), lambda: copy_text(self.editor, self.editor.get("1.0", "end-1c"))),
        ))
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.status = LocalizedVar(master=page)
        AdaptiveLabel(page, textvariable=self.status, style="Subtitle.TLabel").grid(row=4, column=0, sticky="ew", pady=(6, 0))
        guidance = AdaptiveLabel(page, text=tr("可修改任务要求；结构化返回字段由软件保持。每项最多 20,000 字符，留空使用默认。"),
                                 style="Subtitle.TLabel")
        guidance.grid(row=5, column=0, sticky="ew", pady=(5, 0))
        self.area.hide_when_short = [header, guidance]
        self.editor.bind("<<Modified>>", self.edited, add="+")
        self.show_current()

    def store_current(self):
        value = self.editor.get("1.0", "end-1c")
        if not value.strip() or value == PROMPTS[self.current_role]:
            self.overrides.pop(self.current_role, None)
        else:
            self.overrides[self.current_role] = value

    def edited(self, _event=None):
        if self.editor.edit_modified():
            self.store_current()
            self.update_status()
            self.editor.edit_modified(False)

    def update_status(self):
        self.status.set(tr("已自定义 · {arg0} 字符", arg0=len(self.editor.get("1.0", "end-1c")))
                        if self.current_role in self.overrides else tr("使用默认提示词"))

    def show_current(self):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.overrides.get(self.current_role, PROMPTS[self.current_role]))
        self.editor.edit_modified(False)
        self.editor.edit_reset()
        self.update_status()

    def choose_role(self, _event=None):
        self.store_current()
        self.current_role = next(key for key, label in PROMPT_LABELS.items() if label == self.role.get())
        self.show_current()

    def restore_current(self):
        self.overrides.pop(self.current_role, None)
        self.show_current()

    def restore_all(self):
        if not messagebox.askyesno(tr("恢复默认提示词"), tr("是否恢复所有任务的默认提示词？当前自定义内容将被替换。"),
                                   parent=self.page.winfo_toplevel()):
            return
        self.overrides.clear()
        self.show_current()

    def config_data(self):
        self.store_current()
        return normalize_overrides(self.overrides)

    def prompt_snapshot(self):
        return snapshot(self.config_data())


def read_license(directory=None):
    directory = Path(directory) if directory is not None else Path(__file__).resolve().parent
    # Older installed updaters only extract .txt assets from a source ZIP.
    for name in ("License", "License.txt"):
        path = directory / name
        if path.is_file():
            return path.read_text(encoding="utf-8-sig")
    raise FileNotFoundError("License / License.txt")


class LegalNotice:
    def __init__(self, page):
        self.page = page
        page.configure(padding=(14, 10))
        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        AdaptiveLabel(header, text=tr("法律声明与许可证"), style="CardTitle.TLabel").grid(row=0, column=0, sticky="ew")
        AdaptiveLabel(header, text=tr("以下显示项目随附的 License 原文。可选择文字或复制全文；界面切换语言不会改写许可证。"),
                      style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=(5, 0))
        area = FlexibleText(page, readonly=True)
        area.hide_when_short = [header]
        area.grid(row=1, column=0, sticky="nsew")
        self.text = area.text
        self.license_text = ""
        try:
            self.license_text = read_license()
            self.text.insert("1.0", self.license_text)
        except (OSError, UnicodeError) as exc:
            AdaptiveLabel(page, text=tr("无法读取随附许可证：{arg0}", arg0=exc),
                          style="Subtitle.TLabel").grid(row=3, column=0, sticky="ew", pady=8)
        self.text.configure(state="disabled")
        self.copy_button = ttk.Button(page, text=tr("复制许可证全文"),
                                      command=lambda: copy_text(self.text, self.license_text))
        self.copy_button.grid(row=2, column=0, sticky="w", pady=(8, 0))
        if not self.license_text:
            self.copy_button.configure(state="disabled")
