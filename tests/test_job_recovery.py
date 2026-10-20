"""Bounded jobId recovery, cancellation, and cache lifecycle regression tests."""
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import paddleocr_pdf_to_md_gui as app


def status(state="done", **extra):
    return {"code": 0, "data": {"state": state, "totalPages": 1, **extra}}


class JobRecoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.pdf = self.root / "paper.pdf"
        self.pdf.write_bytes(b"test PDF")
        self.output = self.root / "paper.md"
        self.cache = app.get_job_cache_path(self.root, self.pdf)
        self.logs = []
        self.stop = threading.Event()
        self.wait = patch.object(app, "wait_for_poll_interval", return_value=False)
        self.wait.start()
        self.addCleanup(self.wait.stop)
        self.save = patch.object(app, "save_result_resources", side_effect=self.save_result)
        self.save.start()
        self.addCleanup(self.save.stop)

    @staticmethod
    def save_result(_payload, markdown_path, raw_path, _timeout, **_kwargs):
        markdown = "字" * 150
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")
        raw_path.write_text("{}", encoding="utf-8")
        return markdown, {}

    def process(self, **kwargs):
        return app.process_one_pdf_async(
            self.pdf, self.output, self.root, "key", "model", "https://example.invalid",
            1, 60, 0, False, self.stop.is_set, Mock(), self.logs.append, **kwargs)

    def test_status_requires_success_code_and_known_state_and_closes_response(self):
        invalid = [
            {}, {"code": None, "data": {"state": "done"}},
            {"code": "0", "data": {"state": "done"}},
            {"code": False, "data": {"state": "done"}},
            {"code": 0.0, "data": {"state": "done"}},
            {"code": 12002, "data": {"state": "done"}},
            {"code": 0, "data": None}, {"code": 0, "data": {}},
            status("failed"), status("unknown"), status("cancelled"),
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = Mock(status_code=200)
                response.json.return_value = payload
                with patch.object(app.requests, "get", return_value=response):
                    with self.assertRaises(app.PaddleOCRAPIError):
                        app.get_job_status("job", "key", "https://example.invalid", 1)
                response.close.assert_called_once()
        for http_code in (200, 201):
            for state in ("pending", "running", "done"):
                with self.subTest(http_code=http_code, state=state):
                    response = Mock(status_code=http_code)
                    response.json.return_value = status(state)
                    with patch.object(app.requests, "get", return_value=response):
                        self.assertEqual(app.get_job_status("job", "key", "https://example.invalid", 1), status(state))
                    response.close.assert_called_once()

    def test_http_and_non_json_responses_are_anomalies(self):
        for code in (202, 400, 401, 403, 404, 429, 500):
            with self.subTest(code=code):
                response = Mock(status_code=code)
                response.json.return_value = status()
                with patch.object(app.requests, "get", return_value=response):
                    with self.assertRaises(app.PaddleOCRAPIError):
                        app.get_job_status("job", "key", "https://example.invalid", 1)
                response.close.assert_called_once()
        response = Mock(status_code=200, text="<html>proxy error</html>")
        response.json.side_effect = ValueError("invalid JSON")
        with patch.object(app.requests, "get", return_value=response):
            with self.assertRaises(app.PaddleOCRAPIError):
                app.get_job_status("job", "key", "https://example.invalid", 1)
        response.close.assert_called_once()

    def test_pending_and_running_do_not_consume_retries(self):
        responses = [status("pending"), status("running")] * 7 + [status()]
        with patch.object(app, "submit_document_job_with_retry", return_value={"data": {"jobId": "healthy"}}) as submit, \
                patch.object(app, "get_job_status", side_effect=responses) as get:
            markdown, _ = self.process()
        self.assertEqual(markdown, "字" * 150)
        self.assertEqual(get.call_count, 15)
        submit.assert_called_once()
        self.assertEqual(json.loads(self.cache.read_text())["jobId"], "healthy")
        self.assertFalse(any("查询异常" in str(item) for item in self.logs))

    def test_cached_job_gets_three_retries_then_new_job_replaces_deleted_cache(self):
        self.cache.write_text('{"jobId": "expired"}', encoding="utf-8")
        def submit(**_kwargs):
            self.assertFalse(self.cache.exists())
            return {"data": {"jobId": "replacement"}}
        error = app.PaddleOCRAPIError("expired", code=11001)
        with patch.object(app, "submit_document_job_with_retry", side_effect=submit) as send, \
                patch.object(app, "get_job_status", side_effect=[error] * 4 + [status()]) as get:
            self.process()
        send.assert_called_once()
        self.assertEqual([call.args[0] for call in get.call_args_list], ["expired"] * 4 + ["replacement"])
        self.assertEqual(json.loads(self.cache.read_text())["jobId"], "replacement")
        self.assertTrue(any("已删除异常 jobId" in str(item) for item in self.logs))

    def test_four_failed_jobs_stop_after_sixteen_query_attempts(self):
        submitted = [{"data": {"jobId": f"job-{index}"}} for index in range(4)]
        with patch.object(app, "submit_document_job_with_retry", side_effect=submitted) as send, \
                patch.object(app, "get_job_status", side_effect=TimeoutError("request timed out")) as get:
            with self.assertRaises(app.JobRecoverySkipped):
                self.process()
        self.assertEqual(send.call_count, 4)
        self.assertEqual(get.call_count, 16)
        self.assertEqual([call.args[0] for call in get.call_args_list],
                         [f"job-{index}" for index in range(4) for _ in range(4)])
        batches = [call.kwargs["batch_id"] for call in send.call_args_list]
        self.assertEqual(len(set(batches)), 4)
        self.assertFalse(self.cache.exists())
        self.assertFalse(self.output.exists())

    def test_healthy_interleaved_responses_do_not_reset_anomaly_budget(self):
        sequence = [status("unknown"), status("pending"), status("failed"),
                    status("running"), ValueError("malformed response"),
                    status("pending"), TimeoutError("network timeout")] * 4
        submitted = [{"data": {"jobId": f"job-{index}"}} for index in range(4)]
        with patch.object(app, "submit_document_job_with_retry", side_effect=submitted) as send, \
                patch.object(app, "get_job_status", side_effect=sequence) as get:
            with self.assertRaises(app.JobRecoverySkipped):
                self.process()
        self.assertEqual(send.call_count, 4)
        self.assertEqual(get.call_count, 28)
        self.assertFalse(self.cache.exists())

    def test_cached_original_has_only_three_additional_submissions(self):
        self.cache.write_text('{"jobId":"old"}', encoding="utf-8")
        with patch.object(app, "submit_document_job_with_retry",
                          side_effect=[{"data": {"jobId": f"new-{index}"}} for index in range(3)]) as send, \
                patch.object(app, "get_job_status", return_value=status("failed")) as get:
            with self.assertRaises(app.JobRecoverySkipped):
                self.process()
        self.assertEqual(send.call_count, 3)
        self.assertEqual(get.call_count, 16)
        self.assertFalse(self.cache.exists())

    def test_cancel_preserves_current_job_and_never_resubmits(self):
        self.cache.write_text('{"jobId":"in-progress"}', encoding="utf-8")
        with patch.object(app, "submit_document_job_with_retry") as send, \
                patch.object(app, "get_job_status", side_effect=app.StopRequested("cancelled")) as get:
            with self.assertRaises(app.StopRequested):
                self.process()
        send.assert_not_called()
        get.assert_called_once()
        self.assertEqual(json.loads(self.cache.read_text())["jobId"], "in-progress")

    def test_stop_flag_wins_over_a_transport_error(self):
        self.cache.write_text('{"jobId":"in-progress"}', encoding="utf-8")
        def query(*_args):
            self.stop.set()
            raise OSError("transport closed")
        with patch.object(app, "submit_document_job_with_retry") as send, \
                patch.object(app, "get_job_status", side_effect=query):
            with self.assertRaises(app.StopRequested):
                self.process()
        send.assert_not_called()
        self.assertTrue(self.cache.exists())

    def test_cancel_during_retry_delay_preserves_the_current_job(self):
        self.cache.write_text('{"jobId":"waiting"}', encoding="utf-8")
        with patch.object(app, "submit_document_job_with_retry") as send, \
                patch.object(app, "get_job_status", return_value=status("failed")) as get, \
                patch.object(app, "wait_for_poll_interval", side_effect=app.StopRequested("cancelled")):
            with self.assertRaises(app.StopRequested):
                self.process()
        send.assert_not_called()
        get.assert_called_once()
        self.assertEqual(json.loads(self.cache.read_text())["jobId"], "waiting")

    def test_overall_poll_timeout_consumes_the_same_four_anomaly_budget(self):
        with patch.object(app.time, "monotonic", side_effect=[0, 2] * 4), \
                patch.object(app, "get_job_status") as get:
            with self.assertRaises(TimeoutError):
                app.poll_job_with_retries(
                    job_id="slow", token="key", base_url="https://example.invalid", request_timeout=1,
                    poll_timeout=1, poll_interval=0, stop_checker=self.stop.is_set,
                    progress_callback=Mock(), log_callback=self.logs.append)
        get.assert_not_called()
        self.assertEqual(len(self.logs), 4)
        self.assertTrue(all("查询异常" in str(item) for item in self.logs))

    def test_failed_cache_deletion_never_reuses_or_resubmits_bad_id(self):
        self.cache.write_text('{"jobId":"bad"}', encoding="utf-8")
        unlink = Path.unlink
        def locked(path, *args, **kwargs):
            if path == self.cache:
                raise PermissionError("locked cache")
            return unlink(path, *args, **kwargs)
        with patch.object(app, "submit_document_job_with_retry") as send, \
                patch.object(app, "get_job_status", return_value=status("failed")) as get, \
                patch.object(Path, "unlink", new=locked):
            with self.assertRaisesRegex(RuntimeError, "无法删除"):
                self.process()
        self.assertEqual(get.call_count, 4)
        send.assert_not_called()
        self.assertEqual(json.loads(self.cache.read_text())["jobId"], "bad")

    def test_resubmission_cannot_reactivate_an_already_retired_id(self):
        with patch.object(app, "submit_document_job_with_retry", return_value={"data": {"jobId": "same-id"}}) as send, \
                patch.object(app, "get_job_status", return_value=status("failed")) as get:
            with self.assertRaises(app.JobRecoverySkipped):
                self.process()
        self.assertEqual(send.call_count, 4)
        self.assertEqual(get.call_count, 4)
        self.assertFalse(self.cache.exists())

    def test_submission_errors_and_missing_ids_have_a_finite_retry_budget(self):
        for result in (OSError("connection failed"), {"data": {}}, {"data": {"jobId": False}}):
            with self.subTest(result=result):
                with patch.object(app, "submit_document_job_with_retry") as send, \
                        patch.object(app, "get_job_status") as get:
                    if isinstance(result, Exception):
                        send.side_effect = result
                    else:
                        send.return_value = result
                    with self.assertRaises(app.JobRecoverySkipped):
                        self.process()
                self.assertEqual(send.call_count, 4)
                get.assert_not_called()
                self.assertFalse(self.cache.exists())

    def test_corrupt_cache_is_removed_before_a_fresh_submission(self):
        self.cache.write_text("incomplete JSON", encoding="utf-8")
        def submit(**_kwargs):
            self.assertFalse(self.cache.exists())
            return {"data": {"jobId": "fresh"}}
        with patch.object(app, "submit_document_job_with_retry", side_effect=submit) as send, \
                patch.object(app, "get_job_status", return_value=status()):
            self.process()
        send.assert_called_once()
        self.assertEqual(json.loads(self.cache.read_text())["jobId"], "fresh")

    def test_cache_write_error_does_not_create_more_remote_jobs(self):
        with patch.object(app, "submit_document_job_with_retry", return_value={"data": {"jobId": "new"}}) as send, \
                patch.object(app, "get_job_status") as get, \
                patch.object(app.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.process()
        send.assert_called_once()
        get.assert_not_called()
        self.assertFalse(list(self.cache.parent.glob(".job-*.tmp")))

    def test_submission_http_429_retries_and_closes_every_response(self):
        limited = Mock(status_code=429)
        limited.json.return_value = {"message": "too many requests"}
        accepted = Mock(status_code=201)
        accepted.json.return_value = {"code": 0, "data": {"jobId": "accepted"}}
        with patch.object(app.requests, "post", side_effect=[limited, accepted]) as post, \
                patch.object(app, "wait_with_stop"):
            result = app.submit_document_job_with_retry(
                self.pdf, "key", "model", "batch", "https://example.invalid",
                1, self.stop.is_set, self.logs.append)
        self.assertEqual(result["data"]["jobId"], "accepted")
        self.assertEqual(post.call_count, 2)
        limited.close.assert_called_once()
        accepted.close.assert_called_once()

    def test_split_parts_use_the_same_captured_ocr_prompt(self):
        work = self.root / "split"
        work.mkdir()
        parts = [app.SplitPdfPart(work / f"{index}.pdf", index, index, index, 1)
                 for index in (1, 2)]
        prompts = {"ocr_review": "同一次任务使用相同质量规则"}
        with patch.object(app, "split_pdf_for_upload", return_value=(parts, work, 2)), \
                patch.object(app, "process_one_pdf_async", return_value=("字" * 150, {})) as process:
            app.process_split_pdf_async(
                self.pdf, self.output, self.root, "key", "model", "https://example.invalid",
                1, 60, 0, False, self.stop.is_set, Mock(), Mock(), self.logs.append, prompts=prompts)
        self.assertEqual(process.call_count, 2)
        self.assertTrue(all(call.kwargs["prompts"] is prompts for call in process.call_args_list))

    def test_batch_skips_exhausted_file_and_continues_to_next_pdf(self):
        second = self.root / "second.pdf"
        second.write_bytes(b"second PDF")
        gui = object.__new__(app.PaddleOCRBatchGUI)
        gui.stop_requested = False
        gui.log_queue = queue.Queue()
        gui.manual_query_event = threading.Event()
        gui.literature = Mock()
        counter = 0
        def submit(**kwargs):
            nonlocal counter
            counter += 1
            return {"data": {"jobId": "good" if kwargs["pdf_path"] == second else f"bad-{counter}"}}
        def query(job_id, *_args):
            return status() if job_id == "good" else status("failed")
        with patch.object(app, "submit_document_job_with_retry", side_effect=submit), \
                patch.object(app, "get_job_status", side_effect=query):
            gui._worker([self.pdf, second], self.root, self.root, "key", "model",
                        "https://example.invalid", False, False, 1, 60, 0, False, "", "", "")
        self.assertEqual(counter, 5)
        self.assertTrue(second.with_suffix(".md").exists())
        gui.literature.after_ocr.assert_called_once()
        log = (self.root / app.LOG_FILE_NAME).read_text(encoding="utf-8")
        self.assertIn("SKIP_JOB_RECOVERY", log)
        self.assertIn("成功 1，跳过 1，失败 0", log)


if __name__ == "__main__":
    unittest.main()
