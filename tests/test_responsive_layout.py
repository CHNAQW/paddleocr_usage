import tkinter as tk
from tkinter import font as tkfont, ttk
import unittest
from unittest.mock import patch

import paddleocr_pdf_to_md_gui as application
from responsive_ui import AdaptiveCheckbutton, fit_lines
from ui_i18n import set_language


class CompactLabelTextTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        self.addCleanup(self.root.destroy)

    def test_hiding_additional_lines_preserves_complete_version_when_it_fits(self):
        font = tkfont.nametofont("TkDefaultFont", root=self.root)
        version = "27.1.1.1"
        width = font.measure(version + "…") + 50
        self.assertEqual(fit_lines(version + "\n" + "Release notes " * 100, width, 1, font),
                         version + "…")

    def test_ellipsis_reserves_its_measured_width_instead_of_two_characters(self):
        for size in (10, 16):
            with self.subTest(size=size):
                font = tkfont.Font(root=self.root, family="Arial", size=size)
                prefix = "WWWiii1234"
                width = font.measure(prefix + "…")
                result = fit_lines(prefix + "567890ABCDEFGHIJKLMN", width, 1, font)
                self.assertEqual(result, prefix + "…")
                self.assertLessEqual(font.measure(result), width)


class ResponsiveLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        cls.load = patch.object(application, 'load_config', return_value=application.AppConfig(token=''))
        cls.save = patch.object(application, 'save_config')
        cls.load.start()
        cls.save.start()
        application.configure_unicode_ui_fonts(cls.root)
        application.configure_design_language(cls.root)
        cls.app = application.PaddleOCRBatchGUI(cls.root)
        cls.shell = cls.app.workspace_layout
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.root.tk.call('after', 'info'):
            cls.root.tk.call("after", "cancel", timer)
        cls.root.destroy()
        cls.load.stop()
        cls.save.stop()
        set_language('zh')

    def assert_inside(self, widget, window):
        self.assertTrue(widget.winfo_viewable(), str(widget))
        self.assertGreaterEqual(widget.winfo_rootx(), window.winfo_rootx())
        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), window.winfo_rootx() + window.winfo_width())
        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), window.winfo_rooty() + window.winfo_height())

    def test_log_drag_is_bounded_and_form_remains_scrollable_after_resize(self):
        self.shell.settings.withdraw()
        for locale in ('zh', 'en'):
            self.app.change_ui_language(locale)
            for size in ('1100x820', '540x420'):
                self.root.geometry(size)
                self.app.notebook.select(0)
                self.root.update()
                panes = self.app.workspace_panes
                x, y = panes.sash_coord(0)
                panes.event_generate('<ButtonPress-1>', x=x + 10, y=y + 2)
                panes.event_generate('<B1-Motion>', x=x + 10, y=0)
                panes.event_generate('<ButtonRelease-1>', x=x + 10, y=0)
                self.root.update()
                self.assertGreaterEqual(self.app.notebook.winfo_height(), int(panes.panecget(self.app.notebook, 'minsize')))
                self.assertGreaterEqual(self.app.notebook.winfo_height(), 64)
                self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
                self.assertLessEqual(self.app.notebook.winfo_rooty() + self.app.notebook.winfo_height(), self.shell.log_frame.winfo_rooty())
                outer = self.root.nametowidget(self.app.notebook.select())
                canvas = next(w for w in outer.winfo_children() if isinstance(w, tk.Canvas))
                self.assertLess(canvas.yview()[1] - canvas.yview()[0], 1)
                canvas.yview_moveto(1)
                self.assertGreater(canvas.yview()[0], 0)
                self.assert_inside(self.app.start_btn, self.root)
                canvas.yview_moveto(0)

    def test_every_preferences_section_is_accessible_in_narrow_english_window(self):
        self.app.change_ui_language('en')
        self.root.geometry('540x420')
        self.shell.show_settings(0)
        self.shell.settings.geometry('440x340')
        self.root.update()
        selector = self.shell.settings_selector
        self.assertTrue(selector.winfo_viewable())
        self.assertEqual(len(selector.cget('values')), 7)
        for index in range(7):
            selector.current(index)
            selector.event_generate('<<ComboboxSelected>>')
            self.root.update()
            self.assertEqual(self.shell.settings_tabs.index(self.shell.settings_tabs.select()), index)
            self.assert_inside(selector, self.shell.settings)
            outer = self.root.nametowidget(self.shell.settings_tabs.select())
            canvas = next(w for w in outer.winfo_children() if isinstance(w, tk.Canvas))
            content = canvas.winfo_children()[0]
            self.assertEqual(content.winfo_width(), canvas.winfo_width())
        self.shell.settings.geometry('1000x650')
        self.root.update()
        self.assertFalse(selector.winfo_ismapped())
        self.shell.settings.withdraw()

    def test_checkboxes_wrap_complete_caption_and_relocalize_at_large_font(self):
        window = tk.Toplevel(self.root)
        window.geometry('280x220')
        style = ttk.Style(window)
        previous = style.lookup('TCheckbutton', 'font')
        style.configure('TCheckbutton', font=('DejaVu Sans', 18))
        try:
            variable = tk.BooleanVar(master=window)
            button = AdaptiveCheckbutton(window, text='所有 LLM 共用同一服务商与 API Key', variable=variable)
            button.pack(fill='x', padx=12)
            self.app.change_ui_language('en')
            self.root.update()
            self.assertIn('\n', button.display.get())
            self.assertEqual(' '.join(button.display.get().split()), ' '.join(button.source.get().split()))
            font = tkfont.Font(root=window, font=style.lookup('TCheckbutton', 'font'))
            for line in button.display.get().splitlines():
                self.assertLessEqual(font.measure(line), button.winfo_width() - 30)
            button.invoke()
            self.assertTrue(variable.get())
            self.app.change_ui_language('zh')
            self.root.update()
            self.assertIn('所有', button.cget('text'))
        finally:
            style.configure('TCheckbutton', font=previous)
            window.destroy()

    def test_github_wizard_navigation_wraps_in_english_small_window(self):
        self.app.change_ui_language('en')
        self.app.literature.github_setup.open()
        wizard = self.app.literature.github_setup.wizard
        try:
            wizard.window.geometry('480x420')
            for step in range(4):
                wizard.show(step)
                self.root.update()
                for button in wizard.navigation.buttons:
                    self.assert_inside(button, wizard.window)
        finally:
            wizard.close()


class ScaledLogLayoutTests(unittest.TestCase):
    def assert_log_fits(self, app, dpi, locale):
        shell = app.workspace_layout
        widgets = {"root": app.root, "navigation": shell.rail, "header": shell.header,
                   "toolbar": shell.toolbar, "actions": shell.actions, "panes": app.workspace_panes,
                   "document": app.notebook, "log_header": shell.log_header,
                   "log_frame": shell.log_frame, "log_text": app.log_text}
        geometry = {name: (widget.winfo_width(), widget.winfo_height(), widget.winfo_reqheight())
                    for name, widget in widgets.items()}
        diagnostic = f"DPI={dpi}, locale={locale}, minsize={app.root.minsize()}, width/height/reqheight={geometry}"
        self.assertGreaterEqual(app.log_text.winfo_height(), 40, diagnostic)
        self.assertGreaterEqual(app.notebook.winfo_height(), 64, diagnostic)
        self.assertLessEqual(app.log_text.winfo_rooty() + app.log_text.winfo_height(),
                             app.root.winfo_rooty() + app.root.winfo_height(), diagnostic)

    def test_log_and_task_viewport_fit_at_96_and_100_dpi(self):
        for dpi in (96, 100):
            with self.subTest(dpi=dpi):
                try:
                    root = tk.Tk()
                except tk.TclError as exc:
                    raise unittest.SkipTest(str(exc))
                previous_scaling = root.tk.call('tk', 'scaling')
                try:
                    root.tk.call('tk', 'scaling', dpi / 72)
                    application.configure_unicode_ui_fonts(root)
                    application.configure_design_language(root)
                    with patch.object(application, 'load_config', return_value=application.AppConfig(token='')), \
                            patch.object(application, 'save_config'):
                        app = application.PaddleOCRBatchGUI(root)
                        for locale in ('zh', 'en'):
                            app.change_ui_language(locale)
                            root.geometry('540x420')
                            root.update()
                            self.assert_log_fits(app, dpi, locale)
                finally:
                    for timer in root.tk.call('after', 'info'):
                        root.tk.call("after", "cancel", timer)
                    root.tk.call('tk', 'scaling', previous_scaling)
                    root.destroy()
                    set_language('zh')

    def test_extra_toolbar_row_reserves_log_space_and_minimum_recovers_after_resize(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        previous_scaling = root.tk.call("tk", "scaling")
        try:
            root.tk.call("tk", "scaling", 100 / 72)
            application.configure_unicode_ui_fonts(root)
            application.configure_design_language(root)
            with patch.object(application, "load_config", return_value=application.AppConfig(token="")), \
                    patch.object(application, "save_config"):
                app = application.PaddleOCRBatchGUI(root)
                shell = app.workspace_layout
                style = ttk.Style(root)
                original_font = style.lookup("Tool.TButton", "font")
                # A slightly wider native font is enough to add a toolbar row.
                # Exercise this on Linux too, rather than relying on Windows CI.
                style.configure("Tool.TButton", font=(shell.family, 10))
                for locale in ("zh", "en"):
                    app.change_ui_language(locale)
                    root.geometry("540x420")
                    root.update()
                    self.assert_log_fits(app, 100, locale)
                    self.assertTrue(shell.compact)
                    self.assertEqual(len(shell.toolbar.buttons), 8)
                    for button in shell.toolbar.buttons:
                        self.assertTrue(button.winfo_viewable())
                self.assertGreater(root.minsize()[1], 420)
                root.geometry("1100x820")
                root.update()
                self.assertFalse(shell.compact)
                self.assertEqual(root.minsize(), (540, 420))
                style.configure("Tool.TButton", font=original_font)
                root.geometry("680x420")
                root.update()
                self.assertTrue(shell.compact)
                self.assertEqual(root.minsize(), (540, 420))
                self.assert_log_fits(app, 100, "en")
                with patch.object(root, "minsize", wraps=root.minsize) as minimum:
                    for _ in range(5):
                        shell.constrain_panes()
                        root.update()
                    self.assertFalse(any(call.args for call in minimum.call_args_list))
        finally:
            for timer in root.tk.call("after", "info"):
                root.tk.call("after", "cancel", timer)
            root.tk.call("tk", "scaling", previous_scaling)
            root.destroy()
            set_language("zh")


if __name__ == '__main__':
    unittest.main()
