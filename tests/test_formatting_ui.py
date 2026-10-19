import json
import queue
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import literature_processing as lp
import literature_ui
import paddleocr_pdf_to_md_gui as application
from ui_i18n import set_language
from test_literature_ui import assert_english_captions


class FormattingAndServiceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        self.addCleanup(self.cleanup_root)
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.load = patch.object(application, 'load_config', return_value=application.AppConfig(token='paddle-only'))
        self.save = patch.object(application, 'save_config')
        self.load.start(); self.save.start()
        self.addCleanup(self.load.stop); self.addCleanup(self.save.stop)
        self.addCleanup(set_language, 'zh')
        self.app = application.PaddleOCRBatchGUI(self.root)
        self.c = self.app.literature
        self.root.update()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'paper.md'
        self.source.write_text('Title\n\nRead 12 papers.\n')

    def cleanup_root(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()

    def formatter(self):
        self.c.open_formatting()
        panel = self.c.formatting
        panel.input.set(str(self.source))
        for model in panel.models.values():
            model.url.set('https://example.invalid/v1')
            model.key.set('format-key')
            model.model.set('model')
        self.root.update()
        return panel

    def wait(self, panel):
        deadline = time.monotonic() + 3
        while panel.busy and time.monotonic() < deadline:
            self.root.update(); time.sleep(.01)
        self.assertFalse(panel.busy)

    def test_shared_provider_covers_all_llm_roles_including_ocr_check_but_not_paddleocr(self):
        panel = self.formatter()
        original_paddle = (self.app.config.token, self.app.model_var.get(), self.app.token_state_var.get())
        models = [*self.c.profiles.values(), *panel.models.values()]
        for i, model in enumerate(models):
            model.model.set('role-model-' + str(i))
        self.c.shared_url.set('https://one-provider.invalid/v1')
        self.c.shared_key.set('shared-key')
        self.c.shared_llm.set(True)
        style = application.ttk.Style(self.root)
        self.assertEqual(style.lookup('TCombobox', 'fieldbackground', ('disabled',)),
                         style.lookup('TEntry', 'fieldbackground', ('disabled',)))
        for i, model in enumerate(models):
            self.assertEqual((model.url.get(), model.key.get()), ('https://one-provider.invalid/v1', 'shared-key'))
            self.assertEqual(model.model.get(), 'role-model-' + str(i))
            self.assertEqual(str(model.provider_selector.cget('state')), 'disabled')
            self.assertEqual(str(model.url_entry.cget('state')), 'disabled')
            self.assertEqual(str(model.key_entry.cget('state')), 'disabled')
            self.assertNotEqual(str(model.combo.cget('state')), 'disabled')
        self.assertEqual((self.app.llm_base_url_var.get(), self.app.llm_api_key_var.get()), ('https://one-provider.invalid/v1', 'shared-key'))
        self.assertEqual((self.app.config.token, self.app.model_var.get(), self.app.token_state_var.get()), original_paddle)
        self.c.shared_key.set('rotated-key')
        self.assertTrue(all(model.key.get() == 'rotated-key' for model in models))
        self.assertEqual(self.c.config_data()['llm_service']['enabled'], True)

    def test_shared_setting_applies_to_formatting_window_opened_later(self):
        self.c.shared_url.set('https://shared.invalid/v1'); self.c.shared_key.set('new-key'); self.c.shared_llm.set(True)
        self.c.open_formatting()
        for model in self.c.formatting.models.values():
            self.assertEqual(model.url.get(), 'https://shared.invalid/v1')
            self.assertEqual(model.key.get(), 'new-key')
            self.assertEqual(str(model.key_entry.cget('state')), 'disabled')

    def test_cancel_and_accept_override_require_the_exact_prompt_and_unlock_all_connections(self):
        self.c.shared_llm.set(True)
        model = self.c.profiles['translator']
        target = model.url_entry
        event = SimpleNamespace(widget=target)
        with patch.object(literature_ui.messagebox, 'askyesno', return_value=False) as ask:
            self.assertEqual(self.c.override_shared_llm(event), 'break')
        self.assertEqual(ask.call_args.args[1], '您已选择“所有服务共用一个LLM服务商”，是否需要强制覆盖设置？')
        self.assertTrue(self.c.shared_llm.get())
        self.assertEqual(str(target.cget('state')), 'disabled')
        with patch.object(literature_ui.messagebox, 'askyesno', return_value=True):
            self.c.override_shared_llm(event)
        self.assertFalse(self.c.shared_llm.get())
        self.assertEqual(str(target.cget('state')), 'normal')
        self.assertEqual(str(model.provider_selector.cget('state')), 'readonly')
        self.assertEqual(str(self.app.shared_review_key_entry.cget('state')), 'normal')
        model.url.set('https://separate.invalid/v1')
        self.assertNotEqual(self.c.profiles['reviewer'].url.get(), model.url.get())

    def test_disabled_connection_click_prompts_and_closed_combo_wheels_never_change_provider(self):
        self.app.workspace_layout.show_settings(1); self.root.update()
        model = self.c.profiles['translator']
        for shared in (False, True):
            self.c.shared_llm.set(shared)
            before = (model.provider.get(), model.url.get(), model.key.get())
            with patch.object(literature_ui.messagebox, 'askyesno') as ask:
                for event, kwargs in (('<MouseWheel>', {'delta': -120}), ('<Button-4>', {}), ('<Button-5>', {})):
                    model.provider_selector.event_generate(event, **kwargs)
                    self.root.update()
                ask.assert_not_called()
            self.assertEqual((model.provider.get(), model.url.get(), model.key.get()), before)
        with patch.object(literature_ui.messagebox, 'askyesno', return_value=False) as ask:
            model.provider_selector.event_generate('<Button-1>'); self.root.update()
        ask.assert_called_once()
        self.assertTrue(self.c.shared_llm.get())

    def test_global_provider_presets_still_change_by_explicit_selection(self):
        self.c.shared_provider.set('Kimi / Moonshot')
        self.c.shared_key.set('previous-provider-key')
        self.c.shared_preset()
        self.assertEqual(self.c.shared_url.get(), lp.PROVIDERS['Kimi / Moonshot'])
        self.assertEqual(self.c.shared_key.get(), '')

    def test_formatting_window_paths_save_lock_and_bilingual_compact_controls(self):
        panel = self.formatter()
        self.assertEqual(panel.output.get(), str(self.folder))
        self.assertEqual(str(panel.output_entry.cget('state')), 'disabled')
        root, paths, output = panel.paths()
        self.assertEqual((root, paths, output), (self.folder, [self.source], None))
        panel.window.geometry('540x420')
        for locale, label in (('en', 'Start formatting and verification'), ('zh', '开始整理并核验')):
            self.app.change_ui_language(locale); self.root.update()
            self.assertEqual(panel.start_button.cget('text'), label)
            if locale == 'en':
                assert_english_captions(self, panel.window, self.app.workspace_layout.language_selector)
                self.assertGreaterEqual(panel.input_entry.winfo_width(), 150)
            self.assertTrue(panel.start_button.winfo_viewable())
            self.assertLessEqual(panel.start_button.winfo_rooty() + panel.start_button.winfo_height(), panel.window.winfo_rooty() + panel.window.winfo_height())
        panel.close(); self.c.open_formatting()
        self.assertIs(self.c.formatting, panel)
        self.assertEqual(self.c.config_data()['formatting']['input'], str(self.source))

    def test_single_pass_worker_is_guarded_from_updates_and_never_uploads_automatically(self):
        panel = self.formatter()
        def chat(profile, prompt, data, stop, input_percent):
            self.assertTrue(self.app.updates.app_busy())
            return '# Title\n\nRead 12 papers.' if prompt == lp.FORMAT_PROMPT else '{"has_problem":false,"issues":[]}'
        with patch.object(lp, 'chat', side_effect=chat) as request, patch.object(self.c, 'maybe_upload') as upload:
            panel.start(); self.wait(panel)
        self.assertEqual(request.call_count, 2)
        self.assertTrue((self.folder / 'paper_FORMATTED.md').exists())
        self.assertIn('通过 1', panel.status.get())
        upload.assert_not_called()
        self.assertFalse(self.app.updates.app_busy())

    def test_generation_error_can_retry_without_deleting_source(self):
        panel = self.formatter()
        result = {'status': 'verified'}
        with patch.object(lp, 'format_markdown_document', side_effect=[RuntimeError('HTTP 503'), result]) as work, \
                patch.object(self.c, 'decide', return_value='retry') as decide:
            panel.start(); self.wait(panel)
        self.assertEqual(work.call_count, 2)
        self.assertIsNone(decide.call_args.args[0]['first'])
        self.assertIn('503', decide.call_args.args[0]['problem'])
        self.assertEqual(self.source.read_text(), 'Title\n\nRead 12 papers.\n')

    def test_stopping_while_waiting_for_a_draft_choice_closes_dialog_without_output(self):
        panel = self.formatter()
        with patch.object(lp, 'chat', side_effect=['# Title\n\nRead 12 papers.',
                '{"has_problem":true,"issues":["Review needed"]}']):
            panel.start()
            deadline = time.monotonic() + 3
            dialog = None
            while time.monotonic() < deadline:
                self.root.update()
                windows = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
                           and w.winfo_viewable() and w not in (panel.window, self.app.workspace_layout.settings)]
                if windows:
                    dialog = windows[0]
                    break
                time.sleep(.01)
            self.assertIsNotNone(dialog)
            panel.cancel.set()
            self.wait(panel)
            while dialog.winfo_exists() and time.monotonic() < deadline:
                self.root.update(); time.sleep(.01)
        self.assertFalse(dialog.winfo_exists())
        self.assertFalse((self.folder / 'paper_FORMATTED.md').exists())
        self.assertEqual(self.source.read_text(), 'Title\n\nRead 12 papers.\n')

    def dialog(self, second=False, first=True):
        response = queue.Queue()
        payload = {'filename': 'paper.md', 'source': 'source', 'first': 'first' if first else None,
                   'problem': {'issues': ['Missing a word']}}
        if second:
            payload['second'] = 'second'
        self.c.decision_dialog(payload, response)
        self.root.update()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable() and w != self.app.workspace_layout.settings)
        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, application.ttk.Button):
                    yield child
                yield from buttons(child)
        return dialog, response, list(buttons(dialog))

    def test_problem_dialog_shows_two_or_three_choices_and_retry_discards_current_attempt(self):
        for second in (False, True):
            dialog, response, buttons = self.dialog(second)
            labels = [b.cget('text') for b in buttons]
            self.assertIn('保留第一稿', labels)
            self.assertIn('删除并重试上一步', labels)
            self.assertEqual('保留第二稿' in labels, second)
            dialog.geometry('480x360'); self.root.update()
            for b in buttons:
                self.assertLessEqual(b.winfo_rooty() + b.winfo_height(), dialog.winfo_rooty() + dialog.winfo_height())
            next(b for b in buttons if b.cget('text') == '删除并重试上一步').invoke()
            self.assertEqual(response.get_nowait(), 'retry')
        dialog, response, buttons = self.dialog(first=False)
        self.assertNotIn('保留第一稿', [b.cget('text') for b in buttons])
        next(b for b in buttons if b.cget('text') == '跳过此文件').invoke()
        self.assertEqual(response.get_nowait(), 'unresolved')

    def test_problem_dialog_and_override_prompt_have_full_english_captions(self):
        self.app.change_ui_language('en')
        dialog, response, buttons = self.dialog(True)
        self.assertEqual([b.cget('text') for b in buttons if b.cget('text') != 'Copy full text'],
                         ['Keep first draft', 'Discard and retry previous step', 'Keep second draft'])
        self.assertEqual(sum(b.cget('text') == 'Copy full text' for b in buttons), 4)
        next(b for b in buttons if b.cget('text') == 'Keep second draft').invoke()
        self.assertEqual(response.get_nowait(), 'second')
        self.c.shared_llm.set(True)
        with patch.object(literature_ui.messagebox, 'askyesno', return_value=False) as ask:
            self.c.override_shared_llm(SimpleNamespace(widget=self.c.profiles['translator'].url_entry))
        self.assertNotRegex(str(ask.call_args.args), r'[\u4e00-\u9fff]')


class SharedServiceStartupTest(unittest.TestCase):
    def test_first_shared_setup_reuses_an_existing_llm_connection_without_touching_paddleocr(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        try:
            application.configure_unicode_ui_fonts(root)
            application.configure_design_language(root)
            config = application.AppConfig(token='paddle-token', literature={'translator': {
                'base_url': 'https://api.moonshot.cn/v1', 'api_key': 'existing-llm-key', 'model': 'kimi'}})
            with patch.object(application, 'load_config', return_value=config), patch.object(application, 'save_config'):
                app = application.PaddleOCRBatchGUI(root)
                c = app.literature
                self.assertFalse(c.shared_llm.get())
                self.assertEqual((c.shared_url.get(), c.shared_key.get()), ('https://api.moonshot.cn/v1', 'existing-llm-key'))
                c.shared_llm.set(True)
                self.assertTrue(all(model.key.get() == 'existing-llm-key' for model in c.profiles.values()))
                self.assertEqual(app.config.token, 'paddle-token')
        finally:
            for timer in root.tk.call('after', 'info'):
                root.after_cancel(timer)
            root.destroy()
            set_language('zh')

if __name__ == '__main__':
    unittest.main()
