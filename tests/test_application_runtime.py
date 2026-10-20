"""Regression checks for bounded OCR retry and lossless settings writes."""
import json
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import paddleocr_pdf_to_md_gui as application
from task_runtime import TaskCancelled


class ApplicationRuntimeTests(unittest.TestCase):
    def test_persistent_rate_limit_stops_after_three_submissions(self):
        error = application.PaddleOCRAPIError("rate limited", code=12002, payload={"code": 12002})
        with patch.object(application, "submit_document_job_once", side_effect=error) as submit, \
                patch.object(application, "wait_with_stop") as wait:
            with self.assertRaises(application.PaddleOCRAPIError) as caught:
                application.submit_document_job_with_retry(
                    Path("paper.pdf"), "key", "model", "batch", "https://example.invalid", 1,
                    lambda: False, Mock())
        self.assertIs(caught.exception, error)
        self.assertEqual(submit.call_count, 3)
        self.assertEqual(wait.call_count, 2)

    def test_retry_can_recover_and_stop_during_wait(self):
        error = application.PaddleOCRAPIError("rate limited", payload={"code": 12002})
        result = {"data": {"jobId": "fixture-job"}}
        with patch.object(application, "submit_document_job_once", side_effect=[error, result]), \
                patch.object(application, "wait_with_stop"):
            self.assertEqual(application.submit_document_job_with_retry(
                Path("paper.pdf"), "key", "model", "batch", "https://example.invalid", 1,
                lambda: False, Mock()), result)
        with self.assertRaises(application.StopRequested):
            application.wait_with_stop(60, lambda: True)

    def test_delays_use_monotonic_time_and_never_sleep_a_negative_interval(self):
        for function in (application.wait_with_stop, application.wait_for_poll_interval):
            with self.subTest(function=function.__name__), \
                    patch.object(application.time, "time", side_effect=AssertionError("wall clock read")), \
                    patch.object(application.time, "monotonic", side_effect=[10, 10.2, 12]), \
                    patch.object(application.time, "sleep") as sleep:
                function(1, lambda: False)
                self.assertEqual(sleep.call_count, 1)
                self.assertGreater(sleep.call_args.args[0], 0)
        event = threading.Event()
        event.set()
        self.assertTrue(application.wait_for_poll_interval(60, lambda: False, event))
        self.assertFalse(event.is_set())

    def test_settings_replace_failure_keeps_previous_file_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.json"
            old = '{"token":"previous-token","ui_language":"en"}'
            config_file.write_text(old, encoding="utf-8")
            with patch.object(application, "CONFIG_DIR", root), \
                    patch.object(application, "CONFIG_PATH", config_file), \
                    patch.object(application.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    application.save_config(application.AppConfig(token="new-token"))
            self.assertEqual(config_file.read_text(encoding="utf-8"), old)
            self.assertEqual(list(root.iterdir()), [config_file])

    def test_settings_successfully_replace_and_preserve_unknown_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(application, "CONFIG_DIR", root), \
                    patch.object(application, "CONFIG_PATH", root / "config.json"):
                config = application.AppConfig(token="saved-token")
                config.future_setting = {"nested": "value"}
                application.save_config(config)
                self.assertEqual(application.load_config().future_setting, {"nested": "value"})
                self.assertEqual(json.loads((root / "config.json").read_text())["token"], "saved-token")
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_model_requests_close_responses_on_parse_failure(self):
        response = Mock(ok=True)
        response.json.return_value = {"data": [], "choices": []}
        for transport, invoke in (
                ("get", lambda: application.fetch_openai_compatible_models("https://example.invalid/v1", "key")),
                ("post", lambda: application.check_openai_compatible_api("https://example.invalid/v1", "key", "model"))):
            with self.subTest(transport=transport), patch.object(application.requests, transport, return_value=response):
                response.close.reset_mock()
                with self.assertRaises(RuntimeError):
                    invoke()
                response.close.assert_called_once()

    def test_model_request_cancellation_does_not_wait_for_transport(self):
        stop, release, entered = threading.Event(), threading.Event(), threading.Event()
        response = Mock(ok=True)
        response.json.return_value = {"data": [{"id": "fixture"}]}
        def request(*_args, **_kwargs):
            entered.set()
            release.wait(2)
            return response
        def cancel():
            entered.wait(1)
            stop.set()
        timer = threading.Thread(target=cancel, daemon=True)
        timer.start()
        try:
            with patch.object(application.requests, "get", side_effect=request):
                start = time.monotonic()
                with self.assertRaises(TaskCancelled):
                    application.fetch_openai_compatible_models("https://example.invalid/v1", "key", stop=stop.is_set)
                self.assertLess(time.monotonic() - start, .5)
        finally:
            release.set()
            timer.join(timeout=1)
        deadline = time.monotonic() + 1
        while not response.close.called and time.monotonic() < deadline:
            time.sleep(.005)
        response.close.assert_called_once()

    def test_pdf_scan_accepts_uppercase_extensions_and_stops_during_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            for name in ("a.PDF", "b.pdf", "ignore.txt", "nested/c.PdF"):
                (root / name).write_bytes(b"fixture")
            self.assertEqual({path.name for path in application.find_pdf_files(root, False)}, {"a.PDF", "b.pdf"})
            self.assertEqual({path.name for path in application.find_pdf_files(root, True)}, {"a.PDF", "b.pdf", "c.PdF"})
            calls = 0
            def stop():
                nonlocal calls
                calls += 1
                return calls >= 3
            with self.assertRaises(application.StopRequested):
                application.find_pdf_files(root, True, stop)
            self.assertEqual(calls, 3)

    def test_size_scan_stats_each_pdf_once_and_preserves_missing_files_for_per_file_errors(self):
        paths = [Path("large.pdf"), Path("missing.pdf"), Path("small.pdf")]
        with patch.object(application, "get_file_size_mb", side_effect=[60, FileNotFoundError(), 1]) as size:
            normal, oversized = application.split_oversized_pdfs(paths)
        self.assertEqual(size.call_count, 3)
        self.assertEqual(normal, paths[1:])
        self.assertEqual(oversized, [(paths[0], 60)])

    def test_result_download_errors_release_responses(self):
        for function in (application.download_text_url, application.download_binary_url):
            for error in (OSError("response failed"), application.StopRequested("stopped")):
                with self.subTest(function=function.__name__, error=type(error).__name__):
                    response = Mock()
                    response.raise_for_status.side_effect = error
                    response.close.side_effect = OSError("cleanup failed")
                    with patch.object(application.requests, "get", return_value=response):
                        with self.assertRaises(type(error)) as caught:
                            function("https://example.invalid/result", 1)
                    self.assertIs(caught.exception, error)
                    response.close.assert_called_once()

    def test_response_cleanup_error_keeps_downloaded_document_and_normal_job_status(self):
        response = Mock(text="# Readable paper\n\nDownloaded content.", encoding="utf-8")
        response.close.side_effect = OSError("cleanup failed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, raw = root / "paper.md", root / "paper.raw.json"
            with patch.object(application.requests, "get", return_value=response):
                markdown, metadata = application.save_result_resources(
                    {"data": {"resultUrl": {"markdownUrl": "https://example.invalid/result"}}},
                    output, raw, 1)
            self.assertEqual(markdown, response.text)
            self.assertEqual(output.read_text(encoding="utf-8"), response.text + "\n")
            self.assertNotIn("markdownDownloadError", metadata)
        response.close.assert_called_once()

        for function, payload, status in (
                (lambda: application.get_job_status("existing", "key", "https://example.invalid", 1),
                 {"code": 0, "data": {"state": "running"}}, 200),
                (lambda: application.validate_access_token("key"),
                 {"code": 11001}, 404)):
            with self.subTest(payload=payload):
                response = Mock()
                response.status_code = status
                response.json.return_value = payload
                response.close.side_effect = OSError("cleanup failed")
                with patch.object(application.requests, "get", return_value=response):
                    result = function()
                if status == 200:
                    self.assertEqual(result, payload)
                else:
                    self.assertTrue(result[0])
                response.close.assert_called_once()

    def test_stopping_result_download_does_not_save_a_placeholder_document(self):
        stop, entered, release, closed = [threading.Event() for _ in range(4)]
        response = Mock(close=closed.set)
        def request(*_args, **_kwargs):
            entered.set()
            release.wait(2)
            return response
        def cancel():
            entered.wait(1)
            stop.set()
        cancel_thread = threading.Thread(target=cancel, daemon=True)
        cancel_thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(application.requests, "get", side_effect=request):
                    with self.assertRaises(application.StopRequested):
                        application.save_result_resources(
                            {"data": {"resultUrl": {"jsonUrl": "https://example.invalid/result"}}},
                            root / "paper.md", root / "paper.raw.json", 1, stop_checker=stop.is_set)
                self.assertEqual(list(root.iterdir()), [])
        finally:
            release.set()
            cancel_thread.join(timeout=1)
        self.assertTrue(closed.wait(1))

    def test_token_probe_is_cancellable_and_closes_successful_responses(self):
        with patch.object(application.requests, "get") as get:
            with self.assertRaises(application.StopRequested):
                application.validate_access_token("key", stop_checker=lambda: True)
            get.assert_not_called()
        response = Mock(status_code=404)
        response.json.return_value = {"code": 11001}
        with patch.object(application.requests, "get", return_value=response):
            self.assertTrue(application.validate_access_token("key")[0])
        response.close.assert_called_once()

    def test_file_removed_after_scan_does_not_abort_following_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing, available = root / "missing.pdf", root / "available.pdf"
            available.write_bytes(b"fixture")
            gui = object.__new__(application.PaddleOCRBatchGUI)
            gui.stop_requested = False
            gui.log_queue = queue.Queue()
            gui.manual_query_event = threading.Event()
            gui.literature = Mock()
            with patch.object(application, "process_one_pdf_async", return_value=("text", {})) as process:
                gui._worker([missing, available], root, root, "key", "model", "https://example.invalid",
                            False, False, 1, 60, 0, False, "", "", "")
            process.assert_called_once()
            self.assertEqual(process.call_args.kwargs["pdf_path"], available)
            gui.literature.after_ocr.assert_called_once()
            log = (root / application.LOG_FILE_NAME).read_text(encoding="utf-8")
            self.assertIn("成功 1，跳过 0，失败 1", log)


if __name__ == "__main__":
    unittest.main()
