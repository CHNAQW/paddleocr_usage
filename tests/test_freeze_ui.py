import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_updater
import literature_processing as lp
import literature_ui
import paddleocr_pdf_to_md_gui as application
import update_ui
from test_app_updater import pe_payload
from ui_i18n import set_language


class InterfaceResponsivenessTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        self.destroyed = False
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)
        self.load = patch.object(application, 'load_config', return_value=application.AppConfig(token=''))
        self.save = patch.object(application, 'save_config')
        self.info = patch.object(application.messagebox, 'showinfo')
        self.error = patch.object(application.messagebox, 'showerror')
        self.load.start(); self.save.start(); self.notice = self.info.start(); self.error.start()
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.app = application.PaddleOCRBatchGUI(self.root)
        self.c = self.app.literature
        for role, model in self.c.profiles.items():
            model.url.set('https://example.invalid/v1')
            model.key.set('fixture-key')
            model.model.set(role)
        self.root.update()

    def tearDown(self):
        if not self.destroyed:
            for timer in self.root.tk.call('after', 'info'):
                self.root.after_cancel(timer)
            self.root.destroy()
        self.load.stop(); self.save.stop(); self.info.stop(); self.error.stop()
        set_language('zh')

    def pump(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.005)
        self.assertTrue(predicate())

    def heartbeat(self):
        beats = []
        self.root.after(15, lambda: beats.append(True))
        self.pump(lambda: bool(beats), timeout=.5)

    def stage(self):
        exe = self.directory / 'old.exe'
        exe.write_bytes(pe_payload())
        archive = app_updater.build_package(exe, '27.1.1.1', self.directory)
        panel = self.app.updates
        panel.staged = app_updater.import_package(archive, application.APP_VERSION, cache=self.directory/'cache')
        panel.executable = exe
        return panel

    def test_install_handoff_does_not_block_tk_and_closes_only_after_acknowledgement(self):
        panel = self.stage()
        release = threading.Event()
        def handoff(*_):
            release.wait(2)
        try:
            with patch.object(update_ui, 'launch_install', side_effect=handoff), \
                    patch.object(update_ui.messagebox, 'askyesno', return_value=True), patch.object(self.root, 'destroy') as close:
                started = time.monotonic()
                panel.install()
                self.assertLess(time.monotonic()-started, .2)
                self.heartbeat()
                close.assert_not_called()
                self.assertTrue(panel.handoff)
                release.set()
                self.pump(lambda: panel.installing)
                close.assert_called_once()
                self.assertTrue(panel.staged.payload.exists())
        finally:
            release.set()
            panel.installing = False
            panel.handoff = False

    def test_failed_handoff_restores_install_controls_and_keeps_app_running(self):
        panel = self.stage()
        with patch.object(update_ui, 'launch_install', side_effect=RuntimeError('startup failure')), \
                patch.object(update_ui.messagebox, 'askyesno', return_value=True):
            panel.install()
            self.pump(lambda: not panel.handoff)
        self.assertTrue(self.root.winfo_exists())
        self.assertIn('startup failure', panel.status.get())
        self.assertEqual(str(panel.install_button.cget('state')), 'normal')

    def test_pdf_scan_is_background_work_and_tk_keeps_receiving_events(self):
        release = threading.Event()
        self.app.input_var.set(str(self.directory))
        try:
            with patch.object(application, 'find_pdf_files', side_effect=lambda *_: release.wait(2) and []):
                started = time.monotonic()
                self.app.scan_pdfs()
                self.assertLess(time.monotonic()-started, .2)
                self.heartbeat()
                self.assertIn('pdf_scan', self.app.background_jobs)
                release.set()
                self.pump(lambda: not self.app.background_jobs)
        finally:
            release.set()

    def test_translation_scan_and_automatic_completion_do_not_block_or_prompt(self):
        source = self.directory/'paper.md'
        source.write_text('Paper', encoding='utf-8')
        self.c.input.set(str(self.directory))
        self.c.force_auto.set(True)
        release = threading.Event()
        def scan(*_):
            release.wait(2)
            return [source]
        try:
            with patch.object(literature_ui, 'find_markdown_files', side_effect=scan), \
                    patch.object(self.c, 'process', return_value={'status':'target_language'}):
                self.c.start()
                self.heartbeat()
                self.assertTrue(self.c.thread.is_alive())
                release.set()
                self.pump(lambda: not self.c.thread.is_alive() and self.c.events.empty())
                self.notice.assert_not_called()
        finally:
            release.set()

    def test_force_automatic_settings_are_shared_saved_bilingual_and_snapshotted(self):
        self.c.force_auto.set(True)
        self.assertTrue(self.c.proofreading.get())
        self.assertTrue(self.c.allow_arbiter_revision.get())
        self.assertEqual(self.c.arbitration.get(), '大模型裁决')
        snapshot = self.c.make_snapshot()
        self.assertTrue(self.c.config_data()['force_auto'])
        self.assertTrue(snapshot['options'].force_auto)
        self.assertTrue(self.c.quality_panel.automatic_button.instate(['selected']))
        self.assertTrue(self.c.quality_panel.arbitration_combo.instate(['disabled']))
        self.app.change_ui_language('en')
        self.root.update()
        self.assertEqual(self.c.quality_panel.automatic_button.cget('text'), 'Fully automatic (no manual decisions)')
        self.c.force_auto.set(False)
        self.assertTrue(snapshot['force_auto'])
        self.assertTrue(snapshot['options'].force_auto)

    def test_event_flood_and_one_invalid_event_do_not_kill_the_queue_pump(self):
        self.app.log_queue.put(('page_progress', ('malformed',)))
        for index in range(2000):
            self.app.log_queue.put(('status', str(index)))
        self.app._poll_log_queue()
        self.assertGreater(self.app.log_queue.qsize(), 1900)
        self.heartbeat()
        self.app.log_queue.put(('status', 'still alive'))
        self.pump(lambda: self.app.status_var.get()=='still alive', timeout=6)

    def test_large_logs_bound_tk_text_and_history_without_idle_reentry(self):
        huge = 'x' * 100000
        with patch.object(self.root, 'update_idletasks', side_effect=AssertionError('log must not reenter Tk')):
            self.app.log(huge)
        self.assertEqual(self.app.log_history[-1][1], huge)
        self.assertLess(len(self.app.log_text.get('1.0','end')), 20000)
        for index in range(1100):
            self.app.log(str(index)+'\nline\nline')
        self.assertLessEqual(len(self.app.log_history), 1000)
        self.assertLessEqual(int(self.app.log_text.index('end-1c').split('.')[0]), 2001)
        self.heartbeat()

    def test_github_table_inserts_in_batches_and_allows_interleaved_events(self):
        manual = self.app.workspace_layout.github_manual
        manual.candidates = [lp.UploadCandidate(self.directory/'x.md', f'paper-{i}.md','original','ready','hash') for i in range(2000)]
        manual.render(auto_select=True)
        self.assertLessEqual(len(manual.tree.get_children()), 100)
        self.heartbeat()
        self.pump(lambda: len(manual.tree.get_children())==2000)
        self.assertEqual(len(manual.tree.selection()), 2000)

    def test_closing_root_releases_a_worker_waiting_for_a_user_decision(self):
        finished = threading.Event()
        def work():
            try:
                self.c.decide({'source':'source','first':'draft','filename':'paper.md','problem':'check'})
            except lp.ProcessingCancelled:
                finished.set()
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        self.pump(lambda: not self.c.events.empty())
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()
        self.destroyed = True
        self.assertTrue(finished.wait(.6))
        worker.join(timeout=.2)
        self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
