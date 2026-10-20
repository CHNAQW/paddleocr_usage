"""Guided GitHub destination setup. Network checks run off the Tk thread."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from task_runtime import drain_events

from tkinter import font as tkfont
import webbrowser
from pathlib import Path, PurePosixPath
from tkinter import ttk

from literature_processing import (GitHubOptions, GitHubSetupClient, UPLOAD_KINDS, ProcessingCancelled,
    document_upload_evidence, scan_missing_documents, upload_verified_file, github_folder_name, github_repository_name)
from literature_ui import scrollable_page, update_in_progress
from responsive_ui import AdaptiveCheckbutton, AdaptiveLabel, ButtonToolbar, ResponsiveForm
from ui_i18n import LocalizedVar, filedialog, messagebox, localize_widgets, tr


class GitHubSetup:
    def __init__(self, parent, controls):
        self.controls = controls
        self.wizard = None
        self.manual = None
        box = ttk.LabelFrame(parent, text=tr("GitHub 上传设置"), padding=16)
        box.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        box.columnconfigure(0, weight=1)
        AdaptiveLabel(box, text=tr("跟随四步向导连接 GitHub，选择文件要保存到的仓库。"),
                      style="Subtitle.TLabel").grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.summary = LocalizedVar(master=parent)
        AdaptiveLabel(box, textvariable=self.summary).grid(row=1, column=0, sticky="ew", pady=8)
        ttk.Button(box, text=tr("打开上传设置向导"), style="Accent.TButton", command=self.open).grid(row=2, column=0, sticky="w", pady=8)
        AdaptiveCheckbutton(box, text=tr("自动上传核验通过的 Markdown"), variable=controls.upload,
                        style="Wizard.TCheckbutton", command=self.toggle).grid(row=3, column=0, sticky="ew", pady=6)
        form = ResponsiveForm(box)
        form.grid(row=4, column=0, sticky="ew", pady=8)
        combo = ttk.Combobox(form, textvariable=controls.upload_kind, state="readonly", values=[tr(v) for v in UPLOAD_KINDS])
        combo.localized_choices = UPLOAD_KINDS
        form.add(tr("上传内容"), combo)
        ttk.Button(box, text=tr("手动扫描与补传"), command=self.open_manual).grid(row=5, column=0, sticky="w", pady=8)
        AdaptiveLabel(box, text=tr("手动补传会比较目标仓库，仅上传远端缺少且核验通过的 Markdown。上传内容选项也适用于自动上传。"),
                      style="Subtitle.TLabel").grid(row=6, column=0, sticky="ew", pady=8)
        AdaptiveLabel(box, text=tr("访问凭据只在本次运行中使用。下次启动时，向导会保留仓库和保存位置。"),
                      style="Subtitle.TLabel").grid(row=7, column=0, sticky="ew", pady=8)
        self.traces = []
        for variable in (controls.repository, controls.branch, controls.folder, controls.github_token, controls.upload):
            self.traces.append((variable, variable.trace_add("write", self.refresh)))
        self.refresh()

    def refresh(self, *_):
        c = self.controls
        if not c.repository.get():
            text = tr("尚未设置上传位置。点击向导开始，通常只需连接一次并选择仓库。")
        else:
            text = tr("上传位置：{arg0}\n分支：{arg1}\n文件夹：{arg2}",
                      arg0=c.repository.get(), arg1=c.branch.get(), arg2=c.folder.get() or tr("仓库根目录"))
            if not c.github_token.get().strip():
                text += tr("\n本次尚未连接 GitHub，请打开向导粘贴访问凭据。")
        self.summary.set(text)

    def toggle(self):
        c = self.controls
        if c.upload.get():
            try:
                GitHubOptions(c.repository.get(), c.github_token.get(), c.branch.get(), c.folder.get()).validate()
            except ValueError:
                c.upload.set(False)
                self.open()

    def open(self):
        if self.wizard is not None and self.wizard.window.winfo_exists():
            settings = self.controls.app.workspace_layout.settings
            self.wizard.window.transient(settings if settings.winfo_viewable() else self.controls.app.root)
            self.wizard.window.deiconify()
            self.wizard.window.lift()
            return
        self.wizard = GitHubWizard(self)

    def open_manual(self):
        shell = self.controls.app.workspace_layout
        if getattr(shell, "github_manual", None) is not None:
            shell.app.notebook.select(2)
            shell.settings.withdraw()
            shell.root.lift()
            return
        try:
            GitHubOptions(self.controls.repository.get(), self.controls.github_token.get(),
                          self.controls.branch.get(), self.controls.folder.get()).validate()
        except ValueError:
            self.open()
            return
        if self.manual is not None and not self.manual.closed:
            self.manual.window.lift()
            return
        self.manual = ManualUpload(self)


class GitHubWizard:
    def __init__(self, owner):
        self.owner, self.controls = owner, owner.controls
        self.app = self.controls.app
        settings = self.app.workspace_layout.settings
        parent = settings if settings.winfo_viewable() else self.app.root
        self.window = tk.Toplevel(parent)
        self.window.title(tr("GitHub 上传设置向导"))
        self.window.transient(parent)
        self.window.minsize(480, 420)
        width = min(720, self.window.winfo_screenwidth() - 40)
        height = min(700, self.window.winfo_screenheight() - 60)
        self.window.geometry(f"{width}x{height}")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        self.events = queue.Queue()
        self.generation = 0
        self.cancel = threading.Event()
        self.busy = False
        self.closed = False
        self.checked = None
        self.loaded_repository = self.controls.repository.get()
        self.step = 0
        self.titles = (tr("连接 GitHub"), tr("选择仓库"), tr("选择保存位置"), tr("确认上传设置"))
        self.token = tk.StringVar(master=self.window, value=self.controls.github_token.get())
        self.repository = tk.StringVar(master=self.window, value=self.controls.repository.get())
        self.branch = tk.StringVar(master=self.window, value=self.controls.branch.get())
        self.folder = tk.StringVar(master=self.window, value=self.controls.folder.get())
        self.enabled = tk.BooleanVar(master=self.window, value=True)
        self.account = LocalizedVar(master=self.window)
        self.progress = LocalizedVar(master=self.window)
        self.status = LocalizedVar(master=self.window)
        self.review = LocalizedVar(master=self.window)
        self.browser_location = LocalizedVar(master=self.window)
        self.browser_path = ""
        self.traces = []

        header = ttk.Frame(self.window, padding=(20, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        AdaptiveLabel(header, text=tr("GitHub 上传设置向导"), style="WizardTitle.TLabel").grid(row=0, column=0, sticky="ew")
        AdaptiveLabel(header, textvariable=self.progress, style="WizardStep.TLabel").grid(row=1, column=0, sticky="ew", pady=(8, 10))
        style = ttk.Style(self.window)
        progress_track = tk.Frame(header, height=4, bg=style.lookup("Horizontal.TProgressbar", "troughcolor"))
        progress_track.grid(row=2, column=0, sticky="ew")
        progress_track.grid_propagate(False)
        self.step_progress = tk.Frame(progress_track, bg=style.lookup("Horizontal.TProgressbar", "background"))
        self.step_progress.place(x=0, y=0, relwidth=0, relheight=1)
        self.pages = ttk.Notebook(self.window, style="Workspace.TNotebook")
        self.pages.grid(row=1, column=0, sticky="nsew", padx=8)
        self.frames = [scrollable_page(self.pages, title) for title in self.titles]
        self.build_connection(self.frames[0])
        self.build_repository(self.frames[1])
        self.build_destination(self.frames[2])
        self.build_review(self.frames[3])
        footer = ttk.Frame(self.window, padding=(20, 12))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        AdaptiveLabel(footer, textvariable=self.status, max_lines=3, style="Subtitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self.navigation = ButtonToolbar(footer, ((tr("取消设置"), self.close), (tr("上一步"), self.back), (tr("下一步"), self.next)))
        self.navigation.grid(row=1, column=0, sticky="ew")
        _, self.back_button, self.next_button = self.navigation.buttons
        self.next_button.configure(style="Accent.TButton")
        for variable in (self.token, self.repository, self.branch, self.folder):
            self.traces.append((variable, variable.trace_add("write", self.dirty)))
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self.cleanup, add="+")
        self.window.bind("<Escape>", lambda event: self.close())
        localize_widgets(self.window)
        self.show(0)
        self.poll_id = self.window.after(60, self.poll)
        self.window.grab_set()

    def intro(self, parent, title, explanation):
        parent.configure(padding=(12, 8))
        AdaptiveLabel(parent, text=title, style="WizardHeading.TLabel").grid(row=0, column=0, sticky="ew", pady=(0, 10))
        AdaptiveLabel(parent, text=explanation, style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=(0, 14))

    def build_connection(self, parent):
        self.intro(parent, tr("先让软件连接你的 GitHub 账号"),
                   tr("点击下方按钮在浏览器创建访问凭据（Token），复制后粘贴到这里。已有凭据可直接粘贴。"))
        ttk.Button(parent, text=tr("在 GitHub 创建访问凭据"), command=lambda: webbrowser.open(
            "https://github.com/settings/personal-access-tokens/new")).grid(row=2, column=0, sticky="w", pady=6)
        AdaptiveLabel(parent, text=tr("创建时选择目标仓库的所属账号，在 Repository access 中选择该仓库，并把 Repository permissions → Contents 设为 Read and write。完成后点击 Generate token。"),
                      style="Subtitle.TLabel").grid(row=3, column=0, sticky="ew", pady=10)
        form = ResponsiveForm(parent, style="TFrame")
        form.grid(row=4, column=0, sticky="ew")
        self.token_entry = ttk.Entry(form, textvariable=self.token, show="*")
        form.add(tr("访问凭据（Token）"), self.token_entry)
        AdaptiveLabel(parent, text=tr("连接检查只读取账号和仓库信息，不上传文件；凭据不会写入配置文件。"),
                      style="Subtitle.TLabel").grid(row=5, column=0, sticky="ew", pady=12)

    def build_repository(self, parent):
        self.intro(parent, tr("选择文献要上传到哪个仓库"),
                   tr("从列表中选择，或直接粘贴 GitHub 仓库链接。这里只显示当前凭据可访问的可用仓库。"))
        AdaptiveLabel(parent, textvariable=self.account).grid(row=2, column=0, sticky="ew", pady=8)
        form = ResponsiveForm(parent, style="TFrame")
        form.grid(row=3, column=0, sticky="ew")
        self.repo_combo = ttk.Combobox(form, textvariable=self.repository)
        form.add(tr("目标仓库或仓库链接"), self.repo_combo)
        ttk.Button(parent, text=tr("还没有仓库？在 GitHub 新建"), command=lambda: webbrowser.open(
            "https://github.com/new")).grid(row=4, column=0, sticky="w", pady=12)
        AdaptiveLabel(parent, text=tr("新建仓库时勾选 Add a README file，再把仓库链接粘贴到上方。组织仓库可能需要管理员批准访问凭据。"),
                      style="Subtitle.TLabel").grid(row=5, column=0, sticky="ew", pady=8)

    def build_destination(self, parent):
        self.intro(parent, tr("选择仓库内的保存位置"),
                   tr("默认已选中仓库的主分支。文件夹留空即保存在仓库根目录，也可浏览已有文件夹或填写新目录。"))
        form = ResponsiveForm(parent, style="TFrame")
        form.grid(row=2, column=0, sticky="ew")
        self.branch_combo = ttk.Combobox(form, textvariable=self.branch, state="readonly")
        form.add(tr("保存到哪个分支"), self.branch_combo)
        form.add(tr("保存到哪个文件夹（可留空）"), ttk.Entry(form, textvariable=self.folder))
        AdaptiveLabel(parent, text=tr("例如 papers/2026。新文件夹会在首个文件上传时自动创建。"),
                      style="Subtitle.TLabel").grid(row=3, column=0, sticky="ew", pady=8)
        self.browse_button = ttk.Button(parent, text=tr("浏览已有文件夹"), command=lambda: self.browse(""))
        self.browse_button.grid(row=4, column=0, sticky="w", pady=6)
        self.browser = ttk.Frame(parent)
        self.browser.columnconfigure(0, weight=1)
        AdaptiveLabel(self.browser, textvariable=self.browser_location).grid(row=0, column=0, columnspan=2, sticky="ew", pady=5)
        self.directory_list = ttk.Treeview(self.browser, show="tree", height=4, selectmode="browse")
        self.directory_list.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.directory_list.bind("<<TreeviewSelect>>", self.select_folder)
        self.directory_list.bind("<Double-1>", lambda event: self.open_selected())
        ttk.Button(self.browser, text=tr("打开所选文件夹"), command=self.open_selected).grid(row=2, column=0, sticky="w", pady=8)
        ttk.Button(self.browser, text=tr("返回上一级"), command=self.up).grid(row=2, column=1, sticky="e", pady=8)
        ttk.Button(parent, text=tr("使用仓库根目录"), command=lambda: self.folder.set("")).grid(row=6, column=0, sticky="w", pady=6)
        self.branch_combo.bind("<<ComboboxSelected>>", lambda event: self.browser.grid_remove())

    def build_review(self, parent):
        self.intro(parent, tr("确认后再启用自动上传"),
                   tr("连接检查已确认仓库和分支可访问。请确认创建凭据时已允许写入所选仓库；实际写入权限会在上传时校验。"))
        AdaptiveLabel(parent, textvariable=self.review).grid(row=2, column=0, sticky="ew", pady=12)
        AdaptiveCheckbutton(parent, text=tr("自动上传核验通过的 Markdown"), variable=self.enabled,
                        style="Wizard.TCheckbutton").grid(row=3, column=0, sticky="ew", pady=10)
        AdaptiveLabel(parent, text=tr("只上传通过核验的 Markdown；原 PDF、访问凭据和检查报告不会上传。远端已有同名文件会保留。"),
                      style="Subtitle.TLabel").grid(row=4, column=0, sticky="ew", pady=12)

    def dirty(self, *_):
        self.checked = None
        self.cancel.set()
        self.generation += 1
        self.busy = False
        self.status.set("")
        self.update_buttons()

    def update_buttons(self):
        self.back_button.configure(state="normal" if self.step else "disabled")
        self.next_button.configure(state="disabled" if self.busy else "normal",
                                   text=tr("保存设置") if self.step == 3 else tr("连接并继续") if self.step == 0 else tr("下一步"))

        self.navigation.schedule()

    def show(self, step):
        self.step = step
        self.pages.select(step)
        self.progress.set(tr("第 {arg0} / 4 步 · {arg1}", arg0=step + 1, arg1=self.titles[step]))
        self.step_progress.place_configure(relwidth=(step + 1) / 4)
        self.status.set("")
        self.update_buttons()

    def options(self):
        return GitHubOptions(github_repository_name(self.repository.get()), self.token.get().strip(),
                             self.branch.get().strip(), github_folder_name(self.folder.get()))

    def next(self):
        if self.busy:
            return
        try:
            if self.step == 0:
                if not self.token.get().strip():
                    raise ValueError(tr("请先粘贴 GitHub 访问凭据（Token）。"))
                self.run(lambda client: client.connect(), self.connected)
            elif self.step == 1:
                repository = github_repository_name(self.repository.get())
                self.run(lambda client: client.prepare_repository(repository), self.prepared)
            elif self.step == 2:
                options = self.options()
                options.validate()
                self.run(lambda client: client.check_destination(options), lambda result: self.checked_destination(options))
            else:
                self.finish()
        except Exception as exc:
            self.status.set(exc.args[0] if exc.args else str(exc))

    def connected(self, result):
        self.account.set(tr("已连接账号：{arg0}", arg0=result["login"]))
        self.repo_combo.configure(values=result["repositories"])
        if not self.repository.get() and result["repositories"]:
            self.repository.set(result["repositories"][0])
        self.show(1)

    def prepared(self, result):
        current = self.branch.get()
        keep_branch = result["repository"] == self.loaded_repository and current in result["branches"]
        self.repository.set(result["repository"])
        self.branch_combo.configure(values=result["branches"])
        self.branch.set(current if keep_branch else result["default_branch"] if result["default_branch"] in result["branches"] else result["branches"][0])
        self.loaded_repository = result["repository"]
        self.browser.grid_remove()
        self.show(2)

    def checked_destination(self, options):
        self.checked = options
        self.review.set(tr("上传位置：{arg0}\n分支：{arg1}\n文件夹：{arg2}",
                           arg0=options.repository, arg1=options.branch, arg2=options.folder or tr("仓库根目录")))
        self.show(3)

    def browse(self, folder):
        try:
            repository, branch = github_repository_name(self.repository.get()), self.branch.get()
            self.run(lambda client: client.folders(repository, branch, folder), lambda rows: self.show_folders(folder, rows))
        except Exception as exc:
            self.status.set(exc.args[0] if exc.args else str(exc))

    def show_folders(self, folder, rows):
        self.browser_path = folder
        self.browser_location.set(tr("正在浏览：{arg0}", arg0=folder or tr("仓库根目录")))
        self.directory_list.delete(*self.directory_list.get_children())
        for index, path in enumerate(rows):
            self.directory_list.insert("", "end", iid=str(index), text=PurePosixPath(path).name, values=(path,))
        self.browser.grid(row=5, column=0, sticky="ew", pady=8)
        self.folder.set(folder)
        if not rows:
            self.status.set(tr("此位置没有子文件夹，可使用当前位置或填写新文件夹名称。"))

    def select_folder(self, _event=None):
        selection = self.directory_list.selection()
        if selection:
            self.folder.set(self.directory_list.item(selection[0], "values")[0])

    def open_selected(self):
        selection = self.directory_list.selection()
        if selection:
            self.browse(self.directory_list.item(selection[0], "values")[0])

    def up(self):
        parent = str(PurePosixPath(self.browser_path).parent)
        self.browse("" if parent == "." else parent)

    def run(self, request, completed):
        if self.closed or update_in_progress(self.app):
            return
        self.cancel.set()
        self.cancel = threading.Event()
        self.generation += 1
        generation = self.generation
        client = GitHubSetupClient(self.token.get().strip(), self.cancel.is_set)
        self.completed = completed
        self.busy = True
        self.status.set(tr("正在读取 GitHub 信息，请稍候……"))
        self.update_buttons()
        events = self.events
        def worker():
            try:
                result, error = request(client), None
            except Exception as exc:
                result, error = None, exc.args[0] if exc.args else str(exc)
            events.put((generation, result, error))
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def poll(self):
        if self.closed:
            return
        try:
            for generation, result, error in drain_events(self.events):
                if generation != self.generation:
                    continue
                self.busy = False
                self.update_buttons()
                if error is not None:
                    self.status.set(error)
                else:
                    self.status.set("")
                    self.completed(result)
        except queue.Empty:
            pass
        except Exception as exc:
            self.busy = False
            self.status.set(tr("后台事件处理失败：{arg0}", arg0=exc))
            self.update_buttons()
        self.poll_id = self.window.after(60, self.poll)

    def back(self):
        self.dirty()
        self.show(max(0, self.step - 1))

    def finish(self):
        options = self.options()
        if self.checked is None or options != self.checked:
            self.show(2)
            self.status.set(tr("设置已改变，请重新点击下一步检查上传位置。"))
            return
        c = self.controls
        previous = (c.repository.get(), c.github_token.get(), c.branch.get(), c.folder.get(), c.upload.get())
        variables = (c.repository, c.github_token, c.branch, c.folder, c.upload)
        values = (options.repository, options.token, options.branch, options.folder, self.enabled.get())
        try:
            for variable, value in zip(variables, values):
                variable.set(value)
            self.app.save_current_config()
        except Exception:
            for variable, value in zip(variables, previous):
                variable.set(value)
            self.app.config.literature = c.config_data()
            raise
        self.owner.refresh()
        self.close()

    def cleanup(self, event=None):
        if self.closed or (event is not None and event.widget != self.window):
            return
        self.closed = True
        self.cancel.set()
        self.generation += 1
        self.window.after_cancel(self.poll_id)
        for variable, trace in self.traces:
            variable.trace_remove("write", trace)
        self.traces.clear()

    def close(self):
        if self.closed:
            return
        self.cleanup()
        self.window.grab_release()
        self.window.destroy()


class ManualUpload:
    """Compare first, then let the user upload the selected, positively reviewed files."""
    def __init__(self, owner, parent=None):
        self.owner, self.controls = owner, owner.controls
        self.app = self.controls.app
        self.embedded = parent is not None
        self.window = ttk.Frame(parent) if self.embedded else tk.Toplevel(self.app.workspace_layout.settings)
        if self.embedded:
            self.window.grid(row=0, column=0, sticky="nsew")
        else:
            self.window.title(tr("手动扫描与补传"))
            self.window.geometry("820x650")
            self.window.minsize(480, 420)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1, minsize=100)
        self.closed, self.busy = False, False
        self.worker_thread = None
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.candidates, self.checked = [], None
        self.extra_buttons = []
        self.render_timer = None
        self.render_generation = 0
        page = ttk.Frame(self.window, padding=16)
        page.grid(row=0, column=0, sticky="ew")
        page.columnconfigure(0, weight=1)
        AdaptiveLabel(page, text=tr("先比较，再补传"), style="WizardHeading.TLabel").grid(row=0, column=0, sticky="ew")
        self.intro = AdaptiveLabel(page, text=tr("选择包含原文和译文的本地文件夹。列表默认选中远端缺少且核验通过的文档；可按 Ctrl / Shift 调整选择。"),
                      style="Subtitle.TLabel")
        self.intro.grid(row=1, column=0, sticky="ew", pady=8)
        form = ResponsiveForm(page)
        form.grid(row=2, column=0, sticky="ew")
        path_box = ttk.Frame(form)
        path_box.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(path_box, textvariable=self.controls.upload_root, width=1)
        self.folder_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = ttk.Button(path_box, text=tr("选择文件夹"), command=self.browse)
        self.browse_button.grid(row=0, column=1, padx=(8, 0))
        form.add(tr("本地文档位置"), path_box)
        self.kind_combo = ttk.Combobox(form, textvariable=self.controls.upload_kind, state="readonly", values=[tr(v) for v in UPLOAD_KINDS])
        self.kind_combo.localized_choices = UPLOAD_KINDS
        form.add(tr("上传内容"), self.kind_combo)
        self.destination = LocalizedVar(master=self.window)
        destination_label = AdaptiveLabel(page, textvariable=self.destination, style="Subtitle.TLabel", max_lines=2)
        destination_label.grid(row=3, column=0, sticky="ew", pady=8)
        from workspace_ui import HoverTip
        HoverTip(destination_label, self.destination.get)
        frame = ttk.Frame(self.window, padding=(16, 0))
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("role", "status"), selectmode="extended", height=8)
        self.tree.column("#0", width=350, minwidth=100)
        self.tree.column("role", width=100, minwidth=85, stretch=False)
        self.tree.column("status", width=200, minwidth=140)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar = ttk.Scrollbar(frame, command=self.tree.yview)
        ybar.grid(row=0, column=1, sticky="ns")
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        xbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        footer = ttk.Frame(self.window, padding=16)
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status = LocalizedVar(master=self.window, value=tr("点击扫描，将只读取远端目录，尚不会上传。"))
        AdaptiveLabel(footer, textvariable=self.status, max_lines=2).grid(row=0, column=0, sticky="ew", pady=8)
        toolbar = ButtonToolbar(footer, ((tr("扫描缺失文档"), self.scan), (tr("上传选中文档"), self.upload), (tr("停止"), self.cancel.set)))
        toolbar.grid(row=1, column=0, sticky="ew")
        self.scan_button, self.upload_button, self.stop_button = toolbar.buttons
        if self.embedded:
            footer.grid_remove()  # Embedded tasks use the workspace's fixed action bar.
        self.traces = []
        for var in (self.controls.upload_root, self.controls.upload_kind, self.controls.repository,
                    self.controls.branch, self.controls.folder, self.controls.github_token):
            self.traces.append((var, var.trace_add("write", self.invalidate)))
        self.window.bind("<Destroy>", self.cleanup, add="+")
        self.window.bind("<Configure>", self.resize, add="+")
        self.pending = self.app.root.after(100, self.poll)
        self.render()
        self.buttons()
        localize_widgets(self.window)

    def signature(self):
        c = self.controls
        return (c.upload_root.get(), c.upload_kind.get(), c.repository.get(), c.branch.get(), c.folder.get(), c.github_token.get())

    def invalidate(self, *_):
        if self.checked == self.signature():
            return  # A language refresh only changes the displayed ChoiceVar value.
        self.cancel.set()
        self.checked, self.candidates = None, []
        self.render()
        self.status.set(tr("设置已变化，请重新扫描后上传。"))
        self.buttons()

    def browse(self):
        value = filedialog.askdirectory(parent=self.window.winfo_toplevel(), title=tr("选择文件夹"), initialdir=self.controls.upload_root.get() or None)
        if value:
            self.controls.upload_root.set(value)

    def buttons(self):
        for scan, upload, stop in [(self.scan_button, self.upload_button, self.stop_button)] + self.extra_buttons:
            scan.configure(state="disabled" if self.busy else "normal")
            upload.configure(state="normal" if not self.busy and self.render_timer is None and any(c.status == "ready" for c in self.candidates) else "disabled")
            stop.configure(state="normal" if self.busy else "disabled")
        self.folder_entry.configure(state="disabled" if self.busy else "normal")
        self.browse_button.configure(state="disabled" if self.busy else "normal")
        self.kind_combo.configure(state="disabled" if self.busy else "readonly")

    def render(self, auto_select=False):
        if self.render_timer is not None:
            self.app.root.after_cancel(self.render_timer)
            self.render_timer = None
        self.render_generation += 1
        generation = self.render_generation
        c = self.controls
        self.destination.set(tr("目标：{arg0} · {arg1} / {arg2}", arg0=c.repository.get(), arg1=c.branch.get(), arg2=c.folder.get() or tr("仓库根目录")))
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self.tree.heading("#0", text=tr("相对路径"))
        self.tree.heading("role", text=tr("文档类型"))
        self.tree.heading("status", text=tr("处理状态"))
        font = tkfont.nametofont("TkDefaultFont")
        role_width = max(font.measure(str(v)) for v in (tr("文档类型"), tr("翻译稿"), tr("原文"))) + 24
        self.tree.column("role", width=role_width, minwidth=role_width)
        self.tree.column("#0", minwidth=font.measure(str(tr("相对路径"))) + 24)
        self.tree.column("status", minwidth=font.measure(str(tr("需重新核验文件指纹"))) + 24)
        labels = {"ready": tr("可以补传"), "existing": tr("远端已有，跳过"), "unverified": tr("尚未核验通过"),
                  "changed": tr("需重新核验文件指纹"), "oversize": tr("超过 20 MB"),
                  "uploaded": tr("上传完成"), "failed": tr("上传失败，文件保留本地")}
        def batch(start=0):
            self.render_timer = None
            if self.closed or generation != self.render_generation:
                return
            end = min(start + 100, len(self.candidates))
            chosen = []
            for i in range(start, end):
                item = self.candidates[i]
                self.tree.insert("", "end", iid=str(i), text=item.relative,
                                 values=(tr("翻译稿") if item.role == "translation" else tr("原文"), labels[item.status]))
                if str(i) in selected or (auto_select and item.status == "ready"):
                    chosen.append(str(i))
            if chosen:
                self.tree.selection_add(chosen)
            if end < len(self.candidates):
                self.render_timer = self.app.root.after(1, lambda: batch(end))
            self.buttons()
        batch()

    def resize(self, event=None):
        if event is None or event.widget == self.window:
            height = self.app.root.winfo_height() if self.embedded else self.window.winfo_height()
            if height < 560:
                self.intro.grid_remove()
            else:
                self.intro.grid()

    def launch(self, work, kind):
        self.cancel.clear()
        self.busy = True
        def worker():
            try:
                self.events.put((kind, work()))
            except Exception as exc:
                self.events.put(("error", exc))
            finally:
                self.events.put(("done", None))
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()
        self.buttons()

    def scan(self):
        if self.closed or self.busy or update_in_progress(self.app):
            return
        self.checked = self.signature()
        root, kind, repo, branch, folder, token = self.checked
        options = GitHubOptions(repo, token, branch, folder)
        try:
            options.validate()
        except ValueError:
            self.checked = None
            self.owner.open()
            return
        self.candidates = []
        self.render()
        self.status.set(tr("正在比较本地文档与远端目录……"))
        self.launch(lambda: scan_missing_documents(root, kind, options, stop=self.cancel.is_set), "scan")

    def upload(self):
        if self.closed or self.busy or self.render_timer is not None or update_in_progress(self.app) or self.checked != self.signature():
            return
        selected = [(int(i), self.candidates[int(i)]) for i in self.tree.selection() if self.candidates[int(i)].status == "ready"]
        if not selected:
            messagebox.showinfo(tr("请选择文档"), tr("请先选择可以补传的文档。"), parent=self.window.winfo_toplevel())
            return
        _, kind, repo, branch, folder, token = self.checked
        if not messagebox.askyesno(tr("确认手动上传"), tr("将向 {arg0}（{arg1} / {arg2}）上传 {arg3} 个选中文档。\n上传内容：{arg4}\n远端已有文件会跳过。是否继续？",
                arg0=repo, arg1=branch, arg2=folder or tr("仓库根目录"), arg3=len(selected), arg4=tr(kind)), parent=self.window.winfo_toplevel()):
            return
        try:
            self.app.save_current_config()
        except Exception as exc:
            self.status.set(tr("无法开始上传：{arg0}", arg0=exc))
            return
        options = GitHubOptions(repo, token, branch, folder)
        self.status.set(tr("正在上传选中文档……"))
        def work():
            counts = {"uploaded": 0, "existing": 0, "failed": 0}
            for index, item in selected:
                if self.cancel.is_set():
                    break
                try:
                    role, status, digest = document_upload_evidence(item.path)
                    if status != "ready" or digest != item.sha256 or role != item.role:
                        raise ValueError(tr("核验后文件发生变化，请重新核验再上传。"))
                    remote = upload_verified_file(item.path, item.relative, True, options, item.sha256, self.cancel.is_set)
                    self.controls.log(tr("GitHub 上传成功：{arg0}", arg0=remote))
                    state = "uploaded"
                except ProcessingCancelled:
                    break
                except FileExistsError:
                    state = "existing"
                except Exception as exc:
                    state = "failed"
                    self.controls.log(tr("GitHub 未上传，文件已保留本地：{arg0}；{arg1}", arg0=item.relative, arg1=exc))
                counts[state] += 1
                self.events.put(("row", (index, state)))
            return counts
        self.launch(work, "uploaded")

    def poll(self):
        self.pending = None
        try:
            for kind, value in drain_events(self.events):
                if kind == "scan" and self.checked == self.signature() and not self.cancel.is_set():
                    self.candidates = value
                    self.render(auto_select=True)
                    ready = [str(i) for i, c in enumerate(value) if c.status == "ready"]
                    self.status.set(tr("扫描完成：共 {arg0} 个文档，{arg1} 个可以补传。", arg0=len(value), arg1=len(ready)))
                elif kind == "row" and self.checked == self.signature():
                    from dataclasses import replace
                    index, status = value
                    self.candidates[index] = replace(self.candidates[index], status=status)
                    if self.tree.exists(str(index)):
                        labels = {"existing": tr("远端已有，跳过"), "uploaded": tr("上传完成"), "failed": tr("上传失败，文件保留本地")}
                        self.tree.set(str(index), "status", labels.get(status, status))
                elif kind == "uploaded":
                    self.status.set(tr("本次上传：成功 {arg0}，远端已有 {arg1}，失败 {arg2}。", arg0=value["uploaded"], arg1=value["existing"], arg2=value["failed"]))
                elif kind == "error":
                    self.status.set(tr("已停止。") if isinstance(value, ProcessingCancelled) else tr("GitHub 操作失败：{arg0}", arg0=value))
                elif kind == "done":
                    self.busy = False
                    if self.cancel.is_set():
                        self.status.set(tr("已停止。"))
        except queue.Empty:
            pass
        except Exception as exc:
            self.status.set(tr("后台事件处理失败：{arg0}", arg0=exc))
        self.buttons()
        if not self.closed:
            self.pending = self.app.root.after(100, self.poll)

    def cleanup(self, event):
        if event.widget != self.window:
            return
        self.closed = True
        self.cancel.set()
        if self.render_timer is not None:
            self.app.root.after_cancel(self.render_timer)
            self.render_timer = None
        if self.pending:
            self.app.root.after_cancel(self.pending)
        for variable, token in self.traces:
            variable.trace_remove("write", token)
