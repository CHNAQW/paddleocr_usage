import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import github_ui
import literature_processing as lp
import paddleocr_pdf_to_md_gui as application
from ui_i18n import set_language


class GithubWorkspaceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        self.load = patch.object(application, 'load_config', return_value=application.AppConfig(token=''))
        self.save = patch.object(application, 'save_config')
        self.load.start()
        self.save.start()
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.app = application.PaddleOCRBatchGUI(self.root)
        self.c = self.app.literature
        self.shell = self.app.workspace_layout
        self.manual = self.shell.github_manual
        self.c.github_token.set('')
        for role, model in self.c.profiles.items():
            model.url.set('https://example.invalid/v1')
            model.key.set('fixture-key')
            model.model.set(role)
        self.root.update()

    def tearDown(self):
        wizard = self.c.github_setup.wizard
        if wizard and wizard.window.winfo_exists():
            wizard.close()
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()
        self.load.stop()
        self.save.stop()
        set_language('zh')

    def wait(self):
        deadline = time.monotonic() + 3
        while self.manual.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.manual.busy)

    def configured(self):
        self.c.repository.set('owner/repo')
        self.c.github_token.set('session-only')
        self.c.upload_root.set('/tmp/documents')

    def test_revision_permission_defaults_off_and_tracks_the_decision_mode(self):
        panel = self.c.quality_panel
        self.assertFalse(self.c.allow_arbiter_revision.get())
        self.assertEqual(str(panel.revision_button.cget('state')), 'disabled')
        self.c.secondary.set(True)
        self.assertEqual(str(panel.revision_button.cget('state')), 'disabled')
        self.c.arbitration.set('大模型裁决')
        self.assertEqual(str(panel.revision_button.cget('state')), 'normal')
        self.c.secondary.set(False)
        self.assertEqual(str(panel.revision_button.cget('state')), 'disabled')

    def test_ocr_and_translation_share_permission_and_running_snapshot_is_stable(self):
        self.c.proofreading.set(True)
        self.c.arbitration.set('大模型裁决')
        self.shell.ocr_quality_panel.revision_button.invoke()
        self.assertTrue(self.c.quality_panel.revision_button.instate(['selected']))
        snapshot = self.c.make_snapshot()
        self.assertTrue(snapshot['options'].allow_arbiter_revision)
        self.assertTrue(self.c.config_data()['allow_arbiter_revision'])
        self.c.allow_arbiter_revision.set(False)
        self.assertTrue(snapshot['options'].allow_arbiter_revision)
        self.assertFalse(self.c.make_snapshot()['options'].allow_arbiter_revision)

    def test_third_entry_reuses_the_same_manual_controller_from_preferences(self):
        self.assertEqual(len(self.app.notebook.tabs()), 3)
        self.assertEqual(len(self.shell.nav_buttons), 3)
        self.shell.show_settings(2)
        self.c.github_setup.open_manual()
        self.root.update()
        self.assertEqual(self.app.notebook.index(self.app.notebook.select()), 2)
        self.assertIs(self.c.github_setup.manual, self.manual)
        self.assertTrue(self.manual.embedded)
        self.assertFalse(self.shell.settings.winfo_viewable())
        self.assertTrue(self.shell.github_scan.winfo_ismapped())
        self.assertFalse(self.app.start_btn.winfo_ismapped())
        self.assertFalse(self.c.start_button.winfo_ismapped())
        self.root.focus_force()
        self.root.event_generate('<Control-Key-1>')
        self.root.update()
        self.root.event_generate('<Control-Key-3>')
        self.root.update()
        self.assertEqual(self.app.notebook.index(self.app.notebook.select()), 2)

    def test_setup_wizard_is_visible_when_opened_from_the_third_entry(self):
        self.app.notebook.select(2)
        self.c.github_setup.open()
        self.root.update()
        wizard = self.c.github_setup.wizard
        self.assertTrue(wizard.window.winfo_viewable())
        self.assertEqual(str(wizard.window.transient()), str(self.root))
        self.assertEqual(wizard.step, 0)

    def test_missing_credentials_open_setup_instead_of_starting_a_network_scan(self):
        self.app.notebook.select(2)
        with patch.object(github_ui, 'scan_missing_documents') as scan:
            self.shell.github_scan.invoke()
        scan.assert_not_called()
        self.assertFalse(self.manual.busy)
        self.assertIsNotNone(self.c.github_setup.wizard)

    def test_independent_scan_needs_no_ocr_translation_or_automatic_upload(self):
        self.configured()
        self.c.upload.set(False)
        self.app.notebook.select(2)
        items = [lp.UploadCandidate(Path('/tmp/documents/a.md'), 'a.md', 'original', 'ready', 'sha')]
        with patch.object(github_ui, 'scan_missing_documents', return_value=items) as scan:
            self.shell.github_scan.invoke()
            self.wait()
        scan.assert_called_once()
        self.assertEqual(self.manual.tree.selection(), ('0',))
        self.assertEqual(str(self.shell.github_upload.cget('state')), 'normal')
        self.assertFalse(self.c.upload.get())
        self.c.upload_kind.set('仅上传翻译稿')
        self.assertEqual(self.manual.candidates, [])
        self.assertEqual(str(self.shell.github_upload.cget('state')), 'disabled')

    def test_embedded_scan_blocks_update_installation_and_mirrors_action_states(self):
        self.configured()
        gate = threading.Event()
        self.addCleanup(gate.set)
        with patch.object(github_ui, 'scan_missing_documents', side_effect=lambda *args, **kwargs: (gate.wait(2), [])[1]):
            self.manual.scan()
            self.assertTrue(self.app.updates.app_busy())
            self.assertEqual(str(self.shell.github_scan.cget('state')), 'disabled')
            self.assertEqual(str(self.shell.github_stop.cget('state')), 'normal')
            self.manual.cancel.set()
            gate.set()
            self.wait()
        self.assertEqual(str(self.shell.github_scan.cget('state')), 'normal')

    def test_third_entry_actions_and_logs_fit_small_bilingual_windows(self):
        self.app.notebook.select(2)
        for locale, title in (('en', 'GitHub document uploads'), ('zh', 'GitHub 文档上传')):
            self.app.change_ui_language(locale)
            for geometry in ('1100x780', '540x420'):
                self.root.geometry(geometry)
                self.root.update()
                self.assertEqual(self.shell.title.cget('text'), title)
                self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
                for button in (self.shell.github_scan, self.shell.github_upload, self.shell.github_stop):
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())
