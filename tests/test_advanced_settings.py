import gc
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from advanced_settings import AdvancedPromptSettings, PROMPT_LABELS, read_license
from prompt_templates import MAX_PROMPT_CHARS, PROMPTS
import paddleocr_pdf_to_md_gui as application
from ui_i18n import set_language, widget_text
from test_literature_ui import assert_english_captions


class LicenseResourceTests(unittest.TestCase):
    def test_legacy_source_update_can_read_txt_license_without_changing_original(self):
        original = Path(__file__).resolve().parents[1].joinpath("License").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "License.txt").write_text(original, encoding="utf-8")
            self.assertEqual(read_license(folder), original)
            (folder / "License").write_text("preferred original", encoding="utf-8")
            self.assertEqual(read_license(folder), "preferred original")
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(FileNotFoundError):
            read_license(directory)


class AdvancedSettingsTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        set_language("zh")
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        self.addCleanup(self.cleanup)
        self.load = patch.object(application, "load_config", return_value=application.AppConfig())
        self.save = patch.object(application, "save_config")
        self.load.start()
        self.save.start()
        self.addCleanup(self.load.stop)
        self.addCleanup(self.save.stop)
        application.configure_unicode_ui_fonts(self.root)
        application.configure_design_language(self.root)
        self.app = application.PaddleOCRBatchGUI(self.root)
        self.shell = self.app.workspace_layout
        self.controls = self.app.literature
        self.panel = self.controls.advanced
        self.root.update()

    def cleanup(self):
        for token in self.root.tk.call("after", "info"):
            self.root.after_cancel(token)
        self.root.destroy()
        set_language("zh")

    def select(self, role):
        self.panel.role.set(PROMPT_LABELS[role])
        self.panel.choose_role()

    def edit(self, text):
        self.panel.editor.delete("1.0", "end")
        self.panel.editor.insert("1.0", text)

    def test_all_task_roles_save_restore_and_reuse_custom_prompts(self):
        self.assertEqual(set(PROMPT_LABELS), set(PROMPTS))
        self.assertEqual(self.controls.config_data()["prompts"], {})
        self.select("translation")
        custom = "Translate faithfully; preserve every footnote and table cell."
        self.edit(custom)
        self.select("ocr_review")
        self.edit("Check OCR omissions carefully.")
        self.app.save_current_config()
        saved = self.app.config.literature["prompts"]
        self.assertEqual(saved, {"translation": custom, "ocr_review": "Check OCR omissions carefully."})
        from literature_ui import scrollable_page
        notebook = application.ttk.Notebook(self.root)
        try:
            page = scrollable_page(notebook, "restored")
            restored = AdvancedPromptSettings(page, saved)
            self.assertEqual(restored.prompt_snapshot()["translation"], custom)
            self.assertEqual(restored.prompt_snapshot()["ocr_review"], "Check OCR omissions carefully.")
        finally:
            notebook.destroy()
        self.panel.restore_current()
        self.assertEqual(self.panel.editor.get("1.0", "end-1c"), PROMPTS["ocr_review"])
        self.assertEqual(self.controls.config_data()["prompts"], {"translation": custom})
        with patch("advanced_settings.messagebox.askyesno", return_value=False):
            self.panel.restore_all()
        self.assertEqual(self.controls.config_data()["prompts"], {"translation": custom})
        with patch("advanced_settings.messagebox.askyesno", return_value=True):
            self.panel.restore_all()
        self.assertEqual(self.controls.config_data()["prompts"], {})

    def test_running_snapshot_is_independent_of_later_edits_and_invalid_values_cannot_save(self):
        self.select("translation")
        self.edit("Use the first instructions.")
        running = self.controls.make_snapshot(False)
        self.edit("Use the next instructions.")
        following = self.controls.make_snapshot(False)
        self.assertEqual(running["prompts"]["translation"], "Use the first instructions.")
        self.assertEqual(following["prompts"]["translation"], "Use the next instructions.")
        self.edit("x" * (MAX_PROMPT_CHARS + 1))
        with self.assertRaises(ValueError):
            self.controls.config_data()
        self.edit("  \n")
        self.assertEqual(self.controls.prompt_snapshot()["translation"], PROMPTS["translation"])

    def test_legal_text_is_selectable_and_full_copy_preserves_the_bundled_license(self):
        legal = self.shell.legal_notice
        original = Path(__file__).resolve().parents[1].joinpath("License").read_text(encoding="utf-8")
        self.assertEqual(legal.text.get("1.0", "end-1c"), original)
        self.assertEqual(str(legal.text.cget("state")), "disabled")
        legal.text.tag_add("sel", "1.0", "1.end")
        self.assertEqual(widget_text(legal.text, selected=True), original.splitlines()[0])
        legal.copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(), original)
        self.app.change_ui_language("en")
        self.assertEqual(legal.text.get("1.0", "end-1c"), original)
        self.assertEqual(legal.copy_button.cget("text"), "Copy full license")

    def test_new_settings_pages_are_bilingual_and_editor_grows_with_window(self):
        heights = []
        for locale in ("zh", "en"):
            self.app.change_ui_language(locale)
            for size in ("440x340", "1000x720"):
                self.shell.show_settings(5)
                self.shell.settings.geometry(size)
                self.root.update()
                self.assertGreaterEqual(self.panel.editor.winfo_height(), 100)
                self.assertLessEqual(self.panel.editor.winfo_width(), self.panel.area.canvas.winfo_width())
                self.assertGreaterEqual(self.panel.editor.winfo_rooty(), self.panel.area.canvas.winfo_rooty())
                self.assertLessEqual(self.panel.editor.winfo_rooty() + self.panel.editor.winfo_height(),
                                     self.panel.area.canvas.winfo_rooty() + self.panel.area.canvas.winfo_height())
                heights.append(self.panel.editor.winfo_height())
                self.shell.settings_tabs.select(6)
                self.root.update()
                self.assertLessEqual(self.shell.legal_notice.text.winfo_width(),
                                     self.shell.legal_notice.page.master.winfo_width())
                self.assertLessEqual(self.shell.legal_notice.text.winfo_rooty() + self.shell.legal_notice.text.winfo_height(),
                                     self.shell.legal_notice.page.master.winfo_rooty() + self.shell.legal_notice.page.master.winfo_height())
            if locale == "en":
                assert_english_captions(self, self.shell.settings, self.shell.language_selector)
                self.assertEqual(self.shell.settings_tabs.tab(5, "text"), "Advanced")
                self.assertEqual(self.shell.settings_tabs.tab(6, "text"), "Legal notices")
        self.assertGreater(heights[1], heights[0])
        self.assertGreater(heights[3], heights[2])


if __name__ == "__main__":
    unittest.main()
