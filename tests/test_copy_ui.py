import queue
import tkinter as tk
import unittest
from tkinter import ttk
from unittest.mock import patch

import paddleocr_pdf_to_md_gui as application
import ui_i18n
from responsive_ui import AdaptiveLabel


class CopyInteractionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.root.geometry('640x480')

    def tearDown(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()
        ui_i18n.set_language('zh')

    def show(self, widget):
        widget.pack(fill='both', expand=True)
        ui_i18n.localize_widgets(self.root)
        self.root.update()
        return widget

    def app(self):
        with patch.object(application, 'load_config', return_value=application.AppConfig(token='')), \
                patch.object(application, 'save_config'):
            app = application.PaddleOCRBatchGUI(self.root)
        self.root.update()
        return app

    def test_disabled_text_copies_selection_or_whole_text_without_editing(self):
        text = self.show(tk.Text(self.root))
        text.insert('1.0', '日志第一行\nHTTP 403')
        text.configure(state='disabled')
        text.tag_add('sel', '2.0', '2.end')
        text.event_generate('<<Copy>>')
        self.assertEqual(self.root.clipboard_get(), 'HTTP 403')
        text.tag_remove('sel', '1.0', 'end')
        text.event_generate('<<Copy>>')
        self.assertEqual(self.root.clipboard_get(), '日志第一行\nHTTP 403')
        self.assertEqual(str(text.cget('state')), 'disabled')
        text.focus_force()
        self.root.update()
        text.event_generate('<Control-a>')
        text.event_generate('<Control-c>')
        self.assertEqual(self.root.clipboard_get(), '日志第一行\nHTTP 403')

    def test_entry_selection_copy_and_paste_remain_available(self):
        entry = self.show(ttk.Entry(self.root))
        entry.insert(0, 'C:/文献/原文')
        entry.selection_range(3, 5)
        entry.event_generate('<<Copy>>')
        self.assertEqual(self.root.clipboard_get(), '文献')
        ui_i18n.copy_text(self.root, 'new path')
        entry.selection_range(0, 'end')
        entry.event_generate('<<Paste>>')
        self.assertEqual(entry.get(), 'new path')

    def test_status_label_copy_uses_untruncated_source(self):
        content = '错误详情 ' * 80 + 'END'
        label = self.show(AdaptiveLabel(self.root, text=content, max_lines=1))
        self.assertNotEqual(label.display.get(), content)
        label.event_generate('<<Copy>>')
        self.assertEqual(self.root.clipboard_get(), content)

    def test_context_menu_is_translated_and_cannot_cut_or_paste_disabled_text(self):
        text = self.show(tk.Text(self.root))
        text.insert('1.0', 'read-only report')
        text.configure(state='disabled')
        for locale, caption in (('zh', '复制全部'), ('en', 'Copy all')):
            ui_i18n.set_language(locale)
            with patch.object(tk.Menu, 'tk_popup'):
                text.event_generate('<Button-3>', x=3, y=3)
            menu = text._copy_menu
            self.assertEqual(menu.entrycget(1, 'label'), caption)
            self.assertEqual(menu.entrycget(5, 'state'), 'disabled')
            self.assertEqual(menu.entrycget(6, 'state'), 'disabled')
            menu.invoke(1)
            self.assertEqual(self.root.clipboard_get(), 'read-only report')

    def test_empty_copy_preserves_clipboard_and_localizing_twice_does_not_duplicate_bindings(self):
        text = self.show(tk.Text(self.root))
        binding = text.bind('<<Copy>>')
        ui_i18n.localize_widgets(self.root)
        self.assertEqual(text.bind('<<Copy>>'), binding)
        ui_i18n.copy_text(self.root, 'keep me')
        text.event_generate('<<Copy>>')
        self.assertEqual(self.root.clipboard_get(), 'keep me')

    def test_log_and_update_buttons_copy_full_failure_details_in_both_languages(self):
        app = self.app()
        app.log('HTTP 403: https://api.github.com/example')
        app.workspace_layout.copy_log_button.invoke()
        self.assertIn('HTTP 403', self.root.clipboard_get())
        app.updates.status.set('PowerShell exit code: 1\nParserError')
        app.updates.copy_button.invoke()
        self.assertIn('ParserError', self.root.clipboard_get())
        self.assertIn(application.APP_VERSION, self.root.clipboard_get())
        app.change_ui_language('en')
        self.assertEqual(app.workspace_layout.copy_log_button.cget('text'), 'Copy log')
        self.assertEqual(app.updates.copy_button.cget('text'), 'Copy update details')
        app.updates.copy_button.invoke()
        self.assertIn('Official release', self.root.clipboard_get())

    def test_error_dialog_provides_selectable_body_and_copy_button(self):
        result = []
        def use_dialog():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
            def descendants(widget):
                return [widget] + [item for child in widget.winfo_children() for item in descendants(child)]
            widgets = descendants(dialog)
            text = next(widget for widget in widgets if isinstance(widget, tk.Text))
            text.tag_add('sel', '1.0', '1.end')
            text.event_generate('<<Copy>>')
            result.append(self.root.clipboard_get())
            copy = next(widget for widget in widgets if isinstance(widget, ttk.Button) and widget.cget('text') == 'Copy message')
            copy.invoke()
            result.append(self.root.clipboard_get())
            dialog.destroy()
        ui_i18n.set_language('en')
        self.root.after(50, use_dialog)
        self.assertEqual(ui_i18n.messagebox.showerror('Update failed', 'HTTP 403', detail='Failed URL', parent=self.root), 'ok')
        self.assertEqual(result[0], 'HTTP 403')
        self.assertIn('Update failed\n\nHTTP 403\n\nFailed URL', result[1])

    def test_confirmation_dialogs_keep_their_original_return_value(self):
        with patch.object(ui_i18n._messages, 'askyesno', return_value=False):
            self.assertFalse(ui_i18n.messagebox.askyesno('确认', 'Overwrite?', parent=self.root))

    def test_document_previews_offer_copy_without_resolving_the_dispute(self):
        app = self.app()
        answer = queue.Queue()
        app.literature.decision_dialog({'filename': 'test.md', 'source': 'Original text',
                                       'first': 'First draft', 'problem': {'issues': ['Missing words']}}, answer, lambda: False)
        self.root.update()
        dialog = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel)
                      and child.title().startswith('处理问题'))
        notebook = next(child for child in dialog.winfo_children() if isinstance(child, ttk.Notebook))
        page = dialog.nametowidget(notebook.tabs()[0])
        copy = next(child for child in page.winfo_children() if isinstance(child, ttk.Button))
        copy.invoke()
        self.assertEqual(self.root.clipboard_get(), 'Original text')
        self.assertTrue(answer.empty())
        dialog.destroy()
