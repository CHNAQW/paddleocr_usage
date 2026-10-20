import faulthandler
import gc
import hashlib
import json
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import github_ui
import literature_processing as lp
import paddleocr_pdf_to_md_gui as application
from ui_i18n import set_language


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.options = lp.GitHubOptions('owner/repo', 'session-key', 'review/papers', 'library')
        self.client = Mock(remote_paths=Mock(return_value=set()))

    def document(self, name, verified=True, legacy=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'English literature\r\n')
        if 'TRANSLATED' in name:
            data = {'verified': verified, 'status': 'verified' if verified else 'needs_review',
                    'outputSHA256': hashlib.sha256(path.read_bytes()).hexdigest()}
            suffix = '.translation.json'
        else:
            data = {'hasProblem': not verified}
            if not legacy:
                data['textSHA256'] = lp.review_text_sha256(path.read_text())
            suffix = '.llm-review.json'
        path.with_suffix(suffix).write_text(json.dumps(data))
        return path

    def scan(self, kind='同时上传'):
        return lp.scan_missing_documents(self.root, kind, self.options, client=self.client)

    def test_missing_comparison_roles_and_nested_paths(self):
        self.document('中文/原稿.md')
        self.document('中文/TRANSLATED_原稿.md')
        self.document('already.md')
        self.client.remote_paths.return_value = {'library/already.md'}
        result = self.scan()
        self.assertEqual({v.relative: v.status for v in result}, {'already.md': 'existing', '中文/原稿.md': 'ready', '中文/TRANSLATED_原稿.md': 'ready'})
        self.assertEqual([v.role for v in self.scan('仅上传原文')], ['original', 'original'])
        self.assertEqual([v.role for v in self.scan('仅上传翻译稿')], ['translation'])

    def test_modified_missing_legacy_and_failed_reviews_are_not_eligible(self):
        path = self.document('changed.md')
        path.write_text('edited after review')
        self.document('old.md', legacy=True)
        self.document('failed.md', verified=False)
        (self.root / 'unreviewed.md').write_text('no report')
        self.assertEqual({v.relative: v.status for v in self.scan()}, {'changed.md': 'changed', 'old.md': 'changed', 'failed.md': 'unverified', 'unreviewed.md': 'unverified'})

    def test_real_ocr_review_fingerprint_matches_writer_newlines_and_rejects_text_edits(self):
        path = self.root / 'ocr.md'
        markdown = 'OCR body\nsecond line'
        response = Mock(ok=True)
        response.json.return_value = {'choices': [{'message': {'content': '{"has_problem": false, "issues": []}'}}]}
        with patch.object(application.requests, 'post', return_value=response):
            report = application.review_markdown_with_llm(markdown, path.name, 'https://api.example.invalid/v1', 'key', 'model')
        path.write_bytes((markdown + '\n').replace('\n', '\r\n').encode())
        path.with_suffix('.llm-review.json').write_text(json.dumps(report))
        self.assertEqual(lp.document_upload_evidence(path)[1], 'ready')
        path.write_text('Different OCR body\n')
        self.assertEqual(lp.document_upload_evidence(path)[1], 'changed')

    def test_positive_report_cannot_override_ocr_warning_or_failed_upstream(self):
        path = self.document('ocr.md')
        path.with_suffix('.raw.json').write_text(json.dumps({'parts': [{'qualityWarning': 'too short'}]}))
        translated = self.document('TRANSLATED_ocr.md')
        report = json.loads(translated.with_suffix('.translation.json').read_text())
        report['upstreamVerified'] = False
        translated.with_suffix('.translation.json').write_text(json.dumps(report))
        self.assertTrue(all(v.status == 'unverified' for v in self.scan()))

    def test_symlinks_hidden_folders_and_non_markdown_are_excluded(self):
        path = self.document('good.md')
        (self.root / 'linked.md').symlink_to(path)
        self.document('.git/hidden.md')
        (self.root / 'original.pdf').write_bytes(b'PDF')
        self.assertEqual([v.relative for v in self.scan()], ['good.md'])
        with self.assertRaises(ValueError):
            lp.scan_missing_documents('', '同时上传', self.options, client=self.client)

    def test_truncated_remote_tree_is_walked_without_assuming_missing(self):
        client = lp.GitHubSetupClient('key')
        branch = {'commit': {'commit': {'tree': {'sha': 'root'}}}}
        with patch.object(client, 'get', side_effect=[branch, {'truncated': True},
             {'tree': [{'path': 'library', 'type': 'tree', 'sha': 'child'}]},
             {'tree': [{'path': 'a.md', 'type': 'blob', 'sha': 'file'}]}]) as get:
            self.assertEqual(client.remote_paths(self.options), {'library', 'library/a.md'})
        self.assertIn('review%2Fpapers', get.call_args_list[0].args[0])
        with patch.object(client, 'get', side_effect=[branch, {'truncated': True}, {'truncated': True}]), self.assertRaises(RuntimeError):
            client.remote_paths(self.options)

    def test_cancelled_scan_never_creates_a_commit(self):
        self.document('a.md')
        with patch.object(lp.requests, 'put') as put, self.assertRaises(lp.ProcessingCancelled):
            lp.scan_missing_documents(self.root, '同时上传', self.options, stop=lambda: True, client=self.client)
        put.assert_not_called()


class ManualUploadTests(unittest.TestCase):
    def setUp(self):
        # Reclaim earlier Tk fixtures on their owner thread, before starting workers.
        gc.collect()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        self.addCleanup(self.cleanup_root)
        self.load = patch.object(application, 'load_config', return_value=application.AppConfig())
        self.save = patch.object(application, 'save_config')
        self.load.start(); self.save.start()
        self.addCleanup(self.load.stop)
        self.addCleanup(self.save.stop)
        self.addCleanup(set_language, 'zh')
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.app = application.PaddleOCRBatchGUI(self.root)
        self.c = self.app.literature
        self.c.repository.set('owner/repo'); self.c.github_token.set('session-only')
        self.c.upload_root.set('/tmp/documents')
        self.c.github_setup.open_manual()
        self.panel = self.c.github_setup.manual
        self.root.update()

    def cleanup_root(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()

    def wait(self):
        deadline = time.monotonic() + 3
        while self.panel.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.01)
        if self.panel.busy:
            faulthandler.dump_traceback()
        self.assertFalse(self.panel.busy,
            f"worker_alive={self.panel.worker_thread.is_alive()}, events={self.panel.events.qsize()}, status={self.panel.status.get()}")

    def stage(self):
        items = [lp.UploadCandidate(Path('/tmp/documents/a.md'), 'a.md', 'original', 'ready', 'sha'),
                 lp.UploadCandidate(Path('/tmp/documents/b.md'), 'b.md', 'translation', 'existing', '')]
        with patch.object(github_ui, 'scan_missing_documents', return_value=items), patch.object(github_ui, 'upload_verified_file') as upload:
            self.panel.scan(); self.wait()
            upload.assert_not_called()
        return items

    def test_scan_selects_only_eligible_missing_files_and_choice_changes_invalidate_results(self):
        self.stage()
        self.assertEqual(self.panel.tree.selection(), ('0',))
        self.c.upload_kind.set('仅上传翻译稿')
        self.assertEqual(self.panel.candidates, [])
        self.assertIsNone(self.panel.checked)
        self.assertEqual(str(self.panel.upload_button.cget('state')), 'disabled')
        self.assertEqual(self.c.config_data()['upload_kind'], '仅上传翻译稿')
        self.assertNotIn('session-only', repr(self.c.config_data()))

    def test_selected_files_are_rechecked_and_existing_remote_files_never_written(self):
        self.stage()
        self.panel.tree.selection_set(('0', '1'))
        with patch.object(github_ui.messagebox, 'askyesno', return_value=True), \
             patch.object(github_ui, 'document_upload_evidence', return_value=('original', 'ready', 'sha')), \
             patch.object(github_ui, 'upload_verified_file', return_value='a.md') as upload:
            self.panel.upload(); self.wait()
        self.assertEqual(upload.call_count, 1)
        self.assertEqual(self.panel.candidates[0].status, 'uploaded')
        self.assertEqual(self.panel.candidates[1].status, 'existing')

    def test_changed_document_cannot_upload_after_scan(self):
        self.stage()
        with patch.object(github_ui.messagebox, 'askyesno', return_value=True), \
             patch.object(github_ui, 'document_upload_evidence', return_value=('original', 'changed', 'different')), \
             patch.object(github_ui, 'upload_verified_file') as upload:
            self.panel.upload(); self.wait()
        upload.assert_not_called()
        self.assertEqual(self.panel.candidates[0].status, 'failed')

    def test_upload_waits_until_all_eligible_rows_have_been_rendered_and_selected(self):
        self.panel.checked = self.panel.signature()
        self.panel.candidates = [
            lp.UploadCandidate(Path(f'/tmp/documents/{index}.md'), f'{index}.md', 'original', 'ready', 'sha')
            for index in range(250)]
        self.panel.render(auto_select=True)
        self.assertIsNotNone(self.panel.render_timer)
        self.assertEqual(len(self.panel.tree.selection()), 100)
        self.assertEqual(str(self.panel.upload_button.cget('state')), 'disabled')
        with patch.object(github_ui.messagebox, 'askyesno') as confirm, \
             patch.object(self.panel, 'launch') as launch:
            self.panel.upload()
            confirm.assert_not_called()
            launch.assert_not_called()
        deadline = time.monotonic() + 3
        while self.panel.render_timer is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertIsNone(self.panel.render_timer)
        self.assertEqual(len(self.panel.tree.selection()), 250)
        self.assertEqual(str(self.panel.upload_button.cget('state')), 'normal')

    def test_update_handoff_blocks_new_scan_and_upload_work(self):
        self.stage()
        with patch.object(self.app.updates, 'handoff', True), \
             patch.object(self.panel, 'launch') as launch, \
             patch.object(github_ui.messagebox, 'askyesno') as confirm:
            self.panel.scan()
            self.panel.upload()
            launch.assert_not_called()
            confirm.assert_not_called()

    def test_bilingual_small_workspace_and_sidebar_follow_font_metrics(self):
        self.stage()
        self.root.geometry('540x420')
        for locale, label in (('en', 'Scan missing documents'), ('zh', '扫描缺失文档')):
            self.app.change_ui_language(locale); self.root.update()
            self.assertEqual(self.panel.scan_button.cget('text'), label)
            self.assertTrue(self.app.workspace_layout.github_upload.winfo_ismapped())
            self.assertEqual(len(self.panel.candidates), 2)
            self.assertGreaterEqual(self.panel.tree.winfo_reqheight(), 80)
            button = self.app.workspace_layout.github_upload
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
        self.root.geometry('1100x780'); self.root.update()
        rail = self.app.workspace_layout
        self.assertEqual(rail.rail.winfo_width(), rail.rail_width)
        self.root.geometry('1100x480'); self.root.update()
        self.assertTrue(rail.compact)
        self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)

    def test_automatic_upload_respects_original_translation_selection(self):
        path = Path('/tmp/document.md')
        allowed = {'仅上传原文': {'original'}, '仅上传翻译稿': {'translation'}, '同时上传': {'original', 'translation'}}
        for selection in lp.UPLOAD_KINDS:
            for role in ('original', 'translation'):
                snapshot = {'github': lp.GitHubOptions('owner/repo', 'key'), 'upload_kind': selection}
                with self.subTest(selection=selection, role=role), patch('literature_ui.upload_verified_file') as upload:
                    self.c.maybe_upload(path, path.parent, True, snapshot, 'sha', role=role)
                    self.assertEqual(upload.call_count, int(role in allowed[selection]))


if __name__ == '__main__':
    unittest.main()
