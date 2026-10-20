import gc
import json
import queue
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp
from literature_ui import LiteratureControls
import paddleocr_pdf_to_md_gui as application
from ui_i18n import language, set_language, tr


def assert_english_captions(test, widget, language_selector):
    """Check owned UI text; document content and user-entered values stay untouched."""
    if widget is language_selector or ("text" in widget.keys() and widget.cget("text") == "文/A"):
        return  # Keep the native names of both UI languages in this one selector.
    for option in ("text", "values"):
        if option in widget.keys():
            test.assertNotRegex(str(widget.cget(option)), r"[\u4e00-\u9fff]", str(widget))
    if isinstance(widget, application.ttk.Notebook):
        for tab in widget.tabs():
            test.assertNotRegex(widget.tab(tab, "text"), r"[\u4e00-\u9fff]")
    if isinstance(widget, tk.Menu):
        end = widget.index("end")
        for index in range(end + 1 if end is not None else 0):
            if widget.type(index) not in {"separator", "tearoff"}:
                test.assertNotRegex(widget.entrycget(index, "label"), r"[\u4e00-\u9fff]")
    for child in widget.winfo_children():
        assert_english_captions(test, child, language_selector)


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

    def test_post_ocr_translation_uses_model_for_review_and_proofreading_decisions(self):
        for secondary in (False, True):
            with self.subTest(secondary=secondary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "ocr-result.md"
                source.write_text("# Foreign paper\n\nEvidence and conclusions.", encoding="utf-8")
                profiles = {role: lp.ModelProfile("https://example.invalid/v1", "test-key", role)
                            for role in ("translator", "reviewer", "proofreader", "arbiter")}
                controls = object.__new__(LiteratureControls)
                controls.snapshot = {"auto_translate": True, "output": None, "prefix": False,
                    "profiles": profiles, "options": lp.TranslationOptions(secondary_review=secondary,
                        proofreading=True, arbitration="大模型裁决"), "github": None}
                controls.stopped = Mock(return_value=False)
                controls.events = queue.Queue()
                controls.log = Mock()
                controls.maybe_upload = Mock()
                controls.decide = Mock(side_effect=AssertionError("Automatic model decisions must not open a user dialog"))
                responses = ['{"language":"English","is_target_language":false}', "# 文献\n\n证据与结论。"]
                if secondary:
                    responses += ["# 文献\n\n第二版。", '{"has_problem":true}',
                                  '{"choice":"first","has_problem":false,"reason":"第一版准确"}']
                responses += ['{"has_problem":true,"issues":["缺字疑点"]}',
                              '{"decision":"approve","has_problem":false,"reason":"校对误报，译文完整"}']
                with patch.object(lp, "chat", side_effect=responses) as chat:
                    controls.after_ocr(source, root, {"llmReview": {"hasProblem": False}}, source.read_text())
                report = json.loads((root / "ocr-result_TRANSLATED.translation.json").read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "verified")
                self.assertEqual(report["arbiter"], "arbiter")
                decisions = [call for call in chat.call_args_list if call.args[0].model == "arbiter"]
                self.assertEqual(len(decisions), 2 if secondary else 1)
                self.assertEqual(decisions[-1].args[1], lp.PROOF_ARBITRATE_PROMPT)
                self.assertTrue(controls.maybe_upload.call_args.args[2])
                controls.decide.assert_not_called()


class DesktopLayoutTests(unittest.TestCase):
    def setUp(self):
        # An unexpected modal must fail the case, not wait forever in headless CI.
        for name in ("showinfo", "showwarning", "showerror", "askyesno"):
            guard = patch.object(application.messagebox, name,
                side_effect=AssertionError("Unexpected modal dialog: " + name))
            guard.start()
            self.addCleanup(guard.stop)

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
        application.configure_unicode_ui_fonts(cls.root)
        application.configure_design_language(cls.root)
        cls.app = application.PaddleOCRBatchGUI(cls.root)
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.root.tk.call("after", "info"):
            cls.root.tk.call("after", "cancel", timer)
        cls.root.destroy()
        cls.config_patch.stop()
        cls.save_patch.stop()

    def test_language_icon_and_all_tools_are_directly_visible_in_both_languages(self):
        layout = self.app.workspace_layout
        try:
            self.app.change_ui_language("zh")
            for expected in ("en", "zh"):
                layout.language_button.invoke()
                self.assertEqual(language(), expected)
                self.assertEqual(layout.language_button.cget("text"), "文/A")
                for size in ("540x420", "1100x780"):
                    self.root.geometry(size)
                    self.root.update()
                    self.assertEqual(len(layout.toolbar.buttons), 8)
                    for button in layout.toolbar.buttons:
                        self.assertTrue(button.winfo_viewable())
                        self.assertLessEqual(button.winfo_x() + button.winfo_width(), layout.toolbar.winfo_width())
                        self.assertLessEqual(button.winfo_y() + button.winfo_height(), layout.toolbar.winfo_height())
                    self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
            style = application.ttk.Style(self.root)
            self.assertEqual(style.lookup("Paper.TFrame", "background"), style.lookup("TFrame", "background"))
            self.assertEqual(style.lookup("TCheckbutton", "background"), style.lookup("TFrame", "background"))
        finally:
            self.app.change_ui_language("zh")

    def test_chunk_percentage_validates_and_is_in_saved_settings_and_worker_snapshot(self):
        controls = self.app.literature
        before = controls.input_percent.get()
        try:
            for value in ("50", "65", "80"):
                controls.input_percent.set(value)
                self.assertEqual(controls.config_data()["input_percent"], int(value))
                self.assertEqual(controls.make_snapshot(False)["options"].input_percent, int(value))
            for value in ("49", "81", "50.0", "bad"):
                controls.input_percent.set(value)
                with self.assertRaises(ValueError):
                    controls.config_data()
                with self.assertRaises(ValueError):
                    controls.make_snapshot(False)
        finally:
            controls.input_percent.set(before)

    def test_model_limits_follow_endpoint_model_and_manual_override_round_trips(self):
        from literature_ui import ModelControls
        from model_budget import ModelCatalog
        model = ModelControls(self.root, "model", {"model": "large", "api_key": "secret"},
                              self.app.literature.events, Mock(), Mock())
        restored = None
        try:
            catalog = ModelCatalog([{"id": "large", "context_length": 128000, "max_output_tokens": 16000},
                                    {"id": "small", "max_input_tokens": 32000}])
            self.app.literature.events.put(("profile_result", (model, False, catalog, None, model.profile(), model.request_generation)))
            self.app.literature.poll()
            self.assertEqual(model.profile().context_limit, 128000)
            self.assertEqual(model.limit_value.get(), "128000")
            model.manual_limit.set(True)
            model.refresh_limits()
            model.limit_value.set("64000")
            self.assertEqual(model.profile().input_limit, 64000)
            restored = ModelControls(self.root, "restored", model.config_data(), queue.Queue(), Mock(), Mock())
            self.assertEqual(restored.profile(), model.profile())
            model.model.set("small")
            self.assertFalse(model.manual_limit.get())
            self.assertEqual(model.profile().input_limit, 32000)
            model.url.set("https://other.invalid/v1")
            self.assertEqual(model.profile().input_limit, 0)
            self.assertEqual(model.limit_value.get(), "1000000")
            model.manual_limit.set(True)
            model.limit_value.set("-1")
            with self.assertRaises(ValueError):
                model.config_data()
        finally:
            model.box.destroy()
            if restored:
                restored.box.destroy()

    def test_late_model_metadata_is_ignored_after_changing_endpoint(self):
        from literature_ui import ModelControls
        from model_budget import ModelCatalog
        model = ModelControls(self.root, "model", {"model": "large"}, self.app.literature.events, Mock(), Mock())
        try:
            requested = model.profile()
            generation = model.request_generation
            model.url.set("https://other.invalid/v1")
            result = ModelCatalog([{"id": "large", "context_length": 128000}])
            self.app.literature.events.put(("profile_result", (model, False, result, None, requested, generation)))
            self.app.literature.poll()
            self.assertFalse(model.catalog_limits)
        finally:
            model.box.destroy()

    def test_model_requests_are_single_flight_and_stale_credentials_cannot_publish_results(self):
        from literature_ui import ModelControls
        entered, release = threading.Event(), threading.Event()
        def fetch(*args, **kwargs):
            entered.set()
            release.wait(2)
            return ["stale-model"]
        fetch = Mock(side_effect=fetch)
        model = ModelControls(self.root, "model", {"model": "current", "api_key": "old-key"},
                              self.app.literature.events, fetch, Mock(), app=self.app)
        try:
            model.request(False)
            self.assertTrue(entered.wait(1))
            for _ in range(10):
                model.request(False)
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(all(str(button.cget("state")) == "disabled" for button in model.request_buttons))
            stop = fetch.call_args.kwargs["stop"]
            model.key.set("replacement-key")
            model.key.set("old-key")
            self.assertTrue(stop())
            release.set()
            model.request_thread.join(2)
            self.assertFalse(model.request_thread.is_alive())
            self.app.literature.poll()
            self.assertEqual(model.model.get(), "current")
            self.assertEqual(model.combo.cget("values"), "")
            self.assertIsNone(model.active_request)
            self.assertTrue(all(str(button.cget("state")) == "normal" for button in model.request_buttons))
        finally:
            release.set()
            if model.request_thread:
                model.request_thread.join(2)
            model.box.destroy()

    def test_destroyed_model_controls_cancel_requests_without_opening_a_late_dialog(self):
        from literature_ui import ModelControls
        entered, release = threading.Event(), threading.Event()
        def fetch(*args, **kwargs):
            entered.set()
            release.wait(2)
            raise RuntimeError("late network failure")
        fetch = Mock(side_effect=fetch)
        model = ModelControls(self.root, "model", {"api_key": "key"}, self.app.literature.events, fetch, Mock())
        try:
            model.request(False)
            self.assertTrue(entered.wait(1))
            model.box.destroy()
            self.assertTrue(fetch.call_args.kwargs["stop"]())
            release.set()
            model.request_thread.join(2)
            self.app.literature.poll()  # Unexpected dialogs are a test failure.
            self.assertTrue(model.closed)
            self.assertIsNone(model.active_request)
        finally:
            release.set()
            if model.request_thread:
                model.request_thread.join(2)
            if model.box.winfo_exists():
                model.box.destroy()

    def test_translation_folder_scan_can_be_stopped_before_file_enumeration_finishes(self):
        controls = self.app.literature
        previous = controls.input.get(), self.app.stop_requested, controls.cancel_event.is_set()
        entered = threading.Event()
        def scan(*args, stop, **kwargs):
            entered.set()
            deadline = time.monotonic() + 2
            while not stop() and time.monotonic() < deadline:
                time.sleep(.01)
            if stop():
                raise lp.ProcessingCancelled("cancelled scan")
            raise AssertionError("Stop did not reach the file enumeration")
        try:
            with tempfile.TemporaryDirectory() as directory, patch("literature_ui.find_markdown_files", side_effect=scan):
                controls.input.set(directory)
                controls.scan()
                self.assertTrue(entered.wait(1))
                self.assertTrue(controls.busy())
                self.assertEqual(str(self.app.workspace_layout.translation_stop.cget("state")), "normal")
                controls.stop()
                deadline = time.monotonic() + 3
                while controls.scanning and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertFalse(controls.scanning)
                self.assertIn("已停止", controls.status.get())
                self.assertEqual(str(controls.start_button.cget("state")), "normal")
        finally:
            controls.input.set(previous[0])
            self.app.stop_requested = previous[1]
            controls.cancel_event.set() if previous[2] else controls.cancel_event.clear()

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
                self.app.notebook.select(0)
                self.root.update()
                button = self.app.start_btn
                self.assertTrue(button.winfo_viewable())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), self.root.winfo_rooty() + height)

    def test_forms_reflow_after_wide_and_narrow_resizes(self):
        for width, wide in ((1100, True), (640, False), (1100, True), (540, False)):
            self.root.geometry(f"{width}x780")
            self.root.update()
            self.assertTrue(all(value is wide for value in self.app.workspace_layout.form_columns.values()))

    def test_field_captions_and_long_values_reflow_without_clipping_or_hiding_logs(self):
        controls = self.app.literature
        original_source = controls.source.get()
        original_model = controls.profiles["translator"].model.get()
        try:
            for locale in ("zh", "en"):
                self.app.change_ui_language(locale)
                for width, height in ((1100, 780), (540, 420)):
                    self.root.geometry(f"{width}x{height}")
                    self.app.notebook.select(1)
                    self.root.update()
                    form = controls.language_form
                    font = application.tkfont.nametofont("TkDefaultFont", root=self.root)
                    for label, field in form.rows:
                        self.assertGreaterEqual(label.winfo_width(), font.measure(label.cget("text")))
                        self.assertLessEqual(field.winfo_rootx() + field.winfo_width(), self.root.winfo_rootx() + width)
                    controls.source.set("An unusually long source language designation that needs the complete available row")
                    self.root.update()
                    self.assertTrue(form.stacked)
                    label, field = form.rows[0]
                    self.assertEqual(label.grid_info()["column"], field.grid_info()["column"])
                    self.assertGreater(int(field.grid_info()["row"]), int(label.grid_info()["row"]))
                    self.assertGreaterEqual(field.winfo_width(), form.winfo_width() - 10)
                    self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
                    controls.source.set(original_source)
            controls.profiles["translator"].model.set("research-model-with-a-long-identifier-" * 5)
            self.app.workspace_layout.show_settings(1)
            self.root.update()
            model = controls.profiles["translator"]
            self.assertTrue(model.form.stacked)
            self.assertGreaterEqual(model.combo.winfo_width(), model.form.winfo_width() - 10)
        finally:
            controls.source.set(original_source)
            controls.profiles["translator"].model.set(original_model)
            self.app.workspace_layout.settings.withdraw()
            self.app.change_ui_language("zh")

    def test_original_icon_stays_visible_when_switching_window_sizes(self):
        shell = self.app.workspace_layout
        for width, height, icon_size in ((1100, 780, 48), (640, 480, 32), (540, 420, 32), (1100, 780, 48)):
            with self.subTest(size=(width, height)):
                self.root.geometry(f"{width}x{height}")
                self.root.update()
                gc.collect()
                image = shell.mark.cget("image")
                self.assertEqual(str(image), str(shell.brand_icons[icon_size]))
                self.assertEqual(self.root.tk.call("image", "type", str(image)), "photo")
                self.assertGreater(self.root.tk.call("image", "width", str(image)), 0)
                self.assertLessEqual(self.root.tk.call("image", "width", str(image)), icon_size)
                self.assertTrue(shell.mark.winfo_viewable())
                self.assertEqual(shell.mark.cget("text"), "")
                self.assertLessEqual(shell.mark.winfo_rooty() + shell.mark.winfo_height(), self.root.winfo_rooty() + height)

    def test_same_folder_locks_and_tracks_both_typed_and_selected_source_paths(self):
        controls = self.app.literature
        previous = controls.config_data()
        try:
            controls.same_folder.set(True)
            controls.input.set("/tmp/原文")
            self.assertEqual(controls.output.get(), controls.input.get())
            self.assertEqual(str(controls.output_entry.cget("state")), "disabled")
            self.assertEqual(str(controls.output_button.cget("state")), "normal")
            controls.output.set("/tmp/forbidden")
            self.assertEqual(controls.output.get(), controls.input.get())
            with patch("literature_ui.filedialog.askdirectory", return_value="/tmp/new-source"):
                controls.choose_dir(controls.input)
            self.assertEqual(controls.output.get(), "/tmp/new-source")
            controls.same_folder.set(False)
            self.assertEqual(str(controls.output_entry.cget("state")), "normal")
            controls.output.set("/tmp/independent")
            controls.input.set("/tmp/another-source")
            self.assertEqual(controls.output.get(), "/tmp/independent")
            controls.same_folder.set(True)
            self.assertEqual(controls.output.get(), controls.input.get())
        finally:
            controls.same_folder.set(False)
            controls.input.set(previous["input"])
            controls.output.set(previous["output"])
            controls.same_folder.set(previous["same_folder"])

    def test_output_picker_requires_override_and_keeps_lock_on_either_cancel(self):
        controls = self.app.literature
        previous = controls.config_data()
        try:
            for locale in ("zh", "en"):
                self.app.change_ui_language(locale)
                controls.input.set("/tmp/source")
                controls.same_folder.set(True)
                for confirmed, selection in ((False, "/tmp/new"), (True, ""), (True, "/tmp/new")):
                    controls.same_folder.set(True)
                    with patch("literature_ui.messagebox.askyesno", return_value=confirmed) as confirm, \
                            patch("literature_ui.filedialog.askdirectory", return_value=selection) as picker:
                        controls.output_button.invoke()
                    confirm.assert_called_once()
                    self.assertEqual(confirm.call_args.args[1], tr("您已选择“译文保存在原文文件夹”，是否需要强制覆盖设置？"))
                    self.assertEqual(picker.call_count, int(confirmed))
                    overridden = confirmed and bool(selection)
                    self.assertEqual(controls.same_folder.get(), not overridden)
                    self.assertEqual(controls.output.get(), selection if overridden else controls.input.get())
                    self.assertEqual(str(controls.output_entry.cget("state")), "normal" if overridden else "disabled")
        finally:
            self.app.change_ui_language("zh")
            controls.same_folder.set(False)
            controls.input.set(previous["input"])
            controls.output.set(previous["output"])
            controls.same_folder.set(previous["same_folder"])

    def test_language_switch_preserves_paths_credentials_options_and_active_job(self):
        controls = self.app.literature
        before = controls.config_data()
        active = self.app.worker_thread
        try:
            controls.input.set("/tmp/中文路径")
            translator = controls.profiles["translator"]
            translator.model.set("模型-ID")
            translator.key.set("session-key")
            translator.url.set("https://example.invalid/v1")
            controls.source.set("英语 (en)")
            controls.target.set("简体中文 (ch)")
            controls.prefix.set("前缀 TRANSLATED_")
            controls.arbitration.set("大模型裁决")
            controls.secondary.set(False)
            controls.proofreading.set(False)
            controls.upload.set(False)
            self.app.worker_thread = Mock(is_alive=Mock(return_value=True))
            saved = controls.config_data()
            for locale in ("en", "zh", "en", "zh"):
                self.app.change_ui_language(locale)
                self.root.update()
                self.assertEqual(controls.config_data(), saved)
                self.assertTrue(self.app.worker_thread.is_alive())
                self.assertEqual(self.app.config.ui_language, locale)
                self.assertEqual(controls.make_snapshot()["options"].source, "英语 (en)")
                self.assertEqual(controls.make_snapshot()["options"].target, "简体中文 (ch)")
                self.assertTrue(controls.make_snapshot()["prefix"])
                self.assertEqual(translator.model.get(), "模型-ID")
        finally:
            self.app.worker_thread = active
            controls.same_folder.set(False)
            for key in ("input", "output", "source", "target", "arbitration"):
                getattr(controls, key).set(before[key])
            controls.prefix.set(before["filename_position"])
            for key in ("same_folder", "secondary", "proofreading", "upload"):
                getattr(controls, key).set(before[key])
            for role, profile in controls.profiles.items():
                profile.url.set(before[role]["base_url"])
                profile.key.set(before[role]["api_key"])
                profile.model.set(before[role]["model"])
            self.app.change_ui_language("zh")

    def test_english_captions_logs_and_actions_survive_navigation_and_small_resizes(self):
        try:
            self.app.change_ui_language("en")
            self.assertIn("Welcome to Literature Workspace", self.app.log_text.get("1.0", "end"))
            self.assertIn("Literature Workspace", self.root.title())
            for width, height in ((1100, 780), (640, 480), (540, 420), (1100, 780)):
                self.root.geometry(f"{width}x{height}")
                for page in (0, 1):
                    self.app.notebook.select(page)
                    self.root.update()
                    assert_english_captions(self, self.root, self.app.workspace_layout.language_selector)
                    self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
                    action = self.app.literature.start_button if page else self.app.start_btn
                    self.assertTrue(action.winfo_viewable())
                    self.assertLessEqual(action.winfo_rootx() + action.winfo_width(), self.root.winfo_rootx() + width)
        finally:
            self.app.change_ui_language("zh")

    def test_settings_keep_models_off_the_task_page_and_save_on_return(self):
        shell = self.app.workspace_layout
        shell.show_settings(1)
        self.root.update()
        self.assertTrue(shell.settings.winfo_viewable())
        self.assertEqual(shell.settings_tabs.index(shell.settings_tabs.select()), 1)
        profile = self.app.literature.profiles["translator"]
        previous = profile.model.get()
        profile.model.set("saved-model-id")
        shell.close_settings()
        self.root.update()
        self.assertFalse(shell.settings.winfo_viewable())
        self.assertEqual(self.app.config.literature["translator"]["model"], "saved-model-id")
        profile.model.set(previous)

    def test_running_page_and_split_progress_do_not_push_logs_out_of_small_window(self):
        self.root.geometry("540x420")
        previous_worker = self.app.worker_thread
        try:
            self.app.worker_thread = Mock(is_alive=Mock(return_value=True))
            self.app.page_progress_text_var.set("当前文件页数进度：128/900 页，14.22%")
            self.app.page_progress_var.set(14.22)
            self.app.split_progress_text_var.set("大文件分段进度：当前文件已处理 1/12 段")
            self.app.split_progress_label.grid()
            self.root.update()
            self.assertGreaterEqual(self.app.log_text.winfo_height(), 40)
            self.assertLessEqual(self.app.log_text.winfo_rooty() + self.app.log_text.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
        finally:
            self.app.worker_thread = previous_worker
            self.app.page_progress_var.set(0)
            self.app.split_progress_label.grid_remove()

    def test_keyboard_navigation_and_long_values_keep_actions_reachable(self):
        self.root.geometry("640x480")
        self.root.update()
        self.root.focus_force()
        self.root.event_generate("<Control-Key-2>")
        self.root.update()
        self.assertEqual(self.app.notebook.index(self.app.notebook.select()), 1)
        long_path = "/home/researcher/Documents/国际关系研究/国际制度演变与区域合作机制/英文原始文献与补充材料/"
        controls = self.app.literature
        controls.input.set(long_path)
        controls.profiles["translator"].model.set("moonshot-v1-128k-research-literature-translation")
        self.app.status_var.set("正在处理：Regional Institutions and the Transformation of International Order — Supplementary Appendix.md")
        self.root.update()
        self.assertTrue(controls.start_button.winfo_viewable())
        self.assertLessEqual(controls.start_button.winfo_rootx() + controls.start_button.winfo_width(),
                             self.root.winfo_rootx() + self.root.winfo_width())
        self.app.workspace_layout.status_tip.show()
        self.assertTrue(self.app.workspace_layout.status_tip.window.winfo_exists())
        self.app.workspace_layout.status_tip.close()
        controls.input.set("")
        controls.profiles["translator"].model.set("")
        self.root.event_generate("<Control-Key-1>")
        self.root.update()
        self.assertEqual(self.app.notebook.index(self.app.notebook.select()), 0)

    def test_three_entries_and_default_translation_settings(self):
        tabs = self.app.notebook.tabs()
        self.assertEqual([self.app.notebook.tab(tab, "text") for tab in tabs],
                         ["PDF OCR 转 MD功能", "外文文献翻译功能", "GitHub 文档上传"])
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

    def test_missing_github_credentials_point_to_the_setup_wizard(self):
        controls = self.app.literature
        upload, token = controls.upload.get(), controls.github_token.get()
        try:
            controls.upload.set(True)
            controls.github_token.set("")
            for locale, message in (("zh", "向导"), ("en", "wizard")):
                self.app.change_ui_language(locale)
                with self.assertRaisesRegex(ValueError, message):
                    controls.make_snapshot(False)
        finally:
            controls.upload.set(upload)
            controls.github_token.set(token)
            self.app.change_ui_language("zh")

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
            self.app.background_jobs.clear()
            self.app.worker_thread = None
            controls.auto_translate.set(False)
            self.app.start_btn.configure(state="normal")
            self.app.stop_btn.configure(state="disabled")
            self.app.manual_query_btn.configure(state="disabled")

    def test_ocr_and_translation_entries_share_quality_controls_and_validate_proofreading_arbiter(self):
        controls, layout = self.app.literature, self.app.workspace_layout
        before = {name: getattr(controls, name).get() for name in ("auto_translate", "secondary", "proofreading", "arbitration")}
        previous_profiles = {role: (model.key.get(), model.model.get()) for role, model in controls.profiles.items()}
        try:
            controls.auto_translate.set(True)
            controls.secondary.set(False)
            controls.proofreading.set(False)
            self.assertTrue(layout.ocr_quality_group.grid_info())
            self.assertEqual(str(layout.ocr_quality_panel.arbitration_combo.cget("state")), "disabled")
            layout.ocr_quality_panel.proofreading_button.invoke()
            self.assertTrue(controls.proofreading.get())
            self.assertEqual(str(controls.quality_panel.arbitration_combo.cget("state")), "readonly")
            controls.arbitration.set("大模型裁决")
            for role, model in controls.profiles.items():
                model.key.set("test-key")
                model.model.set(role)
            snapshot = controls.make_snapshot()
            self.assertTrue(snapshot["options"].proofreading)
            self.assertEqual(snapshot["options"].arbitration, "大模型裁决")
            self.assertEqual(snapshot["profiles"]["arbiter"].model, "arbiter")
            self.assertEqual(layout.ocr_quality_panel.arbitration_combo.cget("textvariable"),
                             controls.quality_panel.arbitration_combo.cget("textvariable"))
            controls.profiles["arbiter"].key.set("")
            with self.assertRaises(ValueError):
                controls.make_snapshot()
            controls.auto_translate.set(False)
            self.assertFalse(layout.ocr_quality_group.grid_info())
        finally:
            for name, value in before.items():
                getattr(controls, name).set(value)
            for role, (key, model) in previous_profiles.items():
                controls.profiles[role].key.set(key)
                controls.profiles[role].model.set(model)

    def test_user_can_inspect_both_versions_and_accept_second(self):
        controls = self.app.literature
        result = queue.Queue()
        controls.decision_dialog({"filename": "paper.md", "chunk": 1, "source": "original",
                                 "first": "first", "second": "second", "comparison": {"has_problem": True}}, result)
        self.root.update()
        dialog = next(widget for widget in self.root.winfo_children()
                      if isinstance(widget, tk.Toplevel) and widget.winfo_viewable())
        notebook = next(widget for widget in dialog.winfo_children() if isinstance(widget, application.ttk.Notebook))
        self.assertEqual(len(notebook.tabs()), 4)
        def buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, application.ttk.Button):
                    yield child
                yield from buttons(child)
        accept = next(button for button in buttons(dialog) if button.cget("text") == "保留第二稿")
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


class EnglishStartupTests(unittest.TestCase):
    def test_saved_english_preference_applies_before_building_the_interface(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"GUI tests need a display: {exc}")
        try:
            with patch.object(application, "load_config", return_value=application.AppConfig(ui_language="en")), \
                    patch.object(application, "save_config"):
                application.configure_unicode_ui_fonts(root)
                application.configure_design_language(root)
                app = application.PaddleOCRBatchGUI(root)
                root.update()
                self.assertEqual(language(), "en")
                assert_english_captions(self, root, app.workspace_layout.language_selector)
                self.assertEqual(app.status_var.get(), "Ready.")
                self.assertEqual(app.literature.target.get(), "简体中文 (ch)")
                app.literature.input.set("/tmp/原文")
                self.assertEqual(app.literature.output.get(), "/tmp/原文")
                self.assertEqual(app.literature.source.get(), "自动检测")
                profile = app.literature.profiles["translator"]
                profile.provider.set("Doubao / Volcengine Ark")
                profile.preset()
                self.assertEqual(profile.url.get(), lp.PROVIDERS["Doubao / 火山方舟"])
                for selection, locale in (("中文", "zh"), ("English", "en")):
                    app.ui_language_var.set(selection)
                    app.workspace_layout.language_selector.event_generate("<<ComboboxSelected>>")
                    root.update()
                    self.assertEqual(language(), locale)
                    self.assertEqual(app.config.ui_language, locale)
        finally:
            for timer in root.tk.call("after", "info"):
                root.tk.call("after", "cancel", timer)
            root.destroy()
            set_language("zh")


if __name__ == "__main__":
    unittest.main()
