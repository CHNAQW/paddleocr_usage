import queue
import time
import tkinter as tk
import unittest
from tkinter import ttk
from unittest.mock import patch

import paddleocr_pdf_to_md_gui as application
import ui_i18n
from responsive_ui import AdaptiveCheckbutton, AdaptiveLabel


class CopyInteractionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.root.geometry('640x480')
        self.callback_errors = []
        def callback_error(_kind, value, _traceback):
            self.callback_errors.append(value)
            for child in self.root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
        self.root.report_callback_exception = callback_error

    def tearDown(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()
        ui_i18n.set_language('zh')
        self.assertEqual(self.callback_errors, [])

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

    def test_copy_context_menu_preserves_a_modal_dialog_grab(self):
        dialog = tk.Toplevel(self.root)
        text = tk.Text(dialog)
        text.pack()
        text.insert('1.0', 'diagnostic')
        ui_i18n.localize_widgets(dialog)
        self.root.update()
        dialog.grab_set()
        def popup_without_native_wait(*_args):
            # Windows waits inside its native menu until a person selects an
            # item. Simulate its grab change while testing our restoration.
            self.assertEqual(self.root.grab_current(), dialog)
            dialog.grab_release()
            self.assertIsNone(self.root.grab_current())
        with patch.object(tk.Menu, 'tk_popup', side_effect=popup_without_native_wait) as popup:
            text.event_generate('<Button-3>', x=3, y=3)
            popup.assert_called_once()
        self.assertEqual(self.root.grab_current(), dialog)
        text._copy_menu.invoke(1)
        self.assertEqual(self.root.clipboard_get(), 'diagnostic')
        text._copy_menu.unpost()
        dialog.destroy()

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

    def test_log_copy_keeps_full_retained_message_after_display_truncation(self):
        app = self.app()
        original = "OCR response " * 2500 + "COMPLETE-END"
        app.log(original)
        self.assertNotIn("COMPLETE-END", app.log_text.get("1.0", "end"))
        app.workspace_layout.copy_log_button.invoke()
        self.assertIn(original, self.root.clipboard_get())
        # No-selection copy and the context menu's Copy all use retained history;
        # an explicit selection still copies only the selected visible text.
        app.log_text.event_generate("<<Copy>>")
        self.assertIn(original, self.root.clipboard_get())
        app.log_text.tag_add("sel", "1.0", "1.5")
        selected = app.log_text.get("sel.first", "sel.last")
        app.log_text.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), selected)
        app.change_ui_language("en")
        app.workspace_layout.copy_log_button.invoke()
        self.assertIn(original, self.root.clipboard_get())

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

    def dialog_widgets(self):
        dialog = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        def descendants(widget):
            return [widget] + [item for child in widget.winfo_children() for item in descendants(child)]
        return dialog, descendants(dialog)

    def test_confirmation_buttons_keep_native_return_values_and_copy_does_not_confirm(self):
        cases = (("askyesno", "是", True), ("askyesno", "否", False),
                 ("askyesnocancel", "取消", None), ("askokcancel", "确定", True),
                 ("askokcancel", "取消", False), ("askretrycancel", "重试", True),
                 ("askquestion", "否", "no"))
        for name, caption, expected in cases:
            with self.subTest(name=name, caption=caption):
                def use_dialog():
                    dialog, widgets = self.dialog_widgets()
                    text = next(widget for widget in widgets if isinstance(widget, tk.Text))
                    text.event_generate("<<Copy>>")
                    self.assertEqual(self.root.clipboard_get(), "Overwrite?\n\nFull details")
                    self.assertTrue(dialog.winfo_exists())
                    button = next(widget for widget in widgets if isinstance(widget, ttk.Button)
                                  and widget.cget("text") == caption)
                    button.invoke()
                self.root.after(30, use_dialog)
                result = getattr(ui_i18n.messagebox, name)("Confirm", "Overwrite?", detail="Full details", parent=self.root)
                self.assertIs(result, expected) if expected is None or isinstance(expected, bool) else self.assertEqual(result, expected)

    def test_confirmation_keyboard_defaults_are_safe_and_focused_yes_is_explicit(self):
        for key, focus_yes, expected in (("<Return>", False, False), ("<Escape>", True, False),
                                         ("<Return>", True, True)):
            with self.subTest(key=key, focus_yes=focus_yes):
                def respond():
                    _dialog, widgets = self.dialog_widgets()
                    target = (next(widget for widget in widgets if isinstance(widget, ttk.Button) and widget.cget("text") == "是")
                              if focus_yes else next(widget for widget in widgets if isinstance(widget, tk.Text)))
                    target.focus_force()
                    self.root.after(20, lambda: target.event_generate(key))
                def timeout():
                    self.callback_errors.append(AssertionError("Confirmation key did not close the dialog"))
                    dialog, _widgets = self.dialog_widgets()
                    dialog.destroy()
                self.root.after(30, respond)
                watchdog = self.root.after(2000, timeout)
                try:
                    self.assertEqual(ui_i18n.messagebox.askyesno("Confirm", "Question", parent=self.root), expected)
                finally:
                    self.root.after_cancel(watchdog)

    def test_confirmation_parent_destruction_returns_cancel_without_grab_errors(self):
        parent = tk.Toplevel(self.root)
        parent.grab_set()
        self.root.after(40, parent.destroy)
        self.assertIsNone(ui_i18n.messagebox.askyesnocancel("Confirm", "Question", parent=parent))

    def test_confirmation_explicit_default_and_window_close_keep_native_semantics(self):
        for kind, default, action, expected in (
                ("askyesno", "yes", "enter", True),
                ("askyesno", "invalid", "close", False),
                ("askyesnocancel", "yes", "close", None)):
            with self.subTest(kind=kind, action=action):
                def respond():
                    dialog, widgets = self.dialog_widgets()
                    if action == "close":
                        dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))
                    else:
                        body = next(widget for widget in widgets if isinstance(widget, tk.Text))
                        body.focus_force()
                        self.root.after(20, lambda: body.event_generate("<Return>"))
                self.root.after(30, respond)
                watchdog = self.root.after(2000, lambda: self.dialog_widgets()[0].destroy())
                try:
                    self.assertEqual(getattr(ui_i18n.messagebox, kind)(
                        "Confirm", "Question", default=default, parent=self.root), expected)
                finally:
                    self.root.after_cancel(watchdog)

    def test_labels_buttons_groups_and_wrapped_checkbuttons_copy_complete_captions(self):
        content = "This is a very long checkbox caption " * 20 + "END"
        controls = [
            (ttk.Button(self.root, text="Action caption"), "Action caption"),
            (ttk.Radiobutton(self.root, text="Choice caption"), "Choice caption"),
            (ttk.LabelFrame(self.root, text="Group caption"), "Group caption"),
            (tk.Message(self.root, text="Message caption"), "Message caption"),
            (AdaptiveCheckbutton(self.root, text=content), content),
        ]
        for widget, _ in controls:
            widget.pack(fill="x")
        ui_i18n.localize_widgets(self.root)
        self.root.update()
        for widget, expected in controls:
            with self.subTest(widget=widget):
                widget.event_generate("<<Copy>>")
                self.assertEqual(self.root.clipboard_get(), expected)
                with patch.object(tk.Menu, "tk_popup"):
                    widget.event_generate("<Button-3>", x=2, y=2)
                widget._copy_menu.invoke(0)
                self.assertEqual(self.root.clipboard_get(), expected)

    def test_disabled_and_readonly_fields_copy_whole_value_when_nothing_selected(self):
        for cls in (ttk.Entry, ttk.Combobox):
            for state in ("readonly", "disabled"):
                with self.subTest(cls=cls, state=state):
                    variable = tk.StringVar(self.root, value="Full path / 完整内容")
                    widget = cls(self.root, textvariable=variable)
                    widget.configure(state=state)
                    self.show(widget)
                    widget.event_generate("<<Copy>>")
                    self.assertEqual(self.root.clipboard_get(), "Full path / 完整内容")
                    self.assertEqual(str(widget.cget("state")), state)
                    widget.destroy()

    def test_treeview_copies_headings_nested_rows_and_right_clicked_column(self):
        tree = self.show(ttk.Treeview(self.root, columns=("name", "status"), show="headings"))
        tree.heading("name", text="Full filename")
        tree.heading("status", text="Status")
        first = tree.insert("", "end", values=("original.md", "Verified"))
        tree.insert(first, "end", values=("nested.md", "Complete"))
        tree.insert("", "end", values=("second.md", "Pending"))
        self.root.update()
        tree.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(),
                         "Full filename\tStatus\noriginal.md\tVerified\nnested.md\tComplete\nsecond.md\tPending")
        tree.selection_set(first)
        tree.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), "original.md\tVerified")
        with patch.object(tk.Menu, "tk_popup"):
            tree.event_generate("<Button-3>", x=5, y=5)
        tree._copy_menu.invoke(0)
        self.assertEqual(self.root.clipboard_get(), "Full filename")
        self.assertEqual(tree.selection(), (first,))

    def finish_copy(self):
        deadline = time.monotonic() + 5
        while getattr(self.root, "_pending_text_copy", None) is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.002)
        self.assertIsNone(getattr(self.root, "_pending_text_copy", None))

    def test_large_table_copy_yields_to_gui_and_keeps_all_rows(self):
        tree = self.show(ttk.Treeview(self.root, columns=("file", "status"), show="headings"))
        tree.heading("file", text="File")
        tree.heading("status", text="Status")
        for index in range(1200):
            tree.insert("", "end", values=(f"paper-{index}.md", "Verified"))
        ui_i18n.copy_text(self.root, "previous clipboard")
        heartbeat = []
        self.root.after(0, lambda: heartbeat.append(self.root.clipboard_get()))
        tree.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), "previous clipboard")
        self.finish_copy()
        self.assertEqual(heartbeat, ["previous clipboard"])
        copied = self.root.clipboard_get().splitlines()
        self.assertEqual(len(copied), 1201)
        self.assertEqual(copied[-1], "paper-1199.md\tVerified")

    def test_new_copy_and_destroyed_source_cancel_pending_large_copy(self):
        for action in ("copy", "destroy"):
            with self.subTest(action=action):
                tree = self.show(ttk.Treeview(self.root, columns=("file",), show="headings"))
                for index in range(1000):
                    tree.insert("", "end", values=(f"paper-{index}.md",))
                ui_i18n.copy_text(self.root, "previous clipboard")
                ui_i18n.copy_interface_text(tree)
                self.assertIsNotNone(self.root._pending_text_copy)
                if action == "copy":
                    ui_i18n.copy_text(self.root, "newer explicit copy")
                else:
                    tree.destroy()
                self.finish_copy()
                self.assertEqual(self.root.clipboard_get(),
                                 "newer explicit copy" if action == "copy" else "previous clipboard")
                if action == "copy":
                    tree.destroy()

    def test_rebuilt_table_with_reused_row_ids_does_not_copy_mixed_generations(self):
        tree = self.show(ttk.Treeview(self.root, columns=("file",), show="headings"))
        for index in range(1000):
            tree.insert("", "end", iid=str(index), values=(f"old-{index}.md",))
        ui_i18n.copy_text(self.root, "previous clipboard")
        tree.event_generate("<<Copy>>")
        ui_i18n.invalidate_copy(tree)
        tree.delete(*tree.get_children())
        for index in range(1000):
            tree.insert("", "end", iid=str(index), values=(f"new-{index}.md",))
        self.finish_copy()
        self.assertEqual(self.root.clipboard_get(), "previous clipboard")

    def test_oversized_notice_limits_display_but_copies_complete_message(self):
        content = "Large diagnostic line\n" * 20000 + "FULL-END"
        def inspect():
            dialog, widgets = self.dialog_widgets()
            body = next(widget for widget in widgets if isinstance(widget, tk.Text))
            self.assertLess(len(body.get("1.0", "end-1c")), 101000)
            body.event_generate("<<Copy>>")
            self.assertEqual(self.root.clipboard_get(), content)
            button = next(widget for widget in widgets if isinstance(widget, ttk.Button)
                          and widget.cget("text") == "复制信息")
            button.invoke()
            self.assertEqual(self.root.clipboard_get(), "Diagnostic\n\n" + content)
            dialog.destroy()
        self.root.after(50, inspect)
        watchdog = self.root.after(3000, lambda: self.dialog_widgets()[0].destroy())
        try:
            ui_i18n.messagebox.showinfo("Diagnostic", content, parent=self.root)
        finally:
            self.root.after_cancel(watchdog)

    def test_notebook_tab_copy_does_not_select_it_and_window_copy_includes_all_pages(self):
        notebook = self.show(ttk.Notebook(self.root))
        for title, body in (("First section", "First body"), ("Second section", "Second body")):
            page = ttk.Frame(notebook)
            ttk.Label(page, text=body).pack()
            notebook.add(page, text=title)
        ui_i18n.localize_widgets(self.root)
        self.root.update()
        selected = notebook.select()
        x = next(x for x in range(1, notebook.winfo_width()) if self._tab_index(notebook, x) == 1)
        with patch.object(tk.Menu, "tk_popup"):
            notebook.event_generate("<Button-3>", x=x, y=5)
        notebook._copy_menu.invoke(0)
        self.assertEqual(self.root.clipboard_get(), "Second section")
        self.assertEqual(notebook.select(), selected)
        text = ui_i18n.interface_text(self.root)
        self.assertIn("[First section]\nFirst body\n[Second section]\nSecond body", text)

    @staticmethod
    def _tab_index(notebook, x):
        try:
            return notebook.index("@%s,5" % x)
        except tk.TclError:
            return None

    def test_whole_interface_shortcut_copies_title_and_full_text_but_masks_keys(self):
        self.root.title("Window title")
        secret = ttk.Entry(self.root, show="*")
        secret.insert(0, "api-key-secret")
        secret.pack()
        long_text = "License body " * 2000 + "LICENSE-END"
        label = AdaptiveLabel(self.root, text=long_text, max_lines=1)
        label.pack(fill="x")
        other = tk.Toplevel(self.root)
        other.title("Other dialog")
        ttk.Label(other, text="Other dialog's private content").pack()
        ui_i18n.localize_widgets(self.root)
        self.root.update()
        secret.selection_range(0, "end")
        secret.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), "api-key-secret")
        secret.event_generate("<<CopyInterface>>")
        copied = self.root.clipboard_get()
        self.assertTrue(copied.startswith("Window title\n"))
        self.assertIn(long_text, copied)
        self.assertIn("*" * len("api-key-secret"), copied)
        self.assertNotIn("api-key-secret", copied)
        self.assertNotIn("Other dialog's private content", copied)
        other.destroy()

    def test_native_combobox_dropdown_supports_copy_without_changing_choice(self):
        combo = self.show(ttk.Combobox(self.root, state="readonly", values=("First option", "Second option")))
        combo.current(0)
        combo.tk.call("ttk::combobox::Post", combo)
        self.root.update()
        popup = str(combo.tk.call("ttk::combobox::PopdownWindow", combo))
        def listbox(path):
            for child in combo.tk.splitlist(combo.tk.call("winfo", "children", path)):
                if combo.tk.call("winfo", "class", child) == "Listbox":
                    return str(child)
                found = listbox(child)
                if found:
                    return found
            return None
        path = listbox(popup)
        self.assertIsNotNone(path)
        combo.tk.call(path, "selection", "clear", 0, "end")
        combo.tk.call(path, "selection", "set", 1)
        combo.tk.call("event", "generate", path, "<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), "Second option")
        with patch.object(tk.Menu, "tk_popup"):
            combo.tk.call("event", "generate", path, "<Button-3>", "-x", 3, "-y", 3)
        self.root._dropdown_copy_menu.invoke(1)
        self.assertEqual(self.root.clipboard_get(), "First option\nSecond option")
        self.assertEqual(combo.get(), "First option")

    def test_widgets_created_later_receive_copy_support_when_mapped(self):
        ui_i18n.localize_widgets(self.root)
        button = ttk.Button(self.root, text="Late button")
        button.pack()
        self.root.update()
        button.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), "Late button")

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
