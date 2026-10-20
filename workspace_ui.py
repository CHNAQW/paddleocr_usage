"""Desktop workspace layout. Processing and credentials stay in their controllers."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk

from literature_processing import LANGUAGES, PROVIDERS
from literature_ui import LiteratureControls, ModelControls, scrollable_page
from ui_i18n import LocalizedVar, copy_text, language, localize_widgets, messagebox, tr, ui_text
from responsive_ui import AdaptiveCheckbutton, AdaptiveLabel, ButtonToolbar, NotebookSelector, ResponsiveForm


COLORS = {
    "canvas": "#f4f3ef", "paper": "#f4f3ef", "border": "#e1e4de",
    "ink": "#25332e", "muted": "#65736a", "accent": "#2c6651",
    "soft": "#eaf1eb", "rail": "#213d34", "rail_muted": "#a2b7ac",
    "selected": "#35574a", "log": "#16251f", "log_text": "#d8e4db",
}


def configure_workspace_theme(root):
    family = tkfont.nametofont("TkDefaultFont").actual("family")
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=COLORS["canvas"])
    style.configure(".", font=(family, 10), background=COLORS["canvas"], foreground=COLORS["ink"])
    style.configure("TFrame", background=COLORS["canvas"])
    style.configure("Paper.TFrame", background=COLORS["paper"])
    style.configure("TLabel", background=COLORS["canvas"], foreground=COLORS["ink"])
    style.configure("Title.TLabel", font=(family, 23, "bold"))
    style.configure("Subtitle.TLabel", foreground=COLORS["muted"], font=(family, 10))
    style.configure("WizardTitle.TLabel", font=(family, 15, "bold"))
    style.configure("WizardHeading.TLabel", font=(family, 11, "bold"))
    style.configure("WizardStep.TLabel", foreground=COLORS["accent"], font=(family, 10, "bold"))
    style.configure("CardTitle.TLabel", background=COLORS["paper"], font=(family, 11, "bold"))
    style.configure("Card.TLabel", background=COLORS["paper"])
    style.configure("Hint.TLabel", background=COLORS["paper"], foreground=COLORS["muted"], font=(family, 9))
    style.configure("TEntry", fieldbackground=COLORS["paper"], bordercolor=COLORS["border"], padding=8)
    style.map("TEntry", bordercolor=[("focus", COLORS["accent"])],
              fieldbackground=[("disabled", "#e8eae5")], foreground=[("disabled", COLORS["muted"])])
    style.configure("TSpinbox", fieldbackground=COLORS["canvas"], bordercolor=COLORS["border"], padding=6)
    style.configure("TCombobox", fieldbackground=COLORS["paper"], arrowsize=12, padding=6)
    style.map("TCombobox", fieldbackground=[("disabled", "#e8eae5"), ("readonly", COLORS["paper"])],
              background=[("disabled", "#e8eae5")], foreground=[("disabled", COLORS["muted"])],
              arrowcolor=[("disabled", COLORS["muted"])])
    root.option_add("*TCombobox*Listbox.background", COLORS["canvas"])
    root.option_add("*TCombobox*Listbox.foreground", COLORS["ink"])
    style.configure("Treeview", background=COLORS["canvas"], fieldbackground=COLORS["canvas"],
                    foreground=COLORS["ink"])
    style.configure("TButton", background=COLORS["paper"], bordercolor=COLORS["border"],
                    relief="flat", padding=(12, 7), focusthickness=1, focuscolor=COLORS["accent"])
    style.map("TButton", background=[("pressed", "#d8e5d9"), ("active", COLORS["soft"])], foreground=[("disabled", COLORS["muted"])])
    style.configure("Accent.TButton", background=COLORS["accent"], foreground="#ffffff",
                    bordercolor=COLORS["accent"], padding=(20, 9), font=(family, 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", "#c4cfc6"), ("pressed", "#173f2f"), ("active", "#21533f")],
              foreground=[("disabled", "#f2f5f2"), ("!disabled", "#ffffff")])
    style.configure("Quiet.TButton", background=COLORS["canvas"], bordercolor=COLORS["canvas"], padding=(8, 6))
    style.configure("Tool.TButton", padding=(8, 3), font=(family, 9))
    style.configure("TMenubutton", background=COLORS["paper"], bordercolor=COLORS["border"], padding=(10, 7))
    style.configure("TCheckbutton", background=COLORS["paper"], padding=(0, 5))
    style.map("TCheckbutton", background=[("active", COLORS["paper"])])
    style.configure("Wizard.TCheckbutton", background=COLORS["canvas"])
    style.map("Wizard.TCheckbutton", background=[("active", COLORS["canvas"])])
    if "Workspace.Check.indicator" not in style.element_names():
        images = []
        for selected in (False, True):
            image = tk.PhotoImage(master=root, width=23, height=18)
            image.put(COLORS["accent"] if selected else "#aab8ab", to=(0, 1, 16, 17))
            if not selected:
                image.put(COLORS["paper"], to=(1, 2, 15, 16))
            else:
                for x, y in ((4, 8), (5, 9), (6, 10), (7, 9), (8, 8), (9, 7), (10, 6), (11, 5)):
                    image.put("#ffffff", to=(x, y, x + 2, y + 2))
            images.append(image)
        root._workspace_check_images = images
        style.element_create("Workspace.Check.indicator", "image", images[0], ("selected", images[1]), sticky="w")
    style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
        ("Workspace.Check.indicator", {"side": "left"}),
        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [("Checkbutton.label", {"sticky": "nswe"})]}),
    ]})])
    style.configure("Horizontal.TProgressbar", troughcolor=COLORS["border"], background=COLORS["accent"],
                    borderwidth=0, thickness=4, lightcolor=COLORS["accent"], darkcolor=COLORS["accent"])
    style.configure("TNotebook", background=COLORS["canvas"], borderwidth=0, tabmargins=(0, 4, 0, 8))
    style.configure("TNotebook.Tab", background=COLORS["canvas"], padding=(10, 7), borderwidth=0,
                    bordercolor=COLORS["canvas"], lightcolor=COLORS["canvas"], darkcolor=COLORS["canvas"])
    style.map("TNotebook.Tab", background=[("selected", COLORS["soft"])], foreground=[("selected", COLORS["accent"])])
    style.layout("Workspace.TNotebook.Tab", [])
    style.configure("Workspace.TNotebook", borderwidth=0, tabmargins=0)
    style.configure("TLabelframe", background=COLORS["canvas"], bordercolor=COLORS["border"], padding=12)
    style.configure("TLabelframe.Label", foreground=COLORS["muted"], font=(family, 10, "bold"))
    style.configure("Vertical.TScrollbar", troughcolor=COLORS["canvas"], background="#c8cec7", arrowsize=10)
    style.configure("Horizontal.TScrollbar", troughcolor=COLORS["canvas"], background="#c8cec7", arrowsize=10)


class HoverTip:
    """Reveal clipped metadata without changing the surrounding layout."""
    def __init__(self, widget, text):
        self.widget, self.text, self.pending, self.window = widget, text, None, None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.close, add="+")
        widget.bind("<ButtonPress>", self.close, add="+")
        widget.bind("<Destroy>", self.close, add="+")

    def schedule(self, _event=None):
        self.pending = self.widget.after(450, self.show)

    def show(self):
        self.pending = None
        text = self.text()
        if not text:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        ttk.Label(self.window, text=text, wraplength=420, style="Card.TLabel", padding=10).pack()
        self.window.update_idletasks()
        x = min(self.widget.winfo_rootx(), max(0, self.widget.winfo_screenwidth() - self.window.winfo_reqwidth()))
        y = max(0, self.widget.winfo_rooty() - self.window.winfo_reqheight() - 5)
        self.window.geometry(f"+{x}+{y}")

    def close(self, _event=None):
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


def card(parent, title, subtitle=None):
    outer = tk.Frame(parent, bg=COLORS["paper"], highlightbackground=COLORS["border"], highlightthickness=1)
    outer.columnconfigure(0, weight=1)
    body = ttk.Frame(outer, style="Paper.TFrame", padding=(18, 14))
    outer.card_body = body
    outer.hint = None
    body.grid(sticky="nsew")
    body.columnconfigure(0, weight=1)
    ttk.Label(body, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
    if subtitle:
        outer.hint = AdaptiveLabel(body, text=subtitle, style="Hint.TLabel")
        outer.hint.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    content = ttk.Frame(body, style="Paper.TFrame")
    content.grid(row=2, column=0, sticky="ew")
    content.columnconfigure(0, weight=1)
    return outer, content


def path_field(parent, row, label, variable, command):
    group = ttk.Frame(parent, style="Paper.TFrame")
    group.grid(row=row, column=0, sticky="ew", pady=(0, 10))
    group.columnconfigure(0, weight=1)
    ttk.Label(group, text=label, style="Hint.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
    entry = ttk.Entry(group, textvariable=variable, width=12)
    entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
    button = ttk.Button(group, text=tr('选择文件夹'), command=command)
    button.grid(row=1, column=1)
    return entry, button


def quality_controls(parent, controls):
    """OCR and translation share checks, decision mode and revision permission."""
    panel = ttk.Frame(parent, style="Paper.TFrame")
    panel.columnconfigure(0, weight=1)
    panel.secondary_button = AdaptiveCheckbutton(panel, text=tr('二次翻译核对'), variable=controls.secondary)
    panel.secondary_button.grid(row=0, column=0, sticky="ew")
    panel.proofreading_button = AdaptiveCheckbutton(panel, text=tr('文本校对'), variable=controls.proofreading)
    panel.proofreading_button.grid(row=1, column=0, sticky="ew")
    form = ResponsiveForm(panel)
    form.grid(row=2, column=0, sticky="ew", pady=(4, 0))
    panel.arbitration_combo = ttk.Combobox(form, textvariable=controls.arbitration,
        values=[tr('用户自行裁决'), tr('大模型裁决')], state="readonly")
    panel.arbitration_combo.localized_choices = True
    form.add(tr("发现问题时"), panel.arbitration_combo)
    panel.revision_button = AdaptiveCheckbutton(panel, text=tr("允许裁决模型直接修订译文"), variable=controls.allow_arbiter_revision)
    panel.revision_button.grid(row=3, column=0, sticky="ew", pady=(8, 0))
    AdaptiveLabel(panel, text=tr("默认不授权。授权后，模型可修订翻译分歧或校对疑点，自动核验通过即采用，无需再次确认；仍有疑点时保留报告并交由用户处理。"),
                  style="Hint.TLabel").grid(row=4, column=0, sticky="ew", pady=(6, 0))

    panel.automatic_button = AdaptiveCheckbutton(panel, text=tr("强制全自动（无需人工裁决）"), variable=controls.force_auto)
    panel.automatic_button.grid(row=5, column=0, sticky="ew", pady=(8, 0))
    AdaptiveLabel(panel, text=tr("启用文本校对、模型裁决及修订授权；疑点由模型决定。失败最多尝试两次，保留待处理稿并继续，不弹人工选择。"),
                  style="Hint.TLabel").grid(row=6, column=0, sticky="ew", pady=(4, 0))
    def refresh(*_):
        checking = controls.secondary.get() or controls.proofreading.get()
        automatic = controls.force_auto.get()
        panel.proofreading_button.configure(state="disabled" if automatic else "normal")
        panel.arbitration_combo.configure(state="readonly" if checking and not automatic else "disabled")
        panel.revision_button.configure(state="normal" if checking and controls.arbitration.get() == "大模型裁决" and not automatic else "disabled")
    traces = [(variable, variable.trace_add("write", refresh)) for variable in (controls.secondary, controls.proofreading, controls.arbitration, controls.force_auto)]
    def cleanup(event):
        if event.widget == panel:
            for variable, trace in traces:
                variable.trace_remove("write", trace)
    panel.bind("<Destroy>", cleanup, add="+")
    refresh()
    return panel


def build_translation_page(controls, saved, fetch, test):
    """Create task options here; advanced service configuration lives in Settings."""
    shell = controls.app.workspace_layout
    page = controls.page
    files, body = card(page, tr('01   文献文件夹'), tr('扫描已有 Markdown，自动跳过已是目标语言的文献。'))
    files.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 12))
    controls.input_entry, _ = path_field(body, 0, tr('原文位置'), controls.input, lambda: controls.choose_dir(controls.input))
    controls.output_entry, controls.output_button = path_field(body, 1, tr('译文位置'), controls.output, lambda: controls.choose_dir(controls.output))
    AdaptiveCheckbutton(body, text=tr('译文保存在原文所在文件夹'), variable=controls.same_folder,
                    command=lambda: shell.sync_output()).grid(row=2, column=0, sticky="ew")
    AdaptiveCheckbutton(body, text=tr('包括子文件夹'), variable=controls.recursive).grid(row=3, column=0, sticky="ew")

    options, body = card(page, tr('02   语言与质量'), tr('翻译模型读取前 300 字符识别语言，长文自动分段。'))
    options.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
    controls.language_form = ResponsiveForm(body)
    controls.language_form.grid(row=0, column=0, sticky="ew")
    for row, label, variable, values in ((0, tr('来源语言'), controls.source, [tr('自动检测')] + list(LANGUAGES)),
                                        (1, tr('目标语言'), controls.target, list(LANGUAGES)),
                                        (2, tr('文件名标记'), controls.prefix, [tr('前缀 TRANSLATED_'), tr('后缀 _TRANSLATED')])):
        selector = ttk.Combobox(controls.language_form, textvariable=variable, values=[ui_text(value) for value in values],
                               state="readonly" if row == 2 else "normal")
        selector.localized_choices = True
        controls.language_form.add(label, selector)
    ttk.Separator(body).grid(row=3, column=0, sticky="ew", pady=12)
    controls.quality_panel = quality_controls(body, controls)
    controls.quality_panel.grid(row=4, column=0, sticky="ew")
    summary, body = card(page, tr('03   处理服务'))
    summary.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
    controls.model_summary = LocalizedVar(value=tr('尚未设置翻译模型'))
    model_label = AdaptiveLabel(body, textvariable=controls.model_summary, style="Card.TLabel")
    model_label.grid(row=0, column=0, sticky="ew", pady=5)
    HoverTip(model_label, controls.model_summary.get)
    ttk.Button(body, text=tr('配置模型与上传'), command=lambda: shell.show_settings(1)).grid(row=1, column=0, sticky="w", pady=5)
    shell.build_settings(controls, saved, fetch, test)
    shell.forms.append((page, files, options, summary))


class WorkspaceLayout:
    def __init__(self, app, model_choices, fetch, test, version, icon_path):
        self.app, self.root = app, app.root
        self.family = tkfont.nametofont("TkDefaultFont").actual("family")
        self.compact = None
        self.settings = None
        self.forms = []
        self.form_columns = {}
        app.workspace_layout = self
        self.rail = tk.Frame(self.root, bg=COLORS["rail"], width=184)
        self.brand = tk.Frame(self.rail, bg=COLORS["rail"])
        self.brand_icons = {}
        try:
            # Keep the original artwork and strong references through layout changes.
            self.brand_icon_source = tk.PhotoImage(master=self.root, file=str(icon_path))
            dimension = max(self.brand_icon_source.width(), self.brand_icon_source.height())
            self.brand_icons = {
                size: self.brand_icon_source.subsample(max(1, (dimension + size - 1) // size))
                for size in (32, 48)
            }
        except (tk.TclError, OSError) as exc:
            app.log_queue.put(("log", tr('无法加载应用图标：{arg0}', arg0=exc)))
        self.mark = tk.Label(self.brand, text=tr('文献'), font=(self.family, 23, "bold"),
                             bg=COLORS["rail"], fg="#eff4eb", bd=0, padx=0, pady=0)
        self.mark.pack(anchor="w")
        self.brand_name = tk.Label(self.brand, text=tr('文献处理软件'), font=(self.family, 11, "bold"),
                                   bg=COLORS["rail"], fg="#eff4eb", wraplength=140, justify="left")
        self.brand_name.pack(anchor="w", pady=(8, 0))
        self.nav_area = tk.Frame(self.rail, bg=COLORS["rail"])
        self.nav_buttons = []
        for index, title in enumerate(("01   PDF OCR", tr('02   外文翻译'), tr('03   GitHub 上传'))):
            button = tk.Button(self.nav_area, text=title, anchor="w", relief="flat", bd=0, padx=14, pady=12,
                font=(self.family, 10, "bold"), bg=COLORS["rail"], fg=COLORS["rail_muted"],
                activebackground=COLORS["selected"], activeforeground="#ffffff", cursor="hand2",
                highlightthickness=1, highlightbackground=COLORS["rail"], highlightcolor="#9fc4ab",
                command=lambda i=index: app.notebook.select(i))
            self.nav_buttons.append(button)
        self.rail_footer = tk.Frame(self.rail, bg=COLORS["rail"])
        self.settings_button = tk.Button(self.rail_footer, text=tr('偏好设置'), anchor="w", relief="flat", bd=0,
            bg=COLORS["rail"], fg="#dce9dd", activebackground=COLORS["selected"], activeforeground="#ffffff",
            highlightbackground=COLORS["rail"], highlightcolor="#9fc4ab",
            font=(self.family, 10), padx=14, pady=10, cursor="hand2", command=self.show_settings)
        self.settings_button.pack(fill="x")
        self.version = tk.Label(self.rail_footer, text=version, bg=COLORS["rail"], fg=COLORS["rail_muted"], font=(self.family, 9))
        self.version.pack(anchor="w", padx=14, pady=(4, 16))

        self.workspace = ttk.Frame(self.root)
        self.workspace.bind("<Configure>", lambda event: self.reflow_forms())
        self.workspace.columnconfigure(0, weight=1)
        self.workspace.rowconfigure(1, weight=1)
        header = ttk.Frame(self.workspace, padding=(24, 16, 20, 8))
        self.header = header
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.title = ttk.Label(header, text=tr('PDF OCR 转 Markdown'), style="Title.TLabel")
        self.title.grid(row=0, column=0, sticky="w")
        self.subtitle = ttk.Label(header, text=tr('从扫描文档到可检索的文献。'), style="Subtitle.TLabel")
        self.subtitle.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.language_button = ttk.Button(header, text="文/A", style="Quiet.TButton",
            command=lambda: app.change_ui_language("en" if language() == "zh" else "zh"))
        self.language_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))
        HoverTip(self.language_button, lambda: "中文 / English")
        self.toolbar = ButtonToolbar(header, (
            (tr('扫描 PDF'), app.scan_pdfs), (tr('扫描 Markdown'), lambda: app.literature.scan()),
            (tr('修复 JSON'), app.repair_json_to_md),
            (tr('MD 整理'), lambda: app.literature.open_formatting()),
            (tr('字数检验'), app.manual_wordcount_check), (tr('LLM 检验'), app.manual_llm_check),
            (tr('OCR 输出目录'), app.open_output_dir), (tr('配置位置'), app.show_config_path)))
        self.toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        app.workspace_panes = tk.PanedWindow(self.workspace, orient="vertical", sashwidth=6,
                                            bg=COLORS["canvas"], bd=0, sashrelief="flat")
        app.workspace_panes.grid(row=1, column=0, sticky="nsew")
        app.notebook = ttk.Notebook(app.workspace_panes, style="Workspace.TNotebook")
        app.workspace_panes.add(app.notebook, minsize=100, stretch="always")
        app.workspace_panes.bind("<Configure>", self.constrain_panes, add="+")
        app.workspace_panes.bind("<ButtonRelease-1>", self.constrain_panes, add="+")
        ocr_page = scrollable_page(app.notebook, tr('PDF OCR 转 MD功能'))
        translation_page = scrollable_page(app.notebook, tr('外文文献翻译功能'))
        app.literature = LiteratureControls(app, translation_page, fetch, test)
        github_page = scrollable_page(app.notebook, tr('GitHub 文档上传'))
        self.build_github(github_page)
        self.build_ocr(ocr_page, model_choices)
        self.build_log()
        self.build_actions()
        app.notebook.bind("<<NotebookTabChanged>>", self.select)
        self.root.bind("<Configure>", self.resize, add="+")
        self.root.bind("<Control-Key-1>", lambda event: app.notebook.select(0))
        self.root.bind("<Control-Key-2>", lambda event: app.notebook.select(1))
        self.root.bind("<Control-Key-3>", lambda event: app.notebook.select(2))
        self.resize()
        self.select()
        self.sync_output()
        self.refresh_language()

    def build_github(self, page):
        from github_ui import ManualUpload
        controls = self.app.literature
        setup = controls.github_setup
        destination, body = card(page, tr("01   GitHub 上传位置"), tr("手动上传可独立使用，无需先运行 OCR 或翻译，也无需开启自动上传。"))
        destination.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 12))
        AdaptiveLabel(body, textvariable=setup.summary, style="Card.TLabel").grid(row=0, column=0, sticky="ew", pady=6)
        ttk.Button(body, text=tr("打开上传设置向导"), command=setup.open).grid(row=1, column=0, sticky="w", pady=6)
        documents, body = card(page, tr("02   选择并补传文档"))
        documents.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        self.github_manual = setup.manual = ManualUpload(setup, parent=body)

    def build_ocr(self, page, models):
        app = self.app
        files, body = card(page, tr('01   文档位置'), tr('选择 PDF 所在文件夹，保留原文并生成 Markdown。'))
        files.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 12))
        app.input_entry, _ = path_field(body, 0, tr('PDF 输入文件夹'), app.input_var, app.choose_input_dir)
        app.output_entry, _ = path_field(body, 1, tr('Markdown 输出文件夹'), app.output_var, app.choose_output_dir)
        options, body = card(page, tr('02   处理选项'))
        options.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        line = ResponsiveForm(body)
        line.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        app.model_combo = ttk.Combobox(line, textvariable=app.model_var, values=models, state="readonly")
        line.add(tr('OCR 模型'), app.model_combo)
        for row, text, variable in ((1, tr('包括子文件夹'), app.recursive_var), (2, tr('保留子文件夹结构'), app.preserve_var),
                                     (3, tr('覆盖已有 Markdown'), app.overwrite_var), (4, tr('使用 LLM 核验 OCR 质量'), app.llm_review_var),
                                     (5, tr('自动检测外文并翻译'), app.literature.auto_translate)):
            AdaptiveCheckbutton(body, text=text, variable=variable).grid(row=row, column=0, sticky="ew")
        self.ocr_quality_group = ttk.LabelFrame(body, text=tr("自动翻译核对设置（两入口共用）"), padding=10)
        self.ocr_quality_group.columnconfigure(0, weight=1)
        self.ocr_quality_group.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        self.ocr_quality_panel = quality_controls(self.ocr_quality_group, app.literature)
        self.ocr_quality_panel.grid(row=0, column=0, sticky="ew")
        ttk.Button(self.ocr_quality_group, text=tr("配置翻译与裁决模型"),
                   command=lambda: self.show_settings(1)).grid(row=1, column=0, sticky="w", pady=(6, 0))
        def sync_quality_options(*_):
            if app.literature.auto_translate.get():
                self.ocr_quality_group.grid()
            else:
                self.ocr_quality_group.grid_remove()
        app.literature.auto_translate.trace_add("write", sync_quality_options)
        sync_quality_options()
        AdaptiveLabel(body, text=tr('大于 50MB 的 PDF 会自动拆分并合并结果。'), style="Hint.TLabel").grid(row=7, column=0, sticky="ew", pady=(8, 0))
        service, body = card(page, tr('03   处理服务'))
        service.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
        AdaptiveLabel(body, textvariable=app.token_state_var, style="Card.TLabel").grid(row=0, column=0, sticky="ew", pady=5)
        ttk.Button(body, text=tr('配置 OCR 与核验'), command=lambda: self.show_settings(0)).grid(row=1, column=0, sticky="w", pady=5)
        self.forms.append((page, files, options, service))

    def build_settings(self, controls, saved, fetch, test):
        app = self.app
        self.settings = tk.Toplevel(self.root)
        self.settings.withdraw()
        self.settings.minsize(440, 340)
        self.settings.title(tr('偏好设置 · 文献处理软件'))
        self.settings.transient(self.root)
        self.settings.columnconfigure(0, weight=1)
        self.settings.rowconfigure(1, weight=1)
        settings_header = ttk.Frame(self.settings, padding=(18, 14))
        settings_header.grid(row=0, column=0, sticky="ew")
        settings_header.columnconfigure(0, weight=1)
        settings_title = AdaptiveLabel(settings_header, text=tr('偏好设置'), style="CardTitle.TLabel")
        settings_title.grid(row=0, column=0, columnspan=2, sticky="ew")
        language_caption = AdaptiveLabel(settings_header, text=tr('界面语言 / Interface language'), style="Subtitle.TLabel")
        language_caption.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        app.ui_language_var = tk.StringVar(value="English" if language() == "en" else "中文")
        self.language_selector = ttk.Combobox(settings_header, textvariable=app.ui_language_var,
                                              values=("中文", "English"), state="readonly", width=10)
        self.language_selector.grid(row=1, column=1, sticky="e", pady=(8, 0), padx=(12, 0))
        self.language_selector.bind("<<ComboboxSelected>>", lambda event: app.change_ui_language(
            "en" if app.ui_language_var.get() == "English" else "zh"))
        self.settings_tabs = ttk.Notebook(self.settings)
        self.settings_tabs.grid(row=1, column=0, sticky="nsew", padx=12)
        self.settings_selector = NotebookSelector(settings_header, self.settings_tabs)
        self.settings_selector.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ocr = scrollable_page(self.settings_tabs, tr('OCR 与核验'))
        models = scrollable_page(self.settings_tabs, tr('翻译模型'))
        github = scrollable_page(self.settings_tabs, tr('GitHub 上传'))
        updates = scrollable_page(self.settings_tabs, tr('软件更新'))
        token = ttk.LabelFrame(ocr, text="PaddleOCR", padding=12)
        token.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        token.columnconfigure(0, weight=1)
        AdaptiveLabel(token, textvariable=app.token_state_var).grid(row=0, column=0, columnspan=2, sticky="ew", pady=8)
        for row, title, callback in ((1, tr('输入/更新 Access Token'), app.set_token), (2, tr('检测 API Key 是否有效'), app.check_api_key), (3, tr('清除 Token'), app.clear_token)):
            ttk.Button(token, text=title, command=callback).grid(row=row, column=0, sticky="w", pady=4)
        review = ttk.LabelFrame(ocr, text=tr('OCR 质量核验模型'), padding=12)
        review.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        review.columnconfigure(0, weight=1)
        form = ResponsiveForm(review, style="TFrame")
        form.grid(row=0, column=0, columnspan=2, sticky="ew")
        for row, title, variable in ((0, "Base URL", app.llm_base_url_var), (1, "API Key", app.llm_api_key_var)):
            entry = ttk.Entry(form, textvariable=variable, show="*" if row == 1 else "")
            form.add(title, entry)
            setattr(app, "shared_review_key_entry" if row == 1 else "shared_review_url_entry", entry)
        app.llm_model_combo = ttk.Combobox(form, textvariable=app.llm_model_var)
        form.add(tr('模型'), app.llm_model_combo)
        review_actions = ButtonToolbar(review, ((tr('拉取模型列表'), app.fetch_llm_models), (tr('测试LLM API'), app.test_llm_api)))
        review_actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        app.fetch_models_btn, app.test_llm_api_btn = review_actions.buttons

        budget = ttk.LabelFrame(models, text=tr("翻译分段预算"), padding=12)
        budget.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        budget.columnconfigure(0, weight=1)
        budget_form = ResponsiveForm(budget, style="TFrame")
        budget_form.grid(row=0, column=0, sticky="ew")
        controls.percent_spinbox = ttk.Spinbox(budget_form, from_=50, to=80, increment=1,
                                               textvariable=controls.input_percent)
        budget_form.add(tr("输入上限使用比例（50%–80%）"), controls.percent_spinbox)
        AdaptiveLabel(budget, text=tr("默认 50%。按模型上限计算整次请求预算，计入提示词与核对所需的译文，并为输出保留空间。"),
                      style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=(6, 0))
        AdaptiveLabel(budget, text=tr("兼容接口没有统一 tokenizer；使用 UTF-8 字节数加消息开销保守估算 token，优先保留完整段落。"),
                      style="Subtitle.TLabel").grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(budget, text=tr("统一 LLM 服务设置"), command=lambda: self.show_settings(4)).grid(row=3, column=0, sticky="w", pady=6)
        roles = ttk.Notebook(models)
        roles.grid(row=2, column=0, sticky="ew", padx=8, pady=8)
        self.roles_selector = NotebookSelector(models, roles)
        self.roles_selector.grid(row=1, column=0, sticky="ew", padx=8, pady=(8, 0))
        for key, title in (("translator", tr('翻译')), ("reviewer", tr('二次核对')), ("proofreader", tr('校对')), ("arbiter", tr('裁决'))):
            tab = ttk.Frame(roles)
            tab.columnconfigure(0, weight=1)
            roles.add(tab, text=title)
            model = ModelControls(tab, title + tr('模型'), saved.get(key, {}), controls.events, fetch, test, app=self.app)
            model.box.grid(row=0, column=0, sticky="ew", padx=6, pady=8)
            controls.profiles[key] = model
            if key == "translator":
                model.model.trace_add("write", lambda *_: self.refresh_model_summary(controls))
        self.refresh_model_summary(controls)
        from github_ui import GitHubSetup
        controls.github_setup = GitHubSetup(github, controls)
        from update_ui import UpdatePanel
        app.updates = UpdatePanel(updates, app, self.app.app_version, self.app.compiled_application)
        shared = scrollable_page(self.settings_tabs, tr("LLM 服务"))
        group = ttk.LabelFrame(shared, text=tr("统一 LLM 服务设置"), padding=14)
        group.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        group.columnconfigure(0, weight=1)
        AdaptiveCheckbutton(group, text=tr("所有 LLM 共用同一服务商与 API Key"), variable=controls.shared_llm).grid(row=0, column=0, sticky="ew", pady=6)
        AdaptiveCheckbutton(group, text=tr("强制全自动（无需人工裁决）"), variable=controls.force_auto).grid(row=4, column=0, sticky="ew", pady=6)
        AdaptiveLabel(group, text=tr("启用文本校对、模型裁决及修订授权；疑点由模型决定。失败最多尝试两次，保留待处理稿并继续，不弹人工选择。"),
                      style="Subtitle.TLabel").grid(row=5, column=0, sticky="ew", pady=6)
        shared_form = ResponsiveForm(group)
        shared_form.grid(row=1, column=0, sticky="ew")
        preset = ttk.Combobox(shared_form, textvariable=controls.shared_provider, values=[tr(v) for v in PROVIDERS], state="readonly")
        preset.localized_choices = True
        preset.bind("<<ComboboxSelected>>", controls.shared_preset)
        shared_form.add(tr("服务商预设"), preset)
        controls.shared_selector = preset
        shared_form.add("Base URL", ttk.Entry(shared_form, textvariable=controls.shared_url))
        shared_form.add("API Key", ttk.Entry(shared_form, textvariable=controls.shared_key, show="*"))
        AdaptiveLabel(group, text=tr("共享 OCR 的 LLM 核验、翻译、二次核对、校对、裁决及 Markdown 整理与核验的连接。各任务仍可分别选择模型；PaddleOCR 的服务与 Token 独立配置。"),
                      style="Subtitle.TLabel").grid(row=2, column=0, sticky="ew", pady=8)
        AdaptiveLabel(group, text=tr("启用后各任务的服务商、地址和密钥由此处管理。关闭后保留当前连接，可再分别修改；更换服务后请拉取并选择适配的模型。"),
                      style="Subtitle.TLabel").grid(row=3, column=0, sticky="ew", pady=8)
        from advanced_settings import AdvancedPromptSettings, LegalNotice
        advanced = scrollable_page(self.settings_tabs, tr("高级"))
        legal = scrollable_page(self.settings_tabs, tr("法律声明"))
        controls.advanced = AdvancedPromptSettings(advanced, saved.get("prompts", {}))
        self.legal_notice = LegalNotice(legal)
        footer = ttk.Frame(self.settings, padding=12)
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        privacy_hint = AdaptiveLabel(footer, text=tr('模型密钥保存在本机配置，请勿共享。'), style="Subtitle.TLabel")
        privacy_hint.grid(row=0, column=0, sticky="ew")
        ttk.Button(footer, text=tr('保存并返回'), style="Accent.TButton", command=self.close_settings).grid(row=0, column=1, padx=(8, 0))
        compact_settings = None
        def fit_settings(event):
            nonlocal compact_settings
            if event.widget != self.settings:
                return
            compact = self.settings.winfo_height() < 480
            if compact == compact_settings:
                return
            compact_settings = compact
            settings_header.configure(padding=(12, 8) if compact else (18, 14))
            footer.configure(padding=(12, 6) if compact else 12)
            for widget in (settings_title, language_caption, privacy_hint):
                widget.grid_remove() if compact else widget.grid()
            self.language_selector.grid_configure(row=0 if compact else 1,
                pady=0 if compact else (8, 0), padx=(8, 0) if compact else (12, 0))
            self.settings_selector.grid_configure(row=0 if compact else 2,
                columnspan=1 if compact else 2, pady=0 if compact else (10, 0))
            self.settings_selector.schedule()
        self.settings.bind("<Configure>", fit_settings, add="+")
        self.settings.protocol("WM_DELETE_WINDOW", self.close_settings)
        self.settings.bind("<Escape>", lambda event: self.close_settings())

    def show_settings(self, tab=0):
        self.settings_tabs.select(tab)
        width = min(680, max(440, self.root.winfo_width()), self.root.winfo_screenwidth() - 60)
        height = min(650, max(340, self.root.winfo_height()), self.root.winfo_screenheight() - 80)
        x = min(max(0, self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2),
                max(0, self.root.winfo_screenwidth() - width))
        y = min(max(0, self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2),
                max(0, self.root.winfo_screenheight() - height))
        self.settings.geometry(f"{width}x{height}+{x}+{y}")
        self.settings.deiconify()
        self.settings.lift()
        self.settings.focus_set()

    def close_settings(self):
        try:
            self.app.save_current_config()
        except Exception as exc:
            messagebox.showerror(tr('无法保存设置'), str(exc), parent=self.settings)
            return
        self.settings.withdraw()

    def refresh_model_summary(self, controls):
        controls.model_summary.set(tr("翻译模型  ·  {arg0}",
                                      arg0=controls.profiles["translator"].model.get() or tr("尚未设置")))

    def refresh_language(self):
        localize_widgets(self.root)
        self.app.ui_language_var.set("English" if language() == "en" else "中文")
        self.refresh_model_summary(self.app.literature)
        self.select()
        self.resize()
        self.settings_selector.schedule()
        self.roles_selector.schedule()
        manual = getattr(self.app.literature.github_setup, "manual", None)
        if manual and not manual.closed:
            manual.render()

    def sync_output(self):
        controls = self.app.literature
        if controls.same_folder.get() and controls.output.get() != controls.input.get():
            controls.output.set(controls.input.get())
        controls.output_entry.configure(state="disabled" if controls.same_folder.get() else "normal")
        controls.output_button.configure(state="normal")

    def build_log(self):
        app = self.app
        self.log_frame = tk.Frame(app.workspace_panes, bg=COLORS["log"])
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(1, weight=1)
        app.workspace_panes.add(self.log_frame, minsize=86, height=155, stretch="never")
        self.log_header = tk.Frame(self.log_frame, bg=COLORS["log"])
        self.log_header.grid(row=0, column=0, sticky="ew", padx=16, pady=7)
        self.log_header.columnconfigure(1, weight=1)
        self.log_header.columnconfigure(2, weight=1)
        tk.Label(self.log_header, text=tr('运行日志'), bg=COLORS["log"], fg="#adbcaf", font=(self.family, 9),
                 anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 12))
        app.log_text = tk.Text(self.log_frame, height=5, width=20, wrap="word", bg=COLORS["log"],
                              fg=COLORS["log_text"], relief="flat", bd=0, highlightthickness=0,
                              padx=16, pady=3, spacing3=3, font="TkTextFont", state="disabled")
        app.log_text.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        app.log_text._copy_full_text = app.copyable_log_text
        scrollbar = ttk.Scrollbar(self.log_frame, command=app.log_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(0, 8))
        app.log_text.configure(yscrollcommand=scrollbar.set)
        self.copy_log_button = tk.Button(self.log_header, text=tr("复制日志"), relief="flat", bd=0,
            bg=COLORS["log"], fg=COLORS["log_text"], activebackground=COLORS["rail"],
            activeforeground=COLORS["log_text"], cursor="hand2", font=(self.family, 9),
            command=lambda: copy_text(app.root, app.copyable_log_text()))
        self.copy_log_button.grid(row=0, column=3, sticky="e")
        app._configure_log_tags()

    def build_actions(self):
        app = self.app
        self.actions = ttk.Frame(self.workspace, padding=(20, 10, 20, 12))
        self.actions.grid(row=2, column=0, sticky="ew")
        self.actions.columnconfigure(0, weight=1)
        track = ttk.Frame(self.actions, height=4)
        track.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        track.grid_propagate(False)
        app.file_progress = ttk.Progressbar(track, variable=app.file_progress_var, maximum=100)
        app.file_progress.place(x=0, y=0, relwidth=1, height=4)
        app.status_label = AdaptiveLabel(self.actions, textvariable=app.status_var, max_lines=2, style="Subtitle.TLabel")
        app.status_label.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.status_tip = HoverTip(app.status_label, app.status_var.get)
        app.start_btn = ttk.Button(self.actions, text=tr('开始 OCR'), style="Accent.TButton", command=app.start_batch)
        app.start_btn.grid(row=1, column=3)
        app.literature.start_button = ttk.Button(self.actions, text=tr('开始翻译'), style="Accent.TButton", command=app.literature.start)
        app.literature.start_button.grid(row=1, column=3)
        app.stop_btn = ttk.Button(self.actions, text=tr('停止'), command=app.request_stop, state="disabled")
        app.stop_btn.grid(row=1, column=2, padx=(0, 8))
        self.translation_stop = ttk.Button(self.actions, text=tr('停止'), command=app.literature.stop, state="disabled")
        self.translation_stop.grid(row=1, column=2, padx=(0, 8))
        app.manual_query_btn = ttk.Button(self.actions, text=tr('查询'), command=app.manual_query_current_result, state="disabled")
        app.manual_query_btn.grid(row=1, column=1, padx=(0, 8))
        manual = self.github_manual
        self.github_status = AdaptiveLabel(self.actions, textvariable=manual.status, max_lines=2, style="Subtitle.TLabel")
        self.github_scan = ttk.Button(self.actions, text=tr("扫描缺失文档"), command=manual.scan)
        self.github_upload = ttk.Button(self.actions, text=tr("上传选中文档"), command=manual.upload, style="Accent.TButton")
        self.github_stop = ttk.Button(self.actions, text=tr("停止"), command=manual.cancel.set)
        self.github_status.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.github_scan.grid(row=1, column=1, padx=(0, 8))
        self.github_stop.grid(row=1, column=2, padx=(0, 8))
        self.github_upload.grid(row=1, column=3)
        self.task_progress_track = track
        manual.extra_buttons.append((self.github_scan, self.github_upload, self.github_stop))
        manual.buttons()
        app.page_progress = ttk.Progressbar(self.log_frame, variable=app.page_progress_var, maximum=100)
        app.page_progress_text_label = tk.Label(self.log_header, textvariable=app.page_progress_text_var,
            bg=COLORS["log"], fg="#adbcaf", font=(self.family, 9), width=1, anchor="w")
        app.page_progress_text_label.grid(row=0, column=1, sticky="ew", padx=4)
        HoverTip(app.page_progress_text_label, app.page_progress_text_var.get)
        app.split_progress_label = tk.Label(self.log_header, textvariable=app.split_progress_text_var,
            bg=COLORS["log"], fg="#adbcaf", font=(self.family, 9), width=1, anchor="w")
        app.split_progress_label.grid(row=0, column=2, sticky="ew", padx=4)
        HoverTip(app.split_progress_label, app.split_progress_text_var.get)
        app.split_progress_label.grid_remove()
        app.file_progress_var.trace_add("write", self.progress_visibility)
        app.page_progress_var.trace_add("write", self.progress_visibility)
        self.progress_visibility()

    def progress_visibility(self, *_):
        app = self.app
        if not hasattr(app, "file_progress"):
            return
        working = bool(app.worker_thread and app.worker_thread.is_alive())
        if working:
            app.page_progress_text_label.grid()
        else:
            app.page_progress_text_label.grid_remove()

    def select(self, _event=None):
        app = self.app
        index = app.notebook.index(app.notebook.select())
        for i, button in enumerate(self.nav_buttons):
            button.configure(bg=COLORS["selected"] if i == index else COLORS["rail"],
                             fg="#ffffff" if i == index else COLORS["rail_muted"])
        self.title.configure(text=(tr('PDF OCR 转 Markdown'), tr('外文文献翻译'), tr('GitHub 文档上传'))[index])
        self.subtitle.configure(text=(tr('从扫描文档到可检索的文献。'), tr('保留原意，让文献跨越语言。'),
                                      tr('比较远端目录，上传核验通过的文档。'))[index])
        app.start_btn.grid_remove()
        app.literature.start_button.grid_remove()
        app.stop_btn.grid_remove()
        self.translation_stop.grid_remove()
        app.manual_query_btn.grid_remove()
        for widget in (self.github_status, self.github_scan, self.github_upload, self.github_stop):
            widget.grid_remove()
        app.status_label.grid()
        self.task_progress_track.grid()
        if index == 0:
            app.start_btn.grid()
            app.stop_btn.grid()
            app.manual_query_btn.grid()
        elif index == 1:
            app.literature.start_button.grid()
            self.translation_stop.grid()
        else:
            app.status_label.grid_remove()
            self.task_progress_track.grid_remove()
            for widget in (self.github_status, self.github_scan, self.github_upload, self.github_stop):
                widget.grid()

    def constrain_panes(self, _event=None):
        """Keep a scrollable document viewport when the log divider is dragged."""
        panes = self.app.workspace_panes
        if len(panes.panes()) < 2:
            return
        height = panes.winfo_height()
        if height < 100:
            return
        # Header/button font metrics vary with Tk DPI. Reserve actual text space.
        required_log = self.log_header.winfo_reqheight() + 14 + 8 + 40
        log_minimum = min(max(92, required_log), max(42, height - 70))
        minimum = min(220, max(64, int(height * .30)), height - log_minimum - 6)
        panes.paneconfigure(self.app.notebook, minsize=minimum)
        panes.paneconfigure(self.log_frame, minsize=log_minimum)
        top = panes.sash_coord(0)[1]
        bounded = min(max(top, minimum), max(minimum, height - log_minimum - 6))
        if bounded != top:
            panes.sash_place(0, 0, bounded)

    def resize(self, event=None):
        if event is not None and event.widget != self.root:
            return
        nav_font = tkfont.Font(master=self.root, font=self.nav_buttons[0].cget("font"))
        padding = max(32, nav_font.metrics("linespace") * 3)
        rail_width = max(148, *(nav_font.measure(str(text)) + padding for text in
            ("01   PDF OCR", tr('02   外文翻译'), tr('03   GitHub 上传'), tr('偏好设置'), self.version.cget("text"))))
        compact = (self.root.winfo_width() < rail_width + max(650, nav_font.metrics("linespace") * 35)
                   or self.root.winfo_height() < 520)
        self.reflow_forms()
        if hasattr(self, "github_manual"):
            self.github_manual.resize()
        if compact == self.compact and getattr(self, "rail_width", None) == rail_width:
            return
        self.compact = compact
        self.rail_width = rail_width
        self.github_scan.configure(text=tr("扫描缺失") if compact else tr("扫描缺失文档"))
        self.github_upload.configure(text=tr("上传所选") if compact else tr("上传选中文档"))
        self.rail.grid_forget()
        self.workspace.grid_forget()
        for widget in (self.brand, self.nav_area, self.rail_footer):
            widget.grid_forget()
        for button in self.nav_buttons:
            button.grid_forget()
        if compact:
            self.root.columnconfigure(0, weight=1, minsize=0)
            self.root.columnconfigure(1, weight=0)
            self.root.rowconfigure(0, weight=0)
            self.root.rowconfigure(1, weight=1)
            self.rail.grid_propagate(True)
            self.rail.grid(row=0, column=0, columnspan=2, sticky="ew")
            self.rail.columnconfigure(0, weight=0)
            self.rail.columnconfigure(1, weight=1)
            self.rail.columnconfigure(2, weight=0)
            self.rail.rowconfigure(1, weight=0)
            self.brand_name.pack_forget()
            self.mark.configure(image=self.brand_icons.get(32, ""),
                                text="" if self.brand_icons else tr('文献'), font=(self.family, 11, "bold"))
            self.brand.grid(row=0, column=0, sticky="w", padx=14)
            self.rail_footer.grid(row=0, column=2, sticky="e", padx=8)
            self.version.pack_forget()
            self.nav_area.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
            for i, button in enumerate(self.nav_buttons):
                self.nav_area.columnconfigure(i, weight=1)
                button.configure(text=("PDF OCR", tr('外文翻译'), "GitHub")[i], pady=8, padx=8)
                button.grid(row=0, column=i, sticky="ew", padx=2)
            self.workspace.grid(row=1, column=0, columnspan=2, sticky="nsew")
            self.title.configure(font=(self.family, 17, "bold"))
            self.subtitle.grid_remove()
            self.header.configure(padding=(20, 6, 20, 6))
            self.toolbar.grid_configure(pady=(6, 0))
            self.actions.configure(padding=(20, 8, 20, 8))
            self.app.workspace_panes.paneconfigure(self.log_frame, height=100)
        else:
            self.root.columnconfigure(0, weight=0, minsize=rail_width)
            self.root.columnconfigure(1, weight=1)
            self.root.rowconfigure(0, weight=1)
            self.root.rowconfigure(1, weight=0)
            self.rail.grid_propagate(False)
            self.rail.configure(width=rail_width)
            self.rail.grid(row=0, column=0, rowspan=2, sticky="nsew")
            self.rail.columnconfigure(0, weight=1)
            self.rail.columnconfigure(1, weight=0)
            self.rail.rowconfigure(1, weight=1)
            self.brand_name.pack(anchor="w", pady=(8, 0))
            self.brand_name.configure(wraplength=rail_width - 40)
            self.mark.configure(image=self.brand_icons.get(48, ""),
                                text="" if self.brand_icons else tr('文献'), font=(self.family, 23, "bold"))
            self.brand.grid(row=0, column=0, sticky="nw", padx=20, pady=(22, 22))
            self.nav_area.grid(row=1, column=0, sticky="new", padx=10)
            self.nav_area.columnconfigure(0, weight=1)
            self.nav_area.columnconfigure(1, weight=0)
            self.nav_area.columnconfigure(2, weight=0)
            for i, button in enumerate(self.nav_buttons):
                button.configure(text=("01   PDF OCR", tr('02   外文翻译'), tr('03   GitHub 上传'))[i], pady=12, padx=14)
                button.grid(row=i, column=0, sticky="ew", pady=3)
            self.rail_footer.grid(row=2, column=0, sticky="sew", padx=10)
            self.version.pack(anchor="w", padx=14, pady=(4, 16))
            self.workspace.grid(row=0, column=1, rowspan=2, sticky="nsew")
            self.title.configure(font=(self.family, 23, "bold"))
            self.subtitle.grid()
            self.header.configure(padding=(24, 16, 20, 8))
            self.toolbar.grid_configure(pady=(10, 0))
            self.actions.configure(padding=(20, 10, 20, 12))
            self.app.workspace_panes.paneconfigure(self.log_frame, height=155)
        for _, files, options, service in self.forms:
            for box in (files, options, service):
                box.card_body.configure(padding=(14, 10) if compact else (18, 14))
                if box.hint:
                    box.hint.grid_remove() if compact else box.hint.grid()

    def reflow_forms(self):
        wide = self.workspace.winfo_width() >= 760
        for page, files, options, service in self.forms:
            if self.form_columns.get(page) == wide:
                continue
            self.form_columns[page] = wide
            for box in (files, options, service):
                box.grid_forget()
            page.columnconfigure(0, weight=1)
            page.columnconfigure(1, weight=1 if wide else 0)
            if wide:
                files.grid(row=0, column=0, sticky="new", padx=(20, 6), pady=(10, 12))
                options.grid(row=0, column=1, sticky="new", padx=(6, 20), pady=(10, 12))
                service.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 20))
            else:
                for row, box in enumerate((files, options, service)):
                    box.grid(row=row, column=0, sticky="ew", padx=20, pady=(10 if row == 0 else 0, 12))
