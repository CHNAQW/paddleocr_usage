import gc
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_updater as updates
import paddleocr_pdf_to_md_gui as application
import update_ui
from test_app_updater import pe_payload
from ui_i18n import set_language


class UpdatePanelTests(unittest.TestCase):
    def setUp(self):
        # Tk finalizers must run here, not in the next mocked network worker.
        gc.collect()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.config = patch.object(application, "load_config", return_value=application.AppConfig(token=""))
        self.save = patch.object(application, "save_config")
        self.config.start()
        self.save.start()
        self.app = application.PaddleOCRBatchGUI(self.root)
        self.panel = self.app.updates
        self.exe = self.folder / "old.exe"
        self.exe.write_bytes(pe_payload())
        new = self.folder / "new.exe"
        new.write_bytes(pe_payload())
        self.zip = updates.build_package(new, "26.10.31.02", self.folder)
        self.root.update()

    def tearDown(self):
        self.panel.installing = False
        for timer in self.root.tk.call("after", "info"):
            # ttk's animated progressbar also owns native Tcl timer scripts,
            # which are not Python callback command names for after_cancel.
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()
        for thread in self.panel.discard_threads:
            thread.join(3)
        self.config.stop()
        self.save.stop()
        set_language("zh")

    def stage(self):
        self.panel.staged = updates.import_package(self.zip, application.APP_VERSION, cache=self.folder / "cache")
        self.panel.executable = self.exe
        self.panel.buttons()

    def test_local_preview_runs_in_worker_and_source_mode_cannot_install(self):
        self.panel.executable = None
        original = updates.import_package
        with patch.object(update_ui, "import_package", side_effect=lambda *args, **kwargs:
                          original(*args, cache=self.folder / "cache", **kwargs)):
            self.panel.read(str(self.zip))
            deadline = time.monotonic() + 3
            while self.panel.thread and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertIsNotNone(self.panel.staged)
        self.assertIn("26.10.31.02", self.panel.details.get())
        self.assertEqual(str(self.panel.install_button.cget("state")), "disabled")
        self.assertTrue(self.zip.is_file())

    def test_active_document_work_blocks_installation(self):
        self.stage()
        self.app.worker_thread = Mock(is_alive=Mock(return_value=True))
        with patch.object(update_ui.messagebox, "showwarning") as warning, patch.object(update_ui, "launch_install") as install:
            self.panel.install()
        warning.assert_called_once()
        install.assert_not_called()
        self.assertTrue(self.root.winfo_exists())

    def test_install_cancel_preserves_application_and_staged_update(self):
        self.stage()
        with patch.object(update_ui.messagebox, "askyesno", return_value=False), patch.object(update_ui, "launch_install") as install:
            self.panel.install()
        install.assert_not_called()
        self.assertTrue(self.panel.staged.payload.is_file())
        self.assertTrue(self.root.winfo_exists())

    def test_config_save_failure_does_not_launch_helper_or_close_program(self):
        self.stage()
        with patch.object(update_ui.messagebox, "askyesno", return_value=True), \
                patch.object(self.app, "save_current_config", side_effect=ValueError("invalid settings")), \
                patch.object(update_ui, "launch_install") as install:
            self.panel.install()
        install.assert_not_called()
        self.assertIn("invalid settings", self.panel.status.get())
        self.assertTrue(self.root.winfo_exists())

    def test_successful_handoff_saves_settings_before_closing_and_keeps_payload(self):
        self.stage()
        actions = []
        def close():
            self.assertEqual(str(self.panel.progress_bar.cget("mode")), "determinate")
            timer_scripts = (str(self.root.tk.call("after", "info", timer))
                             for timer in self.root.tk.call("after", "info"))
            self.assertFalse(any(str(self.panel.progress_bar) in script for script in timer_scripts))
            actions.append("close")
        with patch.object(update_ui.messagebox, "askyesno", return_value=True), \
                patch.object(self.app, "save_current_config", side_effect=lambda: actions.append("save")), \
                patch.object(update_ui, "launch_install", side_effect=lambda *args: actions.append("launch")), \
                patch.object(self.root, "destroy", side_effect=close):
            self.panel.install()
            self.wait_worker()
        self.assertEqual(actions, ["save", "launch", "close"])
        self.assertTrue(self.panel.installing)
        self.assertTrue(self.panel.staged.payload.is_file())

    def test_updates_tab_is_bilingual_and_does_not_hide_compact_logs(self):
        self.app.workspace_layout.show_settings(3)
        for locale, text in (("en", "Choose update ZIP"), ("zh", "选择更新 ZIP")):
            self.app.change_ui_language(locale)
            self.root.geometry("540x420")
            self.app.workspace_layout.settings.geometry("540x420")
            self.root.update()
            self.assertEqual(self.panel.choose_button.cget("text"), text)
            self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
            self.assertEqual(self.app.workspace_layout.settings_tabs.index("end"), 7)

    def wait_worker(self):
        deadline = time.monotonic() + 3
        while self.panel.thread and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertIsNone(self.panel.thread)

    def test_explicit_online_check_never_downloads_or_installs_and_uses_selected_channel(self):
        offer = updates.OnlineUpdate("26.10.31.02", "https://github.com/update.zip", "Changes", "https://github.com/release")
        self.panel.channel.set("最新代码（main）")
        with patch.object(update_ui, "check_github_update", return_value=offer) as check, \
                patch.object(update_ui, "download_github_update") as download, patch.object(update_ui, "launch_install") as install:
            self.panel.check_online()
            self.wait_worker()
        self.assertEqual(check.call_args.args[:2], (application.APP_VERSION, "main"))
        download.assert_not_called()
        install.assert_not_called()
        self.assertIn("Changes", self.panel.online_details.get())
        self.assertEqual(str(self.panel.download_button.cget("state")), "normal")
        self.assertIs(self.panel.primary_button, self.panel.download_button)
        self.assertIsNone(self.panel.staged)

    def test_online_download_reuses_package_validation_and_waits_for_install_confirmation(self):
        offer = updates.OnlineUpdate("26.10.31.02", "https://github.com/update.zip", "", "")
        self.panel.online = offer
        self.panel.executable = self.exe
        def download(*args, **kwargs):
            return updates.import_package(self.zip, application.APP_VERSION, cache=self.folder / "cache", **kwargs)
        with patch.object(update_ui, "download_github_update", side_effect=download) as fetch, \
                patch.object(update_ui, "launch_install") as install:
            self.panel.download_online()
            self.wait_worker()
        self.assertEqual(fetch.call_args.args[0], offer)
        self.assertIsNotNone(self.panel.staged)
        self.assertEqual(str(self.panel.install_button.cget("state")), "normal")
        self.assertIs(self.panel.primary_button, self.panel.install_button)
        install.assert_not_called()
        self.assertTrue(self.root.winfo_exists())

    def test_manual_upload_blocks_install_and_channel_change_invalidates_offer(self):
        self.stage()
        self.app.literature.github_setup.manual = Mock(busy=True)
        with patch.object(update_ui.messagebox, "showwarning") as warning, patch.object(update_ui, "launch_install") as install:
            self.panel.install()
        warning.assert_called_once()
        install.assert_not_called()
        self.panel.online = Mock()
        self.panel.reset_online()
        self.assertIsNone(self.panel.online)
        self.assertEqual(str(self.panel.download_button.cget("state")), "disabled")

    def start_automatic_now(self):
        self.panel.cancel_automatic_timer()
        self.panel.run_automatic()

    def test_automatic_checks_are_opt_in_and_preferences_persist(self):
        self.assertFalse(self.panel.automatic.get())
        self.assertIsNone(self.panel.auto_timer)
        with patch.object(update_ui, "check_github_update") as check:
            self.start_automatic_now()
        check.assert_not_called()
        self.panel.channel.set("最新代码（main）")
        self.panel.automatic.set(True)
        self.assertIsNotNone(self.panel.auto_timer)
        self.assertEqual(self.app.literature.config_data()["updates"], {"automatic": True, "channel": "main"})
        self.panel.automatic.set(False)
        self.assertIsNone(self.panel.auto_timer)

    def test_saved_auto_channel_is_restored_and_old_configs_remain_off(self):
        from tkinter import ttk
        for saved, enabled, channel in (({}, False, "release"), ({"automatic": "false"}, False, "release"),
                                        ({"automatic": True, "channel": "main"}, True, "main")):
            with self.subTest(saved=saved):
                app = Mock(root=self.root, config=Mock(literature={"updates": saved}))
                parent = ttk.Frame(self.root)
                panel = update_ui.UpdatePanel(parent, app, application.APP_VERSION)
                self.assertEqual(panel.config_data(), {"automatic": enabled, "channel": channel})
                self.assertEqual(panel.auto_timer is not None, enabled)
                parent.destroy()

    def test_automatic_check_only_notifies_for_both_channels_once(self):
        for channel in ("正式发行版（Release）", "最新代码（main）"):
            self.panel.online = None
            self.panel.channel.set(channel)
            self.panel.automatic.set(True)
            self.panel.auto_checked = False
            offer = updates.OnlineUpdate("26.10.31.02", "https://github.com/update.zip", "Changes", "https://github.com/release")
            with patch.object(update_ui, "check_github_update", return_value=offer) as check, \
                    patch.object(update_ui, "download_github_update") as download, patch.object(update_ui, "launch_install") as install:
                self.start_automatic_now()
                self.wait_worker()
                self.start_automatic_now()
            self.assertEqual(check.call_count, 1)
            self.assertEqual(check.call_args.args[1], "main" if "main" in channel else "release")
            download.assert_not_called()
            install.assert_not_called()
            self.assertIs(self.panel.online, offer)
            self.assertTrue(self.root.winfo_exists())

    def test_auto_check_preserves_staged_package_and_manual_offer(self):
        self.panel.automatic.set(True)
        for attr in ("staged", "online"):
            sentinel = Mock()
            setattr(self.panel, attr, sentinel)
            self.panel.auto_checked = False
            with patch.object(update_ui, "check_github_update") as check:
                self.start_automatic_now()
            check.assert_not_called()
            self.assertIs(getattr(self.panel, attr), sentinel)
            setattr(self.panel, attr, None)

    def test_auto_check_defers_while_busy_and_language_switch_does_not_repeat(self):
        self.panel.automatic.set(True)
        self.panel.thread = Mock(is_alive=Mock(return_value=True))
        self.start_automatic_now()
        self.assertIsNotNone(self.panel.auto_timer)
        self.assertFalse(self.panel.auto_checked)
        self.panel.thread = None
        with patch.object(update_ui, "check_github_update", return_value=None) as check:
            self.start_automatic_now()
            self.wait_worker()
            self.app.change_ui_language("en")
            self.root.update()
            self.start_automatic_now()
        self.assertEqual(check.call_count, 1)
        self.assertIsNone(self.panel.auto_timer)

    def test_disabling_automatic_check_cancels_inflight_and_ignores_offer(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        offer = updates.OnlineUpdate("26.10.31.02", "https://github.com/update.zip", "", "")
        def check(*_args):
            entered.set()
            release.wait(2)
            return offer
        self.panel.automatic.set(True)
        with patch.object(update_ui, "check_github_update", side_effect=check):
            self.start_automatic_now()
            self.assertTrue(entered.wait(1))
            self.panel.automatic.set(False)
            self.assertTrue(self.panel.cancel.is_set())
            release.set()
            self.wait_worker()
        self.assertIsNone(self.panel.online)
        self.assertIsNone(self.panel.auto_timer)

    def test_background_check_failure_is_logged_without_modal_or_download(self):
        self.panel.automatic.set(True)
        with patch.object(update_ui, "check_github_update", side_effect=ValueError("403 test")), \
                patch.object(update_ui.messagebox, "showerror") as error, patch.object(update_ui, "download_github_update") as download:
            self.start_automatic_now()
            self.wait_worker()
        error.assert_not_called()
        download.assert_not_called()
        self.assertIn("403 test", self.panel.status.get())

    def test_replacing_large_stage_does_not_block_ui(self):
        self.stage()
        previous = self.panel.staged
        replacement = updates.import_package(self.zip, application.APP_VERSION, cache=self.folder / "replacement")
        entered, release = threading.Event(), threading.Event()
        def slow_discard(package):
            entered.set()
            release.wait(3)
            updates.discard_package(package)
        with patch.object(update_ui, "discard_package", side_effect=slow_discard), \
                patch.object(update_ui, "import_package", return_value=replacement):
            try:
                self.panel.read(str(self.zip))
                self.wait_worker()
                self.assertTrue(entered.wait(1))
                ticks = []
                self.root.after(1, lambda: ticks.append(True))
                deadline = time.monotonic() + .5
                while not ticks and time.monotonic() < deadline:
                    self.root.update()
                self.assertTrue(ticks)
                self.assertTrue(previous.directory.exists())
                self.assertIs(self.panel.staged, replacement)
            finally:
                release.set()
                for thread in self.panel.discard_threads:
                    thread.join(3)
        self.assertFalse(previous.directory.exists())
        self.assertTrue(self.zip.exists())

    def test_failed_replacement_preserves_verified_package_and_retry_source(self):
        self.stage()
        previous = self.panel.staged
        with patch.object(update_ui, "import_package", side_effect=ValueError("invalid ZIP")):
            self.panel.read(str(self.zip))
            self.wait_worker()
        self.assertIs(self.panel.staged, previous)
        self.assertTrue(previous.payload.exists())
        self.assertTrue(self.zip.exists())
        self.assertIn("已保留", self.panel.status.get())
        self.assertIs(self.panel.primary_button, self.panel.retry_button)
        self.assertIn(previous.version, self.panel.install_button.cget("text"))
        replacement = updates.import_package(self.zip, application.APP_VERSION, cache=self.folder / "retry")
        with patch.object(update_ui, "import_package", return_value=replacement) as load:
            self.panel.retry()
            self.wait_worker()
        self.assertEqual(load.call_args.args[0], str(self.zip))
        self.assertIs(self.panel.staged, replacement)
        self.assertIs(self.panel.primary_button, self.panel.install_button)

    def test_finished_worker_stays_locked_until_completion_is_consumed(self):
        offer = updates.OnlineUpdate("26.10.31.02", "https://github.com/update.zip", "", "")
        with patch.object(update_ui, "check_github_update", return_value=offer) as check, \
                patch.object(update_ui, "import_package") as load:
            self.panel.check_online()
            self.panel.thread.join(2)
            self.assertFalse(self.panel.thread.is_alive())
            self.assertTrue(self.panel.busy())
            self.panel.check_online()
            self.panel.read(str(self.zip))
            check.assert_called_once()
            load.assert_not_called()
            self.wait_worker()
        self.assertFalse(self.panel.busy())
        self.assertIs(self.panel.primary_button, self.panel.download_button)

    def test_cancel_after_import_delivery_keeps_previous_package(self):
        self.stage()
        previous = self.panel.staged
        replacement = updates.import_package(self.zip, application.APP_VERSION, cache=self.folder / "replacement")
        with patch.object(update_ui, "import_package", return_value=replacement):
            self.panel.read(str(self.zip))
            self.panel.thread.join(2)  # Package queued but not accepted by Tk yet.
            self.panel.request_cancel()
            self.wait_worker()
        for thread in self.panel.discard_threads:
            thread.join(3)
        self.assertIs(self.panel.staged, previous)
        self.assertTrue(previous.payload.exists())
        self.assertFalse(replacement.directory.exists())
        self.assertIn("已保留", self.panel.status.get())
        self.assertIn(previous.version, self.panel.preview.get())
        self.assertIs(self.panel.primary_button, self.panel.retry_button)

    def test_channel_change_discards_completed_old_check_before_poll(self):
        offer = updates.OnlineUpdate("26.10.31.02", "https://github.com/update.zip", "", "")
        with patch.object(update_ui, "check_github_update", return_value=offer):
            self.panel.check_online()
            self.panel.thread.join(2)
            self.panel.channel.set("最新代码（main）")
            self.wait_worker()
        self.assertIsNone(self.panel.online)
        self.assertIsNone(self.panel.retry_action)
        self.assertIs(self.panel.primary_button, self.panel.check_button)

    def test_check_failure_preserves_existing_offer_and_allows_retry(self):
        offer = updates.OnlineUpdate("26.10.31.02", "https://github.com/update.zip", "", "")
        self.panel.online = offer
        with patch.object(update_ui, "check_github_update", side_effect=ValueError("network failed")):
            self.panel.check_online()
            self.wait_worker()
        self.assertIs(self.panel.online, offer)
        self.assertIs(self.panel.primary_button, self.panel.retry_button)
        self.assertIn("检查更新失败", self.panel.status.get())
        with patch.object(update_ui, "check_github_update", return_value=None) as check:
            self.panel.retry()
            self.wait_worker()
        check.assert_called_once()
        self.assertIsNone(self.panel.online)

    def test_automatic_check_does_not_override_selected_local_source(self):
        self.panel.status.set("检查更新失败：network failed")
        self.panel.source_mode.set("本地 ZIP 更新")
        self.assertIn("请选择", self.panel.status.get())
        self.panel.automatic.set(True)
        with patch.object(update_ui, "check_github_update") as check:
            self.start_automatic_now()
        check.assert_not_called()
        self.assertEqual(self.panel.source_mode.get(), "本地 ZIP 更新")
        self.assertIs(self.panel.primary_button, self.panel.choose_button)

    def test_source_and_channel_changes_clear_stale_status_and_keep_verified_package(self):
        self.panel.status.set("所选渠道暂无更高版本。")
        self.panel.channel.set("最新代码（main）")
        self.assertIn("检查更新不会", self.panel.status.get())
        self.stage()
        package = self.panel.staged
        self.panel.source_mode.set("本地 ZIP 更新")
        self.assertIs(self.panel.staged, package)
        self.assertIn(package.version, self.panel.status.get())
        self.assertIn("已保留", self.panel.status.get())
        self.panel.source_mode.set("GitHub 联网更新")
        self.assertIs(self.panel.staged, package)
        self.assertIn(package.version, self.panel.status.get())

    def test_progress_reaches_100_only_after_validation(self):
        entered, release = threading.Event(), threading.Event()
        replacement = updates.import_package(self.zip, application.APP_VERSION, cache=self.folder / "replacement")
        def load(*_args, progress, **_kwargs):
            progress(1, 0)
            progress(10, 10)
            progress(1, 10)  # Extraction's own phase must not reset progress.
            entered.set()
            release.wait(3)
            return replacement
        with patch.object(update_ui, "import_package", side_effect=load):
            try:
                self.panel.read(str(self.zip))
                self.assertTrue(entered.wait(1))
                deadline = time.monotonic() + 1
                while self.panel.progress.get() != 99 and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertEqual(self.panel.progress.get(), 99)
                self.assertIsNone(self.panel.staged)
            finally:
                release.set()
                self.wait_worker()
        self.assertEqual(self.panel.progress.get(), 100)

    def test_thread_start_failure_offers_retry_without_permanent_busy(self):
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("cannot start worker")):
            self.panel.check_online()
            self.wait_worker()
        self.assertFalse(self.panel.busy())
        self.assertIs(self.panel.primary_button, self.panel.retry_button)
        self.assertIn("cannot start worker", self.panel.status.get())

    def test_confirmation_blocks_reentry_and_rechecks_document_work(self):
        self.stage()
        def confirm(*_args, **_kwargs):
            self.assertTrue(self.panel.busy())
            self.panel.check_online()
            self.panel.install()
            self.app.worker_thread = Mock(is_alive=Mock(return_value=True))
            return True
        with patch.object(update_ui.messagebox, "askyesno", side_effect=confirm) as confirmation, \
                patch.object(update_ui.messagebox, "showwarning") as warning, \
                patch.object(update_ui, "check_github_update") as check, \
                patch.object(update_ui, "launch_install") as install:
            self.panel.install()
        confirmation.assert_called_once()
        warning.assert_called_once()
        check.assert_not_called()
        install.assert_not_called()
        self.assertFalse(self.panel.busy())

    def test_idle_poll_does_not_reconfigure_buttons_or_reset_package_label(self):
        self.stage()
        with patch.object(self.panel.install_button, "configure", wraps=self.panel.install_button.configure) as configure, \
                patch.object(self.panel.package_summary, "set", wraps=self.panel.package_summary.set) as set_summary:
            for _ in range(5):
                self.panel.buttons()
        configure.assert_not_called()
        set_summary.assert_not_called()

    def test_compact_update_actions_wrap_in_both_languages(self):
        self.app.workspace_layout.show_settings(3)
        self.app.workspace_layout.settings.geometry("440x340")
        self.root.update()
        self.stage()
        self.panel.online = updates.OnlineUpdate("27.1.1.1", "https://github.com/new.zip", "Changes", "")
        self.panel.preview.set("27.1.1.1\n" + "Release notes " * 100)
        for locale in ("zh", "en"):
            self.app.change_ui_language(locale)
            self.app.workspace_layout.settings.geometry("440x340")
            self.panel.buttons()
            self.root.update()
            width = self.panel.actions.winfo_width()
            self.assertGreater(width, 100)
            self.assertIn("27.1.1.1", self.panel.preview_label.display.get())
            self.assertIs(self.panel.primary_button, self.panel.download_button)
            self.assertIn(self.panel.install_button, self.panel.actions.buttons)
            viewport = self.panel.viewport
            self.assertLessEqual(self.panel.primary_button.winfo_rooty() + self.panel.primary_button.winfo_height(),
                                 viewport.winfo_rooty() + viewport.winfo_height())
            for button in self.panel.actions.buttons:
                self.assertEqual(button.winfo_manager(), "place")
                self.assertGreaterEqual(button.winfo_x(), 0)
                self.assertLessEqual(button.winfo_x() + button.winfo_width(), width)
                self.assertLessEqual(button.winfo_y() + button.winfo_height(), self.panel.actions.winfo_height())

    def test_close_during_import_discards_unclaimed_package(self):
        self.stage()
        package, self.panel.staged = self.panel.staged, None
        entered, release = threading.Event(), threading.Event()
        def load(*args, **kwargs):
            entered.set()
            release.wait(3)
            return package
        with patch.object(update_ui, "import_package", side_effect=load):
            self.panel.read(str(self.zip))
            thread = self.panel.thread
            try:
                self.assertTrue(entered.wait(1))
                self.panel.frame.destroy()
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(package.directory.exists())
        self.assertTrue(self.zip.exists())
        self.assertFalse(any(kind == "package" for kind, _ in self.panel.events.queue))

    def test_handoff_disables_cancel_and_rejects_new_reads(self):
        self.stage()
        self.panel.handoff = True
        self.panel.buttons()
        self.assertEqual(str(self.panel.cancel_button.cget("state")), "disabled")
        with patch.object(update_ui, "import_package") as load, \
                patch.object(update_ui, "check_github_update") as check:
            self.panel.read(str(self.zip))
            self.panel.check_online()
        load.assert_not_called()
        check.assert_not_called()
        self.panel.handoff = False


if __name__ == "__main__":
    unittest.main()
