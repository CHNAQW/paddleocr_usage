import tempfile
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
        self.zip = updates.build_package(new, "26.10.19.06", self.folder)
        self.root.update()

    def tearDown(self):
        self.panel.installing = False
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()
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
        self.assertIn("26.10.19.06", self.panel.details.get())
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
        with patch.object(update_ui.messagebox, "askyesno", return_value=True), \
                patch.object(self.app, "save_current_config", side_effect=lambda: actions.append("save")), \
                patch.object(update_ui, "launch_install", side_effect=lambda *args: actions.append("launch")), \
                patch.object(self.root, "destroy", side_effect=lambda: actions.append("close")):
            self.panel.install()
        self.assertEqual(actions, ["save", "launch", "close"])
        self.assertTrue(self.panel.installing)
        self.assertTrue(self.panel.staged.payload.is_file())

    def test_updates_tab_is_bilingual_and_does_not_hide_compact_logs(self):
        self.app.workspace_layout.show_settings(3)
        for locale, text in (("en", "Choose update ZIP"), ("zh", "选择更新 ZIP")):
            self.app.change_ui_language(locale)
            self.root.geometry("540x420")
            self.root.update()
            self.assertEqual(self.panel.choose_button.cget("text"), text)
            self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
            self.assertEqual(self.app.workspace_layout.settings_tabs.index("end"), 5)

    def wait_worker(self):
        deadline = time.monotonic() + 3
        while self.panel.thread and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertIsNone(self.panel.thread)

    def test_explicit_online_check_never_downloads_or_installs_and_uses_selected_channel(self):
        offer = updates.OnlineUpdate("26.10.19.06", "https://github.com/update.zip", "Changes", "https://github.com/release")
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

    def test_online_download_reuses_package_validation_and_waits_for_install_confirmation(self):
        offer = updates.OnlineUpdate("26.10.19.06", "https://github.com/update.zip", "", "")
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


if __name__ == "__main__":
    unittest.main()
