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
from ui_i18n import ChoiceVar, LocalizedVar, copy_text, filedialog, messagebox, tr


class UpdatePanel:
    def __init__(self, parent, app, version, compiled=False):
        self.app, self.root, self.version = app, app.root, version
        self.executable = running_executable(compiled)
        self.staged, self.thread = None, None
        self.online = None
        saved = app.config.literature if isinstance(app.config.literature, dict) else {}
        saved = saved.get("updates", {})
        saved = saved if isinstance(saved, dict) else {}
        self.automatic = tk.BooleanVar(master=self.root, value=saved.get("automatic") is True)
        self.channel = ChoiceVar(master=self.root, value="最新代码（main）" if saved.get("channel") == "main" else "正式发行版（Release）")
        self.auto_timer, self.auto_checked, self.auto_in_progress = None, False, False
        self.preference_signature = (self.automatic.get(), self.channel.get())
        self.installing, self.closed = False, False
        self.handoff = False
        self.cancel = threading.Event()
        self.delivery_lock = threading.Lock()
        self.discard_threads = []
        self.events = queue.Queue()
        self.frame = ttk.Frame(parent, padding=14)
        self.frame.grid(row=0, column=0, sticky="ew")
        self.frame.columnconfigure(0, weight=1)
        AdaptiveLabel(self.frame, text=tr("软件更新"), style="WizardHeading.TLabel").grid(row=0, column=0, sticky="ew")
        AdaptiveLabel(self.frame, text=tr("可选择本地 ZIP，或主动从 GitHub 检查并下载新版。支持源码包和完整 EXE 更新包。"),
                      style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=(8, 12))
        AdaptiveLabel(self.frame, text=tr("当前版本：{arg0}", arg0=version)).grid(row=2, column=0, sticky="ew")
        self.details = LocalizedVar(master=self.root, value=tr("请选择您信任的本地更新 ZIP。"))
        AdaptiveLabel(self.frame, textvariable=self.details).grid(row=3, column=0, sticky="ew", pady=12)
        self.status = LocalizedVar(master=self.root, value=tr("导入后检查版本、依赖、源码语法及文件完整性。"))
        AdaptiveLabel(self.frame, textvariable=self.status, style="Subtitle.TLabel").grid(row=4, column=0, sticky="ew", pady=8)
        self.progress = tk.DoubleVar(master=self.root)
        ttk.Progressbar(self.frame, variable=self.progress, maximum=100).grid(row=5, column=0, sticky="ew", pady=8)
        toolbar = ButtonToolbar(self.frame, ((tr("选择更新 ZIP"), self.choose), (tr("取消读取"), self.cancel.set),
                                             (tr("安装并重启"), self.install), (tr("复制更新信息"), self.copy_details)))
        toolbar.grid(row=6, column=0, sticky="ew", pady=8)
        self.choose_button, self.cancel_button, self.install_button, self.copy_button = toolbar.buttons
        hint = tr("安装前保存设置。源码更新使用内置 Python 运行时，新代码保存在用户目录；完整更新包替换 EXE。启动失败时尝试恢复旧版。")
        AdaptiveLabel(self.frame, text=hint, style="Subtitle.TLabel").grid(row=7, column=0, sticky="ew", pady=8)
        if self.executable is None:
            AdaptiveLabel(self.frame, text=tr("当前为源码运行或非 Windows 环境，可校验更新包；安装替换仅在 Windows EXE 中启用。"),
                          style="Subtitle.TLabel").grid(row=8, column=0, sticky="ew", pady=8)
        online = ttk.LabelFrame(self.frame, text=tr("从 GitHub 获取新版"), padding=12)
        online.grid(row=9, column=0, sticky="ew", pady=(12, 0))
        online.columnconfigure(0, weight=1)
        values = ("正式发行版（Release）", "最新代码（main）")
        self.channel_combo = ttk.Combobox(online, textvariable=self.channel, state="readonly", values=[tr(v) for v in values])
        self.channel_combo.localized_choices = values
        self.channel_combo.grid(row=0, column=0, sticky="ew")
        AdaptiveCheckbutton(online, text=tr("启动时自动检查更新"), variable=self.automatic).grid(row=4, column=0, sticky="ew", pady=(12, 0))
        AdaptiveLabel(online, text=tr("默认关闭。启用后按所选渠道在启动时检查一次；仅提示新版，下载和安装仍需手动确认。"),
                      style="Subtitle.TLabel").grid(row=5, column=0, sticky="ew", pady=8)
        AdaptiveLabel(online, text=tr("来源固定为 CHNAQW/paddleocr_usage。可检查最新 Release 或 main 分支；main 代码可能尚未经过正式发布验证。"),
                      style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=8)
        self.online_details = LocalizedVar(master=self.root, value=tr("选择渠道后检查新版。"))
        AdaptiveLabel(online, textvariable=self.online_details, max_lines=7).grid(row=2, column=0, sticky="ew", pady=8)
        netbar = ButtonToolbar(online, ((tr("检查 GitHub 更新"), self.check_online), (tr("下载此版本"), self.download_online)))
        netbar.grid(row=3, column=0, sticky="ew")
        self.check_button, self.download_button = netbar.buttons
        self.frame.bind("<Destroy>", self.cleanup, add="+")
        self.pending = self.root.after(100, self.poll)
        self.notice_timer = self.root.after(1200, self.show_last_result)
        self.preference_traces = [(v, v.trace_add("write", self.preferences_changed)) for v in (self.automatic, self.channel)]
        self.schedule_automatic()
        self.buttons()

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
        if self.auto_in_progress:
            self.cancel.set()
        if channel_changed:
            self.reset_online()
        self.auto_checked = False
        self.schedule_automatic()

    def schedule_automatic(self):
        if self.automatic.get() and not self.closed and not self.auto_checked and self.auto_timer is None:
            self.auto_timer = self.root.after(3000, self.run_automatic)

    def run_automatic(self):
        self.auto_timer = None
        if self.closed or not self.automatic.get() or self.auto_checked:
            return
        if self.thread and self.thread.is_alive():
            self.schedule_automatic()
            return
        self.auto_checked = True
        # A background check must never invalidate a user's selected package/offer.
        if self.staged or self.online:
            return
        self.check_online(automatic=True)

    def buttons(self):
        busy = self.handoff or bool(self.thread and self.thread.is_alive())
        self.choose_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy and not self.handoff else "disabled")
        self.install_button.configure(state="normal" if self.staged and self.executable and not busy else "disabled")
        self.check_button.configure(state="disabled" if busy else "normal")
        self.download_button.configure(state="normal" if self.online and not busy else "disabled")
        self.channel_combo.configure(state="disabled" if busy else "readonly")

    def reset_online(self, _event=None):
        self.online = None
        self.online_details.set(tr("选择渠道后检查新版。"))
        self.buttons()

    def copy_details(self):
        copy_text(self.root, "\n\n".join((str(tr("当前版本：{arg0}", arg0=self.version)),
                  str(tr(self.channel.get())), self.status.get(), self.online_details.get(), self.details.get())))

    def check_online(self, automatic=False):
        if self.closed or self.handoff or (self.thread and self.thread.is_alive()):
            return
        self.cancel_automatic_timer()
        self.auto_checked = True
        self.auto_in_progress = automatic
        self.reset_online()
        self.cancel.clear()
        self.status.set(tr("正在检查 GitHub 新版……"))
        channel = "main" if self.channel.get() == "最新代码（main）" else "release"
        def worker():
            try:
                self.events.put(("auto_online" if automatic else "online", check_github_update(self.version, channel, self.cancel.is_set)))
            except Exception as exc:
                self.events.put(("auto_error" if automatic else "error", exc))
            finally:
                self.events.put(("done", None))
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()
        self.buttons()

    def download_online(self):
        if not self.closed and not self.handoff and self.online and not (self.thread and self.thread.is_alive()):
            self.read(self.online.url, offer=self.online)

    def choose(self):
        if self.closed or self.handoff or (self.thread and self.thread.is_alive()):
            return
        source = filedialog.askopenfilename(parent=self.frame.winfo_toplevel(), title=tr("选择本地更新包"),
                                            filetypes=[(tr("软件更新包"), "*.zip")])
        if source:
            self.read(source)

    def read(self, source, offer=None):
        if self.closed or self.handoff or (self.thread and self.thread.is_alive()):
            return
        self.cancel_automatic_timer()
        self.auto_checked = True
        previous, self.staged = self.staged, None
        self.cancel.clear()
        self.progress.set(0)
        self.details.set(tr("正在读取：{arg0}", arg0=source))
        self.status.set(tr("正在下载并校验，请稍候……") if offer else tr("正在解包并校验，请稍候……"))
        def worker():
            try:
                if previous:
                    discard_package(previous)
                loader = download_github_update if offer else import_package
                package = loader(offer or source, self.version, stop=self.cancel.is_set,
                    progress=lambda done, total: self.events.put(("progress", 100 * done / total)))
                # Transfer ownership atomically with close: a completed import
                # must never land in an abandoned UI queue after cleanup drained it.
                with self.delivery_lock:
                    abandoned = self.cancel.is_set() or self.closed
                    if not abandoned:
                        self.events.put(("package", package))
                if abandoned:
                    discard_package(package)
                    raise UpdateCancelled(tr("已取消读取更新包。"))
            except Exception as exc:
                self.events.put(("error", exc))
            finally:
                self.events.put(("done", None))
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()
        self.buttons()

    def poll(self):
        self.pending = None
        try:
            for kind, value in drain_events(self.events):
                if kind == "install_ready":
                    self.installing = True
                    self.thread = None
                    self.root.destroy()
                    return
                elif kind == "install_error":
                    self.handoff = False
                    self.thread = None
                    self.status.set(tr("无法开始安装：{arg0}", arg0=value))
                    self.app.log(self.status.get())
                elif kind == "progress":
                    self.progress.set(value)
                elif kind in ("online", "auto_online"):
                    if not self.cancel.is_set() and (kind == "online" or self.automatic.get()):
                        self.online = value
                        if value:
                            self.online_details.set(tr("发现新版：{arg0}\n{arg1}\n{arg2}", arg0=value.version, arg1=value.page, arg2=value.notes))
                            self.status.set(tr("可下载新版；校验通过后再确认安装。"))
                        else:
                            self.online_details.set(tr("所选渠道暂无更高版本。"))
                            self.status.set(tr("所选渠道暂无更高版本。"))
                        if kind == "auto_online":
                            self.app.log(tr("自动检查更新：{arg0}", arg0=self.online_details.get()))
                elif kind == "auto_error":
                    if not self.cancel.is_set() and self.automatic.get():
                        self.status.set(tr("自动检查更新失败，可稍后手动重试：{arg0}", arg0=value))
                        self.app.log(self.status.get())
                elif kind == "package":
                    if self.cancel.is_set():
                        self.discard_in_background(value)
                        self.status.set(tr("已取消读取更新包。"))
                    else:
                        self.staged = value
                        self.details.set(tr("新版：{arg0} · {arg1:.1f} MB\n类型：{arg4}\n来源：{arg2}\nSHA-256：{arg3}",
                            arg0=value.version, arg1=value.size / (1024 * 1024), arg2=str(value.source), arg3=value.sha256,
                            arg4=tr("源码更新") if isinstance(value, SourcePackage) else tr("完整程序更新")))
                        self.status.set(tr("更新包校验通过，可安装并重启。") if self.executable else tr("更新包校验通过；请在 Windows EXE 中安装。"))
                        self.progress.set(100)
                elif kind == "error":
                    self.status.set(tr("已取消读取更新包。") if isinstance(value, UpdateCancelled)
                                    else tr("读取更新包失败：{arg0}", arg0=value))
                    if not isinstance(value, UpdateCancelled):
                        self.app.log(self.status.get())
                elif kind == "done":
                    self.thread = None
                    self.auto_in_progress = False
        except queue.Empty:
            pass
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
        if self.closed or self.handoff or not self.staged or not self.executable or (self.thread and self.thread.is_alive()):
            return
        if self.app_busy():
            messagebox.showwarning(tr("暂时无法安装"), tr("请等待 OCR、翻译或检查任务结束，再安装更新。"), parent=self.frame.winfo_toplevel())
            return
        if not messagebox.askyesno(tr("安装软件更新"),
                tr("将安装 {arg0}，保存设置并退出当前程序，然后重新启动。旧版会保留备份，是否继续？", arg0=self.staged.version),
                parent=self.frame.winfo_toplevel()):
            return
        try:
            self.app.save_current_config()
        except Exception as exc:
            self.status.set(tr("无法开始安装：{arg0}", arg0=exc))
            self.app.log(self.status.get())
            return
        self.handoff = True
        self.status.set(tr("正在启动更新助手，请稍候……"))
        package, executable = self.staged, self.executable
        def worker():
            try:
                launch_install(package, executable, self.version)
                self.events.put(("install_ready", None))
            except Exception as exc:
                self.events.put(("install_error", exc))
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()
        self.buttons()

    def show_last_result(self):
        self.notice_timer = None
        if self.staged or self.thread:
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
        self.cancel_automatic_timer()
        for timer in (self.pending, self.notice_timer):
            if timer is not None:
                self.root.after_cancel(timer)
        if self.staged and not self.installing and not self.handoff:
            abandoned.append(self.staged)
            self.staged = None
        self.discard_in_background(*abandoned)
