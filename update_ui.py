"""Local and GitHub update controls; file and network work run outside Tk."""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from task_runtime import drain_events

from tkinter import ttk

from app_updater import (SourcePackage, UpdateCancelled, discard_package, import_package, last_result,
                         launch_install, running_executable, check_github_update, download_github_update)
from responsive_ui import AdaptiveCheckbutton, AdaptiveLabel, ButtonToolbar
from ui_i18n import ChoiceVar, LocalizedVar, copy_text, filedialog, language, messagebox, tr


class UpdatePanel:
    def __init__(self, parent, app, version, compiled=False):
        self.app, self.root, self.version = app, app.root, version
        self.executable = running_executable(compiled)
        self.staged, self.thread = None, None
        self.online = None
        self.loaded_offer = None
        self.operation = None
        self.operation_succeeded = False
        self.retry_action = None
        self.pending_retry = None
        saved = app.config.literature if isinstance(app.config.literature, dict) else {}
        saved = saved.get("updates", {})
        saved = saved if isinstance(saved, dict) else {}
        self.automatic = tk.BooleanVar(master=self.root, value=saved.get("automatic") is True)
        self.channel = ChoiceVar(master=self.root, value="最新代码（main）" if saved.get("channel") == "main" else "正式发行版（Release）")
        self.source_mode = ChoiceVar(master=self.root, value="GitHub 联网更新")
        self._source_signature = self.source_mode.get()
        self.has_activity = False
        self.auto_timer, self.auto_checked, self.auto_in_progress = None, False, False
        self.preference_signature = (self.automatic.get(), self.channel.get())
        self.installing, self.closed = False, False
        self.confirming = False
        self.handoff = False
        self.cancel = threading.Event()
        self.delivery_lock = threading.Lock()
        self.discard_threads = []
        self.events = queue.Queue()
        self.frame = ttk.Frame(parent, padding=14)
        self.frame.grid(row=0, column=0, sticky="ew")
        self.frame.columnconfigure(0, weight=1)
        self.heading = AdaptiveLabel(self.frame, text=tr("软件更新"), style="WizardHeading.TLabel")
        self.heading.grid(row=0, column=0, sticky="ew")
        self.version_label = AdaptiveLabel(self.frame, text=tr("当前版本：{arg0}", arg0=version))
        self.version_label.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        sources = ttk.Frame(self.frame)
        sources.grid(row=2, column=0, sticky="ew")
        sources.columnconfigure(0, weight=1)
        modes = ("GitHub 联网更新", "本地 ZIP 更新")
        self.source_combo = ttk.Combobox(sources, textvariable=self.source_mode, state="readonly",
                                         values=[tr(value) for value in modes], width=1)
        self.source_combo.localized_choices = modes
        self.source_combo.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        values = ("正式发行版（Release）", "最新代码（main）")
        self.channel_combo = ttk.Combobox(sources, textvariable=self.channel, state="readonly",
                                          values=[tr(v) for v in values], width=1)
        self.channel_combo.localized_choices = values
        self.channel_combo.grid(row=1, column=0, sticky="ew")
        self.details = LocalizedVar(master=self.root, value=tr("请选择您信任的本地更新 ZIP。"))
        self.online_details = LocalizedVar(master=self.root, value=tr("选择渠道后检查新版。"))
        self.preview = LocalizedVar(master=self.root, value=tr("先检查新版，再查看版本与更新说明。"))
        self.preview_label = AdaptiveLabel(self.frame, textvariable=self.preview, max_lines=5)
        self.preview_label.grid(row=3, column=0, sticky="ew", pady=(10, 6))
        self.status = LocalizedVar(master=self.root, value=tr("检查更新不会下载或安装。"))
        AdaptiveLabel(self.frame, textvariable=self.status, max_lines=4, style="Subtitle.TLabel").grid(row=5, column=0, sticky="ew", pady=8)
        self.progress = tk.DoubleVar(master=self.root)
        self.progress_bar = ttk.Progressbar(self.frame, variable=self.progress, maximum=100)
        self.progress_bar.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        self.actions = ButtonToolbar(self.frame, (
            (tr("检查 GitHub 更新"), self.check_online), (tr("选择更新 ZIP"), self.choose),
            (tr("下载并校验"), self.download_online), (tr("安装并重启"), self.install),
            (tr("取消"), self.request_cancel), (tr("重试上一步"), self.retry),
            (tr("查看更新说明"), self.show_notes), (tr("复制更新信息"), self.copy_details)))
        self.actions.grid(row=4, column=0, sticky="ew", pady=4)
        (self.check_button, self.choose_button, self.download_button, self.install_button,
         self.cancel_button, self.retry_button, self.notes_button, self.copy_button) = self.actions.buttons
        self.all_action_buttons = list(self.actions.buttons)
        self.package_summary = LocalizedVar(master=self.root)
        self.package_label = AdaptiveLabel(self.frame, textvariable=self.package_summary, style="Subtitle.TLabel")
        self.package_label.grid(row=7, column=0, sticky="ew", pady=4)
        hint = tr("新包校验通过后才替换待安装包。安装前会再次确认版本、保存设置并重启。")
        AdaptiveLabel(self.frame, text=hint, style="Subtitle.TLabel").grid(row=8, column=0, sticky="ew", pady=8)
        if self.executable is None:
            AdaptiveLabel(self.frame, text=tr("当前为源码运行或非 Windows 环境，可校验更新包；安装替换仅在 Windows EXE 中启用。"),
                          style="Subtitle.TLabel").grid(row=9, column=0, sticky="ew", pady=8)
        online = ttk.LabelFrame(self.frame, text=tr("自动检查更新"), padding=12)
        online.grid(row=10, column=0, sticky="ew", pady=(12, 0))
        online.columnconfigure(0, weight=1)
        AdaptiveCheckbutton(online, text=tr("启动时自动检查更新"), variable=self.automatic).grid(row=0, column=0, sticky="ew")
        AdaptiveLabel(online, text=tr("默认关闭。启用后按所选渠道在启动时检查一次；仅提示新版，下载和安装仍需手动确认。"),
                      style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=8)
        AdaptiveLabel(online, text=tr("来源固定为 CHNAQW/paddleocr_usage。可检查最新 Release 或 main 分支；main 代码可能尚未经过正式发布验证。"),
                      style="Subtitle.TLabel").grid(row=2, column=0, sticky="ew", pady=8)
        self.frame.bind("<Destroy>", self.cleanup, add="+")
        self.pending = self.root.after(100, self.poll)
        self.notice_timer = self.root.after(1200, self.show_last_result)
        self.preference_traces = [(v, v.trace_add("write", self.preferences_changed)) for v in (self.automatic, self.channel)]
        self.preference_traces.append((self.source_mode, self.source_mode.trace_add("write", self.source_changed)))
        self.viewport = parent.master if isinstance(parent.master, tk.Canvas) else None
        self.compact = None
        self.viewport_binding = self.viewport.bind("<Configure>", self.fit_viewport, add="+") if self.viewport else None
        self.fit_viewport()
        self.schedule_automatic()
        self.buttons()

    def fit_viewport(self, _event=None):
        compact = bool(self.viewport and self.viewport.winfo_height() < 300)
        if compact == self.compact:
            return
        self.compact = compact
        self.heading.grid_remove() if compact else self.heading.grid()
        self.frame.configure(padding=8 if compact else 14)
        self.version_label.grid_configure(pady=(0, 4) if compact else (4, 8))
        self.preview_label.max_lines = 1 if compact else 5
        self.preview_label.grid_configure(pady=(6, 4) if compact else (10, 6))
        if self.operation is None:
            self.refresh_preview()
        self.preview_label.schedule()

    def config_data(self):
        return {"automatic": self.automatic.get(), "channel": "main" if self.channel.get() == "最新代码（main）" else "release"}

    def cancel_automatic_timer(self):
        if self.auto_timer is not None:
            self.root.after_cancel(self.auto_timer)
            self.auto_timer = None

    def preferences_changed(self, *_):
        signature = (self.automatic.get(), self.channel.get())
        if signature == self.preference_signature:
            return
        channel_changed = signature[1] != self.preference_signature[1]
        self.preference_signature = signature
        self.cancel_automatic_timer()
        if self.auto_in_progress or (channel_changed and self.operation is not None):
            self.cancel.set()
            self.status.set(tr("正在取消更新操作，请稍候……"))
            if channel_changed:
                self.pending_retry = None
        if channel_changed:
            self.retry_action = None
            self.reset_online()
        self.auto_checked = False
        self.schedule_automatic()

    def schedule_automatic(self):
        if self.automatic.get() and not self.closed and not self.auto_checked and self.auto_timer is None:
            self.auto_timer = self.root.after(3000, self.run_automatic)

    def run_automatic(self):
        self.auto_timer = None
        if self.closed or not self.automatic.get() or self.auto_checked or self.source_mode.get() != "GitHub 联网更新":
            return
        if self.busy():
            self.schedule_automatic()
            return
        self.auto_checked = True
        # A background check must never invalidate a user's selected package/offer.
        if self.staged or self.online:
            return
        self.check_online(automatic=True)

    def buttons(self):
        busy = self.busy()
        online_mode = self.source_mode.get() == "GitHub 联网更新"
        signature = (busy, online_mode, language(), self.operation, self.handoff, self.confirming,
                     self.cancel.is_set(), self.operation_succeeded, self.retry_action, self.pending_retry,
                     self.online, self.loaded_offer, id(self.staged), bool(self.executable),
                     (self.staged.version, self.staged.size) if self.staged else None)
        if signature == getattr(self, "_button_signature", None):
            return
        self.choose_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if self.operation is not None and not self.handoff and not self.cancel.is_set()
                                     and not self.operation_succeeded else "disabled")
        self.install_button.configure(state="normal" if self.staged and self.executable and not busy else "disabled")
        self.check_button.configure(state="disabled" if busy else "normal")
        self.download_button.configure(state="normal" if self.online and not busy else "disabled")
        self.retry_button.configure(state="normal" if self.retry_action and not busy else "disabled")
        self.notes_button.configure(state="normal" if self.online else "disabled")
        self.source_combo.configure(state="disabled" if busy else "readonly")
        self.channel_combo.configure(state="disabled" if busy else "readonly")
        self.channel_combo.grid() if online_mode else self.channel_combo.grid_remove()
        if self.staged:
            self.package_summary.set(tr("已校验的待安装包：{arg0} · {arg1:.1f} MB",
                                       arg0=self.staged.version, arg1=self.staged.size / (1024 * 1024)))
            self.package_label.grid()
        else:
            self.package_label.grid_remove()

        if self.handoff:
            primary = self.install_button
        elif self.operation == "check":
            primary = self.check_button
        elif self.operation == "read":
            primary = self.download_button if self.pending_retry and self.pending_retry[2] else self.choose_button
        elif self.retry_action:
            primary = self.retry_button
        elif online_mode and self.online and self.online != self.loaded_offer:
            primary = self.download_button
        elif self.staged:
            primary = self.install_button
        else:
            primary = self.check_button if online_mode else self.choose_button
        visible = [primary]
        if busy:
            if not self.handoff and not self.confirming:
                visible.append(self.cancel_button)
        else:
            if self.staged and primary is not self.install_button:
                visible.append(self.install_button)
            secondary = self.check_button if online_mode else self.choose_button
            if secondary not in visible:
                visible.append(secondary)
            if online_mode and self.online:
                visible.append(self.notes_button)
        visible.append(self.copy_button)
        self.install_button.configure(text=tr("安装并重启") if primary is self.install_button else
                                      tr("安装已校验版本 {arg0}", arg0=self.staged.version) if self.staged else tr("安装并重启"))
        for button in self.all_action_buttons:
            button.configure(style="Accent.TButton" if button is primary else "Tool.TButton")
            if button not in visible:
                button.place_forget()
        if self.actions.buttons != visible:
            self.actions.buttons = visible
            self.actions.layout = None
            self.actions.schedule()
        self.primary_button = primary
        self._button_signature = signature

    def busy(self):
        return self.confirming or self.handoff or self.installing or self.operation is not None or bool(self.thread and self.thread.is_alive())

    def source_changed(self, *_):
        current = self.source_mode.get()
        if current == getattr(self, "_source_signature", None):
            return
        self._source_signature = current
        self.retry_action = None
        if self.operation is not None:
            self.cancel.set()
            self.pending_retry = None
            self.status.set(tr("正在取消更新操作，请稍候……"))
        if current == "本地 ZIP 更新":
            self.cancel_automatic_timer()
            self.auto_checked = True
            if self.auto_in_progress:
                self.cancel.set()
        self.refresh_preview()
        self.reset_source_status()
        self.buttons()

    def reset_source_status(self):
        if self.busy():
            return
        if self.staged:
            self.status.set(tr("已保留校验通过的版本 {arg0}，可重试或安装该版本。", arg0=self.staged.version))
        elif self.source_mode.get() == "本地 ZIP 更新":
            self.status.set(tr("请选择您信任的本地更新 ZIP。"))
        elif self.online:
            self.status.set(tr("可下载新版；校验通过后再确认安装。"))
        else:
            self.status.set(tr("检查更新不会下载或安装。"))
        self.progress.set(100 if self.staged else 0)

    def refresh_preview(self):
        if self.source_mode.get() == "GitHub 联网更新" and self.online:
            self.preview.set(tr("可用版本：{arg0}", arg0=self.online.version) if self.compact else self.online_details.message)
        elif self.staged:
            self.preview.set(tr("已选择版本 {arg0}，校验通过。", arg0=self.staged.version))
        elif self.source_mode.get() == "本地 ZIP 更新":
            self.preview.set(tr("选择本地 ZIP 后先校验并预览版本，不会直接安装。"))
        else:
            self.preview.set(self.online_details.message)

    def request_cancel(self):
        if self.operation is None or self.handoff or self.operation_succeeded:
            return
        self.cancel.set()
        self.status.set(tr("正在取消更新操作，请稍候……"))
        self.buttons()

    def retry(self):
        if self.busy() or not self.retry_action:
            return
        kind, source, offer = self.retry_action
        if kind == "check":
            self.check_online()
        elif kind == "install":
            self.install()
        else:
            self.read(source, offer)

    def show_notes(self):
        if self.online:
            messagebox.showinfo(tr("更新说明"), self.online_details.get(), parent=self.frame.winfo_toplevel())

    def begin_operation(self, kind, retry_action):
        self.has_activity = True
        self.operation = kind
        self.operation_succeeded = False
        self.pending_retry = retry_action
        self.retry_action = None
        self.cancel = threading.Event()
        self.progress.set(0)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start(15)

    def start_worker(self, work):
        self.thread = threading.Thread(target=work, daemon=True)
        try:
            self.thread.start()
        except Exception as exc:
            if self.handoff:
                self.events.put(("install_error", exc))
            else:
                self.events.put(("error", exc))
                self.events.put(("done", None))
        self.buttons()

    def reset_online(self, _event=None):
        self.online = None
        self.online_details.set(tr("选择渠道后检查新版。"))
        self.refresh_preview()
        self.reset_source_status()
        self.buttons()

    def copy_details(self):
        copy_text(self.root, "\n\n".join((str(tr("当前版本：{arg0}", arg0=self.version)),
                  str(tr(self.source_mode.get())), str(tr(self.channel.get())), self.status.get(),
                  self.online_details.get(), self.details.get())))

    def check_online(self, automatic=False):
        if self.closed or self.busy():
            return
        self.cancel_automatic_timer()
        self.auto_checked = True
        self.auto_in_progress = automatic
        self.source_mode.set("GitHub 联网更新")
        self.begin_operation("check", ("check", None, None))
        self.status.set(tr("正在检查 GitHub 新版……"))
        channel = "main" if self.channel.get() == "最新代码（main）" else "release"
        cancel = self.cancel
        def worker():
            try:
                self.events.put(("auto_online" if automatic else "online", check_github_update(self.version, channel, cancel.is_set)))
            except Exception as exc:
                self.events.put(("auto_error" if automatic else "error", exc))
            finally:
                self.events.put(("done", None))
        self.start_worker(worker)

    def download_online(self):
        if not self.closed and not self.busy() and self.online:
            self.read(self.online.url, offer=self.online)

    def choose(self):
        if self.closed or self.busy():
            return
        source = filedialog.askopenfilename(parent=self.frame.winfo_toplevel(), title=tr("选择本地更新包"),
                                            filetypes=[(tr("软件更新包"), "*.zip")])
        if source:
            self.read(source)

    def read(self, source, offer=None):
        if self.closed or self.busy():
            return
        self.cancel_automatic_timer()
        self.auto_checked = True
        self.source_mode.set("GitHub 联网更新" if offer else "本地 ZIP 更新")
        self.begin_operation("read", ("read", source, offer))
        if not self.staged:
            self.details.set(tr("正在读取：{arg0}", arg0=source))
        if not offer:
            self.preview.set(tr("正在校验本地更新包：{arg0}", arg0=source))
        self.status.set(tr("正在下载并校验，请稍候……") if offer else tr("正在解包并校验，请稍候……"))
        cancel = self.cancel
        def progress(done, total):
            if total > 0 and not cancel.is_set() and not self.closed:
                self.events.put(("progress", max(0, min(99, 100 * done / total))))
        def worker():
            try:
                loader = download_github_update if offer else import_package
                package = loader(offer or source, self.version, stop=cancel.is_set, progress=progress)
                # Transfer ownership atomically with close: a completed import
                # must never land in an abandoned UI queue after cleanup drained it.
                with self.delivery_lock:
                    abandoned = cancel.is_set() or self.closed
                    if not abandoned:
                        self.events.put(("package", package))
                if abandoned:
                    discard_package(package)
                    raise UpdateCancelled(tr("已取消读取更新包。"))
            except Exception as exc:
                self.events.put(("error", exc))
            finally:
                self.events.put(("done", None))
        self.start_worker(worker)

    def poll(self):
        self.pending = None
        try:
            for kind, value in drain_events(self.events):
                if kind == "install_ready":
                    self.installing = True
                    self.thread = None
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                    self.progress.set(100)
                    self.root.destroy()
                    return
                elif kind == "install_error":
                    self.handoff = False
                    self.thread = None
                    self.operation = None
                    self.pending_retry = None
                    self.retry_action = ("install", None, None)
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                    self.progress.set(0)
                    self.status.set(tr("无法开始安装：{arg0}", arg0=value))
                    self.app.log(self.status.get())
                elif kind == "progress":
                    if self.operation == "read" and not self.cancel.is_set():
                        self.progress_bar.stop()
                        self.progress_bar.configure(mode="determinate")
                        self.progress.set(max(self.progress.get(), value))
                elif kind in ("online", "auto_online"):
                    if not self.cancel.is_set() and (kind == "online" or self.automatic.get()):
                        self.online = value
                        self.operation_succeeded = True
                        if value:
                            self.online_details.set(tr("发现新版：{arg0}\n{arg1}\n{arg2}", arg0=value.version, arg1=value.page, arg2=value.notes))
                            self.status.set(tr("可下载新版；校验通过后再确认安装。"))
                        else:
                            self.online_details.set(tr("所选渠道暂无更高版本。"))
                            self.status.set(tr("所选渠道暂无更高版本。"))
                        if kind == "auto_online":
                            self.app.log(tr("自动检查更新：{arg0}", arg0=self.online_details.get()))
                        self.refresh_preview()
                elif kind == "auto_error":
                    if not self.cancel.is_set() and self.automatic.get():
                        self.status.set(tr("自动检查更新失败，可稍后手动重试：{arg0}", arg0=value))
                        self.app.log(self.status.get())
                        self.retry_action = self.pending_retry
                elif kind == "package":
                    if self.cancel.is_set():
                        self.discard_in_background(value)
                        self.status.set(tr("已取消读取更新包。"))
                    else:
                        previous = self.staged
                        self.staged = value
                        self.operation_succeeded = True
                        self.loaded_offer = self.pending_retry[2] if self.pending_retry else None
                        self.details.set(tr("新版：{arg0} · {arg1:.1f} MB\n类型：{arg4}\n来源：{arg2}\nSHA-256：{arg3}",
                            arg0=value.version, arg1=value.size / (1024 * 1024), arg2=str(value.source), arg3=value.sha256,
                            arg4=tr("源码更新") if isinstance(value, SourcePackage) else tr("完整程序更新")))
                        self.status.set(tr("更新包校验通过，可安装并重启。") if self.executable else tr("更新包校验通过；请在 Windows EXE 中安装。"))
                        self.progress_bar.stop()
                        self.progress_bar.configure(mode="determinate")
                        self.progress.set(100)
                        self.refresh_preview()
                        if previous is not None and previous is not value:
                            self.discard_in_background(previous)
                elif kind == "error":
                    self.retry_action = self.pending_retry
                    self.status.set(tr("已取消更新操作。") if isinstance(value, UpdateCancelled)
                                    else tr("检查更新失败：{arg0}", arg0=value) if self.operation == "check"
                                    else tr("读取更新包失败：{arg0}", arg0=value))
                    if self.staged:
                        self.status.set(self.status.message + "\n" + tr("已保留校验通过的版本 {arg0}，可重试或安装该版本。", arg0=self.staged.version))
                    self.refresh_preview()
                    if not isinstance(value, UpdateCancelled):
                        self.app.log(self.status.get())
                elif kind == "done":
                    if self.cancel.is_set() and not self.operation_succeeded:
                        self.retry_action = self.pending_retry
                        self.status.set(tr("已取消更新操作。"))
                        if self.staged:
                            self.status.set(self.status.message + "\n" + tr("已保留校验通过的版本 {arg0}，可重试或安装该版本。", arg0=self.staged.version))
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                    self.progress.set(100 if self.operation_succeeded else 0)
                    self.thread = None
                    self.operation = None
                    self.pending_retry = None
                    self.auto_in_progress = False
                    self.refresh_preview()
        except Exception as exc:
            self.status.set(tr("后台事件处理失败：{arg0}", arg0=exc))
        self.buttons()
        if not self.closed:
            self.pending = self.root.after(100, self.poll)

    def app_busy(self):
        names = ("worker_thread", "check_thread", "repair_thread", "model_fetch_thread", "manual_check_thread")
        manual = getattr(self.app.literature.github_setup, "manual", None)
        return (bool(getattr(self.app, "background_jobs", {})) or any(getattr(self.app, name, None) and getattr(self.app, name).is_alive() for name in names)
                or self.app.literature.busy() or bool(manual and manual.busy))

    def install(self):
        if self.closed or self.busy() or not self.staged or not self.executable:
            return
        if self.app_busy():
            messagebox.showwarning(tr("暂时无法安装"), tr("请等待 OCR、翻译或检查任务结束，再安装更新。"), parent=self.frame.winfo_toplevel())
            return
        package, executable = self.staged, self.executable
        self.confirming = True
        self.buttons()
        try:
            confirmed = messagebox.askyesno(tr("安装软件更新"),
                tr("将安装 {arg0}，保存设置并退出当前程序，然后重新启动。旧版会保留备份，是否继续？", arg0=package.version),
                parent=self.frame.winfo_toplevel())
        finally:
            self.confirming = False
            if not self.closed:
                self.buttons()
        if not confirmed or self.closed or self.busy() or self.staged is not package:
            return
        if self.app_busy():
            messagebox.showwarning(tr("暂时无法安装"), tr("请等待 OCR、翻译或检查任务结束，再安装更新。"), parent=self.frame.winfo_toplevel())
            return
        try:
            self.app.save_current_config()
        except Exception as exc:
            self.retry_action = ("install", None, None)
            self.status.set(tr("无法开始安装：{arg0}", arg0=exc))
            self.app.log(self.status.get())
            self.buttons()
            return
        self.begin_operation("install", ("install", None, None))
        self.handoff = True
        self.status.set(tr("正在启动更新助手，请稍候……"))
        def worker():
            try:
                launch_install(package, executable, self.version)
                self.events.put(("install_ready", None))
            except Exception as exc:
                self.events.put(("install_error", exc))
        self.start_worker(worker)

    def show_last_result(self):
        self.notice_timer = None
        if self.has_activity or self.staged or self.thread or self.operation or self.online or self.retry_action:
            return
        if getattr(sys, "_paddleocr_source_error", None):
            self.status.set(tr("新版源码启动失败，已使用内置版本。请重新导入兼容的更新包。"))
            return
        result = last_result()
        if not result:
            return
        if result["status"] == "installed":
            self.status.set(tr("上次更新已完成，安装版本：{arg0}。", arg0=result.get("version", "")))
        else:
            self.status.set(tr("上次更新未完成。恢复结果：{arg0}；日志：{arg1}",
                arg0=tr("已恢复旧版") if result.get("restored") else tr("请检查原程序或备份"), arg1=result.get("log", "")))

    def discard_in_background(self, *packages):
        # Large directories / antivirus hooks must not block Tk shutdown or
        # cancellation. Startup maintenance reclaims anything interrupted by exit.
        def discard():
            for package in packages:
                discard_package(package)
        if packages:
            self.discard_threads = [thread for thread in self.discard_threads if thread.is_alive()]
            thread = threading.Thread(target=discard, daemon=True, name="update-discard")
            self.discard_threads.append(thread)
            thread.start()

    def cleanup(self, event):
        if event.widget != self.frame:
            return
        with self.delivery_lock:
            self.closed = True
            self.cancel.set()
            abandoned = []
            while not self.events.empty():
                kind, value = self.events.get_nowait()
                if kind == "package" and not self.installing:
                    abandoned.append(value)
        for variable, trace in self.preference_traces:
            variable.trace_remove("write", trace)
        if self.viewport_binding:
            self.viewport.unbind("<Configure>", self.viewport_binding)
            self.viewport_binding = None
        self.cancel_automatic_timer()
        try:
            self.progress_bar.stop()
        except tk.TclError:
            pass  # Child widgets are already destroyed by a parent's Destroy event.
        for timer in (self.pending, self.notice_timer):
            if timer is not None:
                self.root.after_cancel(timer)
        if self.staged and not self.installing and not self.handoff:
            abandoned.append(self.staged)
            self.staged = None
        self.discard_in_background(*abandoned)
