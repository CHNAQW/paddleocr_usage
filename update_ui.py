"""Local and GitHub update controls; file and network work run outside Tk."""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

from app_updater import (SourcePackage, UpdateCancelled, discard_package, import_package, last_result,
                         launch_install, running_executable, check_github_update, download_github_update)
from responsive_ui import AdaptiveLabel, ButtonToolbar
from ui_i18n import ChoiceVar, LocalizedVar, filedialog, messagebox, tr


class UpdatePanel:
    def __init__(self, parent, app, version, compiled=False):
        self.app, self.root, self.version = app, app.root, version
        self.executable = running_executable(compiled)
        self.staged, self.thread = None, None
        self.online = None
        self.channel = ChoiceVar(master=self.root, value="正式发行版（Release）")
        self.installing, self.closed = False, False
        self.cancel = threading.Event()
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
                                             (tr("安装并重启"), self.install)))
        toolbar.grid(row=6, column=0, sticky="ew", pady=8)
        self.choose_button, self.cancel_button, self.install_button = toolbar.buttons
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
        self.channel_combo.bind("<<ComboboxSelected>>", self.reset_online)
        AdaptiveLabel(online, text=tr("来源固定为 CHNAQW/paddleocr_usage。最新代码可能尚未经过正式发布验证；仅在点击检查或下载时联网。"),
                      style="Subtitle.TLabel").grid(row=1, column=0, sticky="ew", pady=8)
        self.online_details = LocalizedVar(master=self.root, value=tr("选择渠道后检查新版。"))
        AdaptiveLabel(online, textvariable=self.online_details, max_lines=7).grid(row=2, column=0, sticky="ew", pady=8)
        netbar = ButtonToolbar(online, ((tr("检查 GitHub 更新"), self.check_online), (tr("下载此版本"), self.download_online)))
        netbar.grid(row=3, column=0, sticky="ew")
        self.check_button, self.download_button = netbar.buttons
        self.frame.bind("<Destroy>", self.cleanup, add="+")
        self.pending = self.root.after(100, self.poll)
        self.notice_timer = self.root.after(1200, self.show_last_result)
        self.buttons()

    def buttons(self):
        busy = bool(self.thread and self.thread.is_alive())
        self.choose_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.install_button.configure(state="normal" if self.staged and self.executable and not busy else "disabled")
        self.check_button.configure(state="disabled" if busy else "normal")
        self.download_button.configure(state="normal" if self.online and not busy else "disabled")
        self.channel_combo.configure(state="disabled" if busy else "readonly")

    def reset_online(self, _event=None):
        self.online = None
        self.online_details.set(tr("选择渠道后检查新版。"))
        self.buttons()

    def check_online(self):
        if self.thread and self.thread.is_alive():
            return
        self.reset_online()
        self.cancel.clear()
        self.status.set(tr("正在检查 GitHub 新版……"))
        channel = "main" if self.channel.get() == "最新代码（main）" else "release"
        def worker():
            try:
                self.events.put(("online", check_github_update(self.version, channel, self.cancel.is_set)))
            except Exception as exc:
                self.events.put(("error", exc))
            finally:
                self.events.put(("done", None))
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()
        self.buttons()

    def download_online(self):
        if self.online and not (self.thread and self.thread.is_alive()):
            self.read(self.online.url, offer=self.online)

    def choose(self):
        if self.thread and self.thread.is_alive():
            return
        source = filedialog.askopenfilename(parent=self.frame.winfo_toplevel(), title=tr("选择本地更新包"),
                                            filetypes=[(tr("软件更新包"), "*.zip")])
        if source:
            self.read(source)

    def read(self, source, offer=None):
        if self.thread and self.thread.is_alive():
            return
        if self.staged:
            discard_package(self.staged)
            self.staged = None
        self.cancel.clear()
        self.progress.set(0)
        self.details.set(tr("正在读取：{arg0}", arg0=source))
        self.status.set(tr("正在下载并校验，请稍候……") if offer else tr("正在解包并校验，请稍候……"))
        def worker():
            try:
                loader = download_github_update if offer else import_package
                package = loader(offer or source, self.version, stop=self.cancel.is_set,
                    progress=lambda done, total: self.events.put(("progress", 100 * done / total)))
                if self.cancel.is_set() or self.closed:
                    discard_package(package)
                    raise UpdateCancelled(tr("已取消读取更新包。"))
                self.events.put(("package", package))
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
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.progress.set(value)
                elif kind == "online":
                    if not self.cancel.is_set():
                        self.online = value
                        if value:
                            self.online_details.set(tr("发现新版：{arg0}\n{arg1}\n{arg2}", arg0=value.version, arg1=value.page, arg2=value.notes))
                            self.status.set(tr("可下载新版；校验通过后再确认安装。"))
                        else:
                            self.online_details.set(tr("所选渠道暂无更高版本。"))
                            self.status.set(tr("所选渠道暂无更高版本。"))
                elif kind == "package":
                    if self.cancel.is_set():
                        discard_package(value)
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
                elif kind == "done":
                    self.thread = None
        except queue.Empty:
            pass
        self.buttons()
        if not self.closed:
            self.pending = self.root.after(100, self.poll)

    def app_busy(self):
        names = ("worker_thread", "check_thread", "repair_thread", "model_fetch_thread", "manual_check_thread")
        manual = getattr(self.app.literature.github_setup, "manual", None)
        return (any(getattr(self.app, name, None) and getattr(self.app, name).is_alive() for name in names)
                or self.app.literature.busy() or bool(manual and manual.busy))

    def install(self):
        if not self.staged or not self.executable or (self.thread and self.thread.is_alive()):
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
            launch_install(self.staged, self.executable, self.version)
        except Exception as exc:
            self.status.set(tr("无法开始安装：{arg0}", arg0=exc))
            return
        self.installing = True
        self.root.destroy()

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

    def cleanup(self, event):
        if event.widget != self.frame:
            return
        self.closed = True
        self.cancel.set()
        for timer in (self.pending, self.notice_timer):
            if timer is not None:
                self.root.after_cancel(timer)
        if self.staged and not self.installing:
            discard_package(self.staged)
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "package" and not self.installing:
                discard_package(value)
