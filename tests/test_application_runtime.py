"""Regression checks for bounded OCR retry and lossless settings writes."""
import json
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


if __name__ == "__main__":
    unittest.main()
