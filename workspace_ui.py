"""Desktop workspace layout. Processing and credentials stay in their controllers."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

from literature_processing import LANGUAGES
from literature_ui import LiteratureControls, ModelControls, scrollable_page


COLORS = {
    "canvas": "#f4f3ef", "paper": "#ffffff", "border": "#e1e4de",
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
    style.configure("CardTitle.TLabel", background=COLORS["paper"], font=(family, 11, "bold"))
    style.configure("Card.TLabel", background=COLORS["paper"])
    style.configure("Hint.TLabel", background=COLORS["paper"], foreground=COLORS["muted"], font=(family, 9))
    style.configure("TEntry", fieldbackground=COLORS["paper"], bordercolor=COLORS["border"], padding=8)
    style.map("TEntry", bordercolor=[("focus", COLORS["accent"])])
    style.configure("TCombobox", fieldbackground=COLORS["paper"], arrowsize=12, padding=6)
    style.map("TCombobox", fieldbackground=[("readonly", COLORS["paper"])])
    style.configure("TButton", background=COLORS["paper"], bordercolor=COLORS["border"],
                    relief="flat", padding=(12, 7), focusthickness=1, focuscolor=COLORS["accent"])
    style.map("TButton", background=[("pressed", "#d8e5d9"), ("active", COLORS["soft"])], foreground=[("disabled", COLORS["muted"])])
    style.configure("Accent.TButton", background=COLORS["accent"], foreground="#ffffff",
                    bordercolor=COLORS["accent"], padding=(20, 9), font=(family, 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", "#c4cfc6"), ("pressed", "#173f2f"), ("active", "#21533f")],
              foreground=[("disabled", "#f2f5f2"), ("!disabled", "#ffffff")])
    style.configure("Quiet.TButton", background=COLORS["canvas"], bordercolor=COLORS["canvas"], padding=(8, 6))
    style.configure("TMenubutton", background=COLORS["paper"], bordercolor=COLORS["border"], padding=(10, 7))
    style.configure("TCheckbutton", background=COLORS["paper"], padding=(0, 5))
    style.map("TCheckbutton", background=[("active", COLORS["paper"])])
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
        outer.hint = ttk.Label(body, text=subtitle, style="Hint.TLabel", wraplength=300)
        outer.hint.grid(row=1, column=0, sticky="w", pady=(0, 8))
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
    button = ttk.Button(group, text="选择文件夹", command=command)
    button.grid(row=1, column=1)
    return entry, button


def build_translation_page(controls, saved, fetch, test):
    """Create task options here; advanced service configuration lives in Settings."""
    shell = controls.app.workspace_layout
    page = controls.page
    files, body = card(page, "01   文献文件夹", "扫描已有 Markdown，自动跳过已是目标语言的文献。")
    files.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 12))
    controls.input_entry, _ = path_field(body, 0, "原文位置", controls.input, lambda: controls.choose_dir(controls.input))
    controls.output_entry, controls.output_button = path_field(body, 1, "译文位置", controls.output, lambda: controls.choose_dir(controls.output))
    ttk.Checkbutton(body, text="译文保存在原文所在文件夹", variable=controls.same_folder,
                    command=lambda: shell.sync_output()).grid(row=2, column=0, sticky="w")
    ttk.Checkbutton(body, text="包括子文件夹", variable=controls.recursive).grid(row=3, column=0, sticky="w")

    options, body = card(page, "02   语言与质量", "翻译模型读取前 300 字符识别语言，长文自动分段。")
    options.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
    for row, label, variable, values in ((0, "来源语言", controls.source, ["自动检测"] + list(LANGUAGES)),
                                        (1, "目标语言", controls.target, list(LANGUAGES)),
                                        (2, "文件名标记", controls.prefix, ["前缀 TRANSLATED_", "后缀 _TRANSLATED"])):
        line = ttk.Frame(body, style="Paper.TFrame")
        line.grid(row=row, column=0, sticky="ew", pady=4)
        line.columnconfigure(1, weight=1)
        ttk.Label(line, text=label, style="Card.TLabel", width=10).grid(row=0, column=0, sticky="w")
        ttk.Combobox(line, textvariable=variable, values=values, width=14,
                     state="readonly" if row == 2 else "normal").grid(row=0, column=1, sticky="ew")
    ttk.Separator(body).grid(row=3, column=0, sticky="ew", pady=12)
    ttk.Checkbutton(body, text="二次翻译核对", variable=controls.secondary).grid(row=4, column=0, sticky="w")
    arbitration = ttk.Combobox(body, textvariable=controls.arbitration,
                               values=["用户自行裁决", "大模型裁决"], state="readonly", width=18)
    arbitration.grid(row=5, column=0, sticky="w", padx=(22, 0), pady=(0, 6))
    ttk.Checkbutton(body, text="文本校对", variable=controls.proofreading).grid(row=6, column=0, sticky="w")
    ttk.Label(body, text="有争议的译文会保留并标记为待处理。", style="Hint.TLabel").grid(row=7, column=0, sticky="w", pady=(6, 0))
    summary, body = card(page, "03   处理服务")
    summary.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
    controls.model_summary = tk.StringVar(value="尚未设置翻译模型")
    model_label = ttk.Label(body, textvariable=controls.model_summary, style="Card.TLabel", width=1)
    model_label.grid(row=0, column=0, sticky="ew", pady=5)
    HoverTip(model_label, controls.model_summary.get)
    ttk.Button(body, text="配置模型与上传", command=lambda: shell.show_settings(1)).grid(row=1, column=0, sticky="w", pady=5)
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
            app.log_queue.put(("log", f"无法加载应用图标：{exc}"))
        self.mark = tk.Label(self.brand, text="文献", font=(self.family, 23, "bold"),
                             bg=COLORS["rail"], fg="#eff4eb", bd=0, padx=0, pady=0)
        self.mark.pack(anchor="w")
        self.brand_name = tk.Label(self.brand, text="文献处理软件", font=(self.family, 11, "bold"), bg=COLORS["rail"], fg="#eff4eb")
        self.brand_name.pack(anchor="w", pady=(8, 0))
        self.nav_area = tk.Frame(self.rail, bg=COLORS["rail"])
        self.nav_buttons = []
        for index, title in enumerate(("01   PDF OCR", "02   外文翻译")):
            button = tk.Button(self.nav_area, text=title, anchor="w", relief="flat", bd=0, padx=14, pady=12,
                font=(self.family, 10, "bold"), bg=COLORS["rail"], fg=COLORS["rail_muted"],
                activebackground=COLORS["selected"], activeforeground="#ffffff", cursor="hand2",
                highlightthickness=1, highlightbackground=COLORS["rail"], highlightcolor="#9fc4ab",
                command=lambda i=index: app.notebook.select(i))
            self.nav_buttons.append(button)
        self.rail_footer = tk.Frame(self.rail, bg=COLORS["rail"])
        self.settings_button = tk.Button(self.rail_footer, text="偏好设置", anchor="w", relief="flat", bd=0,
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
        self.title = ttk.Label(header, text="PDF OCR 转 Markdown", style="Title.TLabel")
        self.title.grid(row=0, column=0, sticky="w")
        self.subtitle = ttk.Label(header, text="从扫描文档到可检索的文献。", style="Subtitle.TLabel")
        self.subtitle.grid(row=1, column=0, sticky="w", pady=(5, 0))
        tools = ttk.Menubutton(header, text="更多工具")
        tools.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))
        menu = tk.Menu(tools, tearoff=False)
        for title, command in (("扫描 PDF", app.scan_pdfs), ("扫描 Markdown", lambda: app.literature.scan()),
                               ("修复JSON为MD", app.repair_json_to_md),
                               ("手动字数检验", app.manual_wordcount_check), ("手动LLM检验", app.manual_llm_check),
                               ("打开 OCR 输出目录", app.open_output_dir), ("显示配置位置", app.show_config_path)):
            menu.add_command(label=title, command=command)
        tools.configure(menu=menu)

        app.workspace_panes = tk.PanedWindow(self.workspace, orient="vertical", sashwidth=6,
                                            bg=COLORS["canvas"], bd=0, sashrelief="flat")
        app.workspace_panes.grid(row=1, column=0, sticky="nsew")
        app.notebook = ttk.Notebook(app.workspace_panes, style="Workspace.TNotebook")
        app.workspace_panes.add(app.notebook, minsize=64, stretch="always")
        ocr_page = scrollable_page(app.notebook, "PDF OCR 转 MD功能")
        translation_page = scrollable_page(app.notebook, "外文文献翻译功能")
        app.literature = LiteratureControls(app, translation_page, fetch, test)
        self.build_ocr(ocr_page, model_choices)
        self.build_log()
        self.build_actions()
        app.notebook.bind("<<NotebookTabChanged>>", self.select)
        self.root.bind("<Configure>", self.resize, add="+")
        self.root.bind("<Control-Key-1>", lambda event: app.notebook.select(0))
        self.root.bind("<Control-Key-2>", lambda event: app.notebook.select(1))
        self.resize()
        self.select()
        self.sync_output()

    def build_ocr(self, page, models):
        app = self.app
        files, body = card(page, "01   文档位置", "选择 PDF 所在文件夹，保留原文并生成 Markdown。")
        files.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 12))
        app.input_entry, _ = path_field(body, 0, "PDF 输入文件夹", app.input_var, app.choose_input_dir)
        app.output_entry, _ = path_field(body, 1, "Markdown 输出文件夹", app.output_var, app.choose_output_dir)
        options, body = card(page, "02   处理选项")
        options.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        line = ttk.Frame(body, style="Paper.TFrame")
        line.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        line.columnconfigure(1, weight=1)
        ttk.Label(line, text="OCR 模型", style="Card.TLabel", width=10).grid(row=0, column=0, sticky="w")
        app.model_combo = ttk.Combobox(line, textvariable=app.model_var, values=models, state="readonly", width=14)
        app.model_combo.grid(row=0, column=1, sticky="ew")
        for row, text, variable in ((1, "包括子文件夹", app.recursive_var), (2, "保留子文件夹结构", app.preserve_var),
                                     (3, "覆盖已有 Markdown", app.overwrite_var), (4, "使用 LLM 核验 OCR 质量", app.llm_review_var),
                                     (5, "自动检测外文并翻译", app.literature.auto_translate)):
            ttk.Checkbutton(body, text=text, variable=variable).grid(row=row, column=0, sticky="w")
        ttk.Label(body, text="大于 50MB 的 PDF 会自动拆分并合并结果。", style="Hint.TLabel", wraplength=280).grid(row=6, column=0, sticky="w", pady=(8, 0))
        service, body = card(page, "03   处理服务")
        service.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
        ttk.Label(body, textvariable=app.token_state_var, style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Button(body, text="配置 OCR 与核验", command=lambda: self.show_settings(0)).grid(row=1, column=0, sticky="w", pady=5)
        self.forms.append((page, files, options, service))

    def build_settings(self, controls, saved, fetch, test):
        app = self.app
        self.settings = tk.Toplevel(self.root)
        self.settings.withdraw()
        self.settings.title("偏好设置 · 文献处理软件")
        self.settings.transient(self.root)
        self.settings.columnconfigure(0, weight=1)
        self.settings.rowconfigure(1, weight=1)
        ttk.Label(self.settings, text="连接你的处理服务", style="CardTitle.TLabel", padding=(18, 14)).grid(row=0, column=0, sticky="ew")
        self.settings_tabs = ttk.Notebook(self.settings)
        self.settings_tabs.grid(row=1, column=0, sticky="nsew", padx=12)
        ocr = scrollable_page(self.settings_tabs, "OCR 与核验")
        models = scrollable_page(self.settings_tabs, "翻译模型")
        github = scrollable_page(self.settings_tabs, "GitHub 上传")
        token = ttk.LabelFrame(ocr, text="PaddleOCR", padding=12)
        token.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        ttk.Label(token, textvariable=app.token_state_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=8)
        for row, title, callback in ((1, "输入/更新 Access Token", app.set_token), (2, "检测 API Key 是否有效", app.check_api_key), (3, "清除 Token", app.clear_token)):
            ttk.Button(token, text=title, command=callback).grid(row=row, column=0, sticky="w", pady=4)
        review = ttk.LabelFrame(ocr, text="OCR 质量核验模型", padding=12)
        review.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        review.columnconfigure(1, weight=1)
        for row, title, variable in ((0, "Base URL", app.llm_base_url_var), (1, "API Key", app.llm_api_key_var)):
            ttk.Label(review, text=title).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
            ttk.Entry(review, textvariable=variable, show="*" if row == 1 else "", width=18).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Label(review, text="模型").grid(row=2, column=0, sticky="w", pady=6)
        app.llm_model_combo = ttk.Combobox(review, textvariable=app.llm_model_var, width=18)
        app.llm_model_combo.grid(row=2, column=1, sticky="ew", pady=6)
        app.fetch_models_btn = ttk.Button(review, text="拉取模型列表", command=app.fetch_llm_models)
        app.fetch_models_btn.grid(row=3, column=0, pady=6)
        app.test_llm_api_btn = ttk.Button(review, text="测试LLM API", command=app.test_llm_api)
        app.test_llm_api_btn.grid(row=3, column=1, sticky="w", padx=8)

        roles = ttk.Notebook(models)
        roles.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        for key, title in (("translator", "翻译"), ("reviewer", "二次核对"), ("proofreader", "校对"), ("arbiter", "裁决")):
            tab = ttk.Frame(roles)
            tab.columnconfigure(0, weight=1)
            roles.add(tab, text=title)
            model = ModelControls(tab, title + "模型", saved.get(key, {}), controls.events, fetch, test)
            model.box.grid(row=0, column=0, sticky="ew", padx=6, pady=8)
            controls.profiles[key] = model
            if key == "translator":
                model.model.trace_add("write", lambda *_: controls.model_summary.set(
                    "翻译模型  ·  " + (controls.profiles["translator"].model.get() or "尚未设置")))
        controls.model_summary.set("翻译模型  ·  " + (controls.profiles["translator"].model.get() or "尚未设置"))
        box = ttk.LabelFrame(github, text="核验后的上传", padding=12)
        box.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        box.columnconfigure(1, weight=1)
        ttk.Checkbutton(box, text="自动上传核验通过的 Markdown", variable=controls.upload).grid(row=0, column=0, columnspan=2, sticky="w", pady=6)
        for row, title, variable in ((1, "仓库", controls.repository), (2, "已有分支", controls.branch),
                                     (3, "仓库内目录", controls.folder), (4, "Token", controls.github_token)):
            ttk.Label(box, text=title).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            ttk.Entry(box, textvariable=variable, show="*" if row == 4 else "", width=18).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Label(box, text="仓库格式：owner/repository。Token 仅用于本次运行。\n需 Contents 写入权限；不会覆盖远端同名文件。",
                  wraplength=360, style="Subtitle.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=12)
        footer = ttk.Frame(self.settings, padding=12)
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, text="模型密钥保存在本机配置，请勿共享。", style="Subtitle.TLabel", wraplength=270).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="保存并返回", style="Accent.TButton", command=self.close_settings).grid(row=0, column=1, padx=(8, 0))
        self.settings.protocol("WM_DELETE_WINDOW", self.close_settings)
        self.settings.bind("<Escape>", lambda event: self.close_settings())

    def show_settings(self, tab=0):
        self.settings_tabs.select(tab)
        width = min(680, self.root.winfo_screenwidth() - 60)
        height = min(650, self.root.winfo_screenheight() - 80)
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
            messagebox.showerror("无法保存设置", str(exc), parent=self.settings)
            return
        self.settings.withdraw()

    def sync_output(self):
        controls = self.app.literature
        controls.output_entry.configure(state="disabled" if controls.same_folder.get() else "normal")
        controls.output_button.configure(state="disabled" if controls.same_folder.get() else "normal")

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
        tk.Label(self.log_header, text="运行日志", bg=COLORS["log"], fg="#adbcaf", font=(self.family, 9),
                 anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 12))
        app.log_text = tk.Text(self.log_frame, height=5, width=20, wrap="word", bg=COLORS["log"],
                              fg=COLORS["log_text"], relief="flat", bd=0, highlightthickness=0,
                              padx=16, pady=3, spacing3=3, font="TkTextFont", state="disabled")
        app.log_text.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        scrollbar = ttk.Scrollbar(self.log_frame, command=app.log_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(0, 8))
        app.log_text.configure(yscrollcommand=scrollbar.set)
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
        app.status_label = ttk.Label(self.actions, textvariable=app.status_var, width=1, style="Subtitle.TLabel")
        app.status_label.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.status_tip = HoverTip(app.status_label, app.status_var.get)
        app.start_btn = ttk.Button(self.actions, text="开始 OCR", style="Accent.TButton", command=app.start_batch)
        app.start_btn.grid(row=1, column=3)
        app.literature.start_button = ttk.Button(self.actions, text="开始翻译", style="Accent.TButton", command=app.literature.start)
        app.literature.start_button.grid(row=1, column=3)
        app.stop_btn = ttk.Button(self.actions, text="停止", width=4, command=app.request_stop, state="disabled")
        app.stop_btn.grid(row=1, column=2, padx=(0, 8))
        self.translation_stop = ttk.Button(self.actions, text="停止", width=4, command=app.literature.stop, state="disabled")
        self.translation_stop.grid(row=1, column=2, padx=(0, 8))
        app.manual_query_btn = ttk.Button(self.actions, text="查询", width=4, command=app.manual_query_current_result, state="disabled")
        app.manual_query_btn.grid(row=1, column=1, padx=(0, 8))
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
        self.title.configure(text="PDF OCR 转 Markdown" if index == 0 else "外文文献翻译")
        self.subtitle.configure(text="从扫描文档到可检索的文献。" if index == 0 else "保留原意，让文献跨越语言。")
        app.start_btn.grid_remove()
        app.literature.start_button.grid_remove()
        app.stop_btn.grid_remove()
        self.translation_stop.grid_remove()
        app.manual_query_btn.grid_remove()
        if index == 0:
            app.start_btn.grid()
            app.stop_btn.grid()
            app.manual_query_btn.grid()
        else:
            app.literature.start_button.grid()
            self.translation_stop.grid()

    def resize(self, event=None):
        if event is not None and event.widget != self.root:
            return
        compact = self.root.winfo_width() < 850
        self.reflow_forms()
        if compact == self.compact:
            return
        self.compact = compact
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
                                text="" if self.brand_icons else "文献", font=(self.family, 11, "bold"))
            self.brand.grid(row=0, column=0, sticky="w", padx=14)
            self.rail_footer.grid(row=0, column=2, sticky="e", padx=8)
            self.version.pack_forget()
            self.nav_area.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
            for i, button in enumerate(self.nav_buttons):
                self.nav_area.columnconfigure(i, weight=1)
                button.configure(text=("PDF OCR", "外文翻译")[i], pady=8, padx=8)
                button.grid(row=0, column=i, sticky="ew", padx=2)
            self.workspace.grid(row=1, column=0, columnspan=2, sticky="nsew")
            self.title.configure(font=(self.family, 17, "bold"))
            self.subtitle.grid_remove()
            self.header.configure(padding=(20, 8, 20, 8))
            self.app.workspace_panes.paneconfigure(self.log_frame, height=100)
        else:
            self.root.columnconfigure(0, weight=0, minsize=184)
            self.root.columnconfigure(1, weight=1)
            self.root.rowconfigure(0, weight=1)
            self.root.rowconfigure(1, weight=0)
            self.rail.grid_propagate(False)
            self.rail.configure(width=184)
            self.rail.grid(row=0, column=0, rowspan=2, sticky="nsew")
            self.rail.columnconfigure(0, weight=1)
            self.rail.columnconfigure(1, weight=0)
            self.rail.rowconfigure(1, weight=1)
            self.brand_name.pack(anchor="w", pady=(8, 0))
            self.mark.configure(image=self.brand_icons.get(48, ""),
                                text="" if self.brand_icons else "文献", font=(self.family, 23, "bold"))
            self.brand.grid(row=0, column=0, sticky="nw", padx=22, pady=(28, 30))
            self.nav_area.grid(row=1, column=0, sticky="new", padx=10)
            self.nav_area.columnconfigure(0, weight=1)
            self.nav_area.columnconfigure(1, weight=0)
            for i, button in enumerate(self.nav_buttons):
                button.configure(text=("01   PDF OCR", "02   外文翻译")[i], pady=12, padx=14)
                button.grid(row=i, column=0, sticky="ew", pady=3)
            self.rail_footer.grid(row=2, column=0, sticky="sew", padx=10)
            self.version.pack(anchor="w", padx=14, pady=(4, 16))
            self.workspace.grid(row=0, column=1, rowspan=2, sticky="nsew")
            self.title.configure(font=(self.family, 23, "bold"))
            self.subtitle.grid()
            self.header.configure(padding=(24, 16, 20, 8))
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
