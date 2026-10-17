import json
import queue
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp
from literature_ui import LiteratureControls
import paddleocr_pdf_to_md_gui as application


class OCRIntegrationTests(unittest.TestCase):
    def controls(self, auto_translate=False):
        controls = object.__new__(LiteratureControls)
        controls.snapshot = {"auto_translate": auto_translate}
        controls.stopped = Mock(return_value=False)
        controls.maybe_upload = Mock()
        controls.process = Mock()
        controls.log = Mock()
        return controls

    def test_ocr_translation_option_controls_the_followup(self):
        path = Path("result.md")
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                controls = self.controls(enabled)
                controls.after_ocr(path, path.parent, {})
                self.assertEqual(controls.process.call_count, int(enabled))

    def test_ocr_warning_prevents_translated_output_upload_approval(self):
        controls = self.controls(True)
        controls.after_ocr(Path("result.md"), Path("."), {"parts": [{"rawResult": {"qualityWarning": "bad OCR"}}]})
        self.assertFalse(controls.process.call_args.kwargs["upstream_ok"])
        self.assertFalse(controls.maybe_upload.call_args.args[2])

    def test_changed_ocr_text_cannot_reuse_earlier_approval(self):
        controls = self.controls(True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.md"
            path.write_text("changed", encoding="utf-8")
            controls.after_ocr(path, path.parent, {"llmReview": {"hasProblem": False}}, "reviewed text")
        controls.maybe_upload.assert_not_called()
        controls.process.assert_not_called()

    def test_failed_upload_keeps_translation_and_reports_failure(self):
        controls = self.controls()
        controls.snapshot["github"] = lp.GitHubOptions("owner/repo", "key")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.md"
            path.write_bytes(b"reviewed")
            with patch("literature_ui.upload_verified_file", side_effect=RuntimeError("HTTP 403")):
                LiteratureControls.maybe_upload(controls, path, path.parent, True, controls.snapshot)
            self.assertTrue(path.exists())
        self.assertIn("未上传", controls.log.call_args.args[0])

    def test_stopping_manual_decision_does_not_leave_worker_waiting(self):
        controls = self.controls()
        controls.events = queue.Queue()
        controls.stopped = Mock(return_value=True)
        with self.assertRaises(lp.ProcessingCancelled):
            LiteratureControls.decide(controls, {"chunk": 1})


class DesktopLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"GUI tests need a display: {exc}")
        cls.config_patch = patch.object(application, "load_config", return_value=application.AppConfig(token=""))
        cls.config_patch.start()
        cls.save_patch = patch.object(application, "save_config")
        cls.save_patch.start()
        application.configure_design_language(cls.root)
        cls.app = application.PaddleOCRBatchGUI(cls.root)
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.config_patch.stop()
        cls.save_patch.stop()

    def test_logs_remain_visible_at_small_window_sizes(self):
        for width, height in ((1100, 780), (640, 480), (540, 420)):
            with self.subTest(size=(width, height)):
                self.root.geometry(f"{width}x{height}")
                self.root.update()
                log = self.app.log_text
                self.assertTrue(log.winfo_ismapped())
                self.assertGreaterEqual(log.winfo_height(), 40)
                self.assertLessEqual(log.winfo_rooty() + log.winfo_height(), self.root.winfo_rooty() + height)
                self.assertLessEqual(log.winfo_rootx() + log.winfo_width(), self.root.winfo_rootx() + width)

    def test_both_entries_and_default_translation_settings(self):
        tabs = self.app.notebook.tabs()
        self.assertEqual([self.app.notebook.tab(tab, "text") for tab in tabs],
                         ["PDF OCR 转 MD功能", "外文文献翻译功能"])
        self.app.notebook.select(1)
        self.root.update()
        self.assertIn("文献处理软件", self.root.title())
        data = self.app.literature.config_data()
        self.assertEqual(data["target"], "简体中文 (ch)")
        self.assertFalse(data["auto_translate"])
        self.assertFalse(data["upload"])

    def test_github_token_is_not_persisted(self):
        controls = self.app.literature
        controls.github_token.set("session-only-token")
        self.app.save_current_config()
        self.assertNotIn("session-only-token", repr(self.app.config))
        controls.github_token.set("")

    def test_model_presets_and_editable_model_selection(self):
        model = self.app.literature.profiles["translator"]
        model.key.set("previous-provider-key")
        model.provider.set("Kimi / Moonshot")
        model.preset()
        self.assertEqual(model.url.get(), lp.PROVIDERS["Kimi / Moonshot"])
        self.assertEqual(model.key.get(), "")
        self.assertEqual(str(model.combo.cget("state")), "normal")

    def test_stop_then_start_resets_cancellation_state(self):
        controls = self.app.literature
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.md"
            source.write_text("foreign paper")
            controls.input.set(directory)
            controls.same_folder.set(True)
            controls.profiles["translator"].key.set("test-key")
            controls.profiles["translator"].model.set("test-model")
            controls.cancel_event.set()
            self.app.stop_requested = True
            with patch("literature_ui.threading.Thread") as thread:
                thread.return_value.is_alive.return_value = False
                controls.start()
            self.assertFalse(controls.cancel_event.is_set())
            self.assertFalse(self.app.stop_requested)
            thread.return_value.start.assert_called_once()
            controls.thread = None
            controls.start_button.configure(state="normal")
            self.app.start_btn.configure(state="normal")

    def test_ocr_start_captures_auto_translation_settings(self):
        controls = self.app.literature
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.pdf").write_bytes(b"pdf")
            self.app.input_var.set(directory)
            self.app.output_var.set(str(root / "ocr"))
            self.app.config.token = "ocr-test-token"
            controls.auto_translate.set(True)
            controls.same_folder.set(True)
            controls.profiles["translator"].key.set("test-key")
            controls.profiles["translator"].model.set("translation-model")
            controls.snapshot = None
            with patch.object(application.messagebox, "askyesno", return_value=True), \
                    patch.object(application.threading, "Thread") as thread:
                thread.return_value.is_alive.return_value = False
                self.app.start_batch()
            self.assertTrue(controls.snapshot["auto_translate"])
            self.assertEqual(controls.snapshot["profiles"]["translator"].model, "translation-model")
            thread.return_value.start.assert_called_once()
            self.app.worker_thread = None
            controls.auto_translate.set(False)
            self.app.start_btn.configure(state="normal")
            self.app.stop_btn.configure(state="disabled")
            self.app.manual_query_btn.configure(state="disabled")

    def test_user_can_inspect_both_versions_and_accept_second(self):
        controls = self.app.literature
        result = queue.Queue()
        controls.decision_dialog({"filename": "paper.md", "chunk": 1, "source": "original",
                                 "first": "first", "second": "second", "comparison": {"has_problem": True}}, result)
        self.root.update()
        dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel))
        notebook = next(widget for widget in dialog.winfo_children() if isinstance(widget, application.ttk.Notebook))
        self.assertEqual(len(notebook.tabs()), 4)
        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, application.ttk.Button):
                    yield child
                yield from buttons(child)
        accept = next(button for button in buttons(dialog) if button.cget("text") == "接受二次译文")
        accept.invoke()
        self.assertEqual(result.get_nowait(), "second")

    def test_translation_entry_runs_worker_checks_and_uploads_result(self):
        controls = self.app.literature
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.md").write_text("# Foreign paper\n\nSome evidence.", encoding="utf-8")
            controls.input.set(directory)
            controls.same_folder.set(True)
            controls.secondary.set(False)
            controls.proofreading.set(True)
            controls.upload.set(True)
            controls.repository.set("owner/repo")
            controls.github_token.set("session-token")
            for key in ("translator", "proofreader"):
                controls.profiles[key].url.set("https://example.invalid/v1")
                controls.profiles[key].key.set("test-key")
                controls.profiles[key].model.set(key)
            contents = ['{"language":"English","is_target_language":false}', "# 外文文献\n\n相关证据。", '{"has_problem":false}']
            responses = []
            for content in contents:
                response = Mock(ok=True)
                response.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
                responses.append(response)
            with patch.object(lp.requests, "post", side_effect=responses) as post, \
                    patch.object(lp.requests, "get", return_value=Mock(status_code=404)), \
                    patch.object(lp.requests, "put", return_value=Mock(status_code=201)) as put, \
                    patch("literature_ui.messagebox.showinfo"):
                controls.start()
                deadline = time.monotonic() + 3
                while (controls.thread.is_alive() or not controls.events.empty()) and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(0.01)
                self.assertFalse(controls.thread.is_alive())
                self.assertTrue(controls.events.empty())
                self.assertEqual(post.call_count, 3)
                put.assert_called_once()
            report = json.loads((root / "paper_TRANSLATED.translation.json").read_text(encoding="utf-8"))
            self.assertTrue(report["verified"])
            self.assertEqual((root / "paper_TRANSLATED.md").read_text(encoding="utf-8"), contents[1] + "\n")
            self.assertIn("核验通过 1", controls.status.get())
            controls.upload.set(False)
            controls.proofreading.set(False)
            controls.github_token.set("")


if __name__ == "__main__":
    unittest.main()
