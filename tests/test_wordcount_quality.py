import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paddleocr_pdf_to_md_gui import (
    count_words_and_cjk,
    markdown_is_too_short,
    manually_check_markdown_wordcount,
    process_one_pdf_async,
    remove_low_wordcount_artifacts,
    fetch_openai_compatible_models,
    review_markdown_with_llm,
    check_openai_compatible_api,
)


class WordCountQualityTests(unittest.TestCase):
    def test_counts_cjk_characters_and_latin_words(self):
        self.assertEqual(count_words_and_cjk("你好 PaddleOCR works well"), 5)

    def test_threshold_is_applied_per_page(self):
        self.assertEqual(markdown_is_too_short("字" * 299, 2), (True, 299))
        self.assertEqual(markdown_is_too_short("字" * 300, 2), (False, 300))

    def test_manual_check_reads_page_count_from_sibling_json(self):
        with tempfile.TemporaryDirectory() as directory:
            md_path = Path(directory) / "document.md"
            md_path.write_text("字" * 299, encoding="utf-8")
            md_path.with_suffix(".raw.json").write_text(
                json.dumps({"jobStatus": {"data": {"totalPages": 2}}}), encoding="utf-8"
            )
            result = manually_check_markdown_wordcount(md_path)
        self.assertEqual(result["pageCount"], 2)
        self.assertEqual(result["minimum"], 300)
        self.assertTrue(result["hasProblem"])

    def test_removes_result_json_and_job_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            md_path = root / "result.md"
            paths = [
                md_path,
                md_path.with_suffix(".json"),
                md_path.with_suffix(".raw.json"),
                root / "document.job.json",
            ]
            for path in paths:
                path.write_text("result", encoding="utf-8")

            remove_low_wordcount_artifacts(md_path, paths[-1])

            self.assertTrue(all(not path.exists() for path in paths))

    def test_resubmits_three_times_then_returns_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "document.pdf"
            output_path = root / "document.md"
            pdf_path.write_bytes(b"fake pdf")
            submissions = iter(("job-1", "job-2", "job-3"))

            def submit(**_kwargs):
                return {"data": {"jobId": next(submissions)}}

            def save(_payload, md_path, raw_path, _timeout):
                md_path.write_text("内容太少", encoding="utf-8")
                raw_path.write_text("{}", encoding="utf-8")
                return "内容太少", {}

            logs = []
            with (
                patch("paddleocr_pdf_to_md_gui.submit_document_job_with_retry", side_effect=submit) as submit_mock,
                patch("paddleocr_pdf_to_md_gui.poll_job_until_done", return_value={"data": {"progress": {"totalPages": 1}}}),
                patch("paddleocr_pdf_to_md_gui.save_result_resources", side_effect=save),
            ):
                _markdown, raw_data = process_one_pdf_async(
                    pdf_path=pdf_path,
                    output_md_path=output_path,
                    output_root=root,
                    token="token",
                    model_name="model",
                    base_url="https://example.invalid",
                    request_timeout=1,
                    poll_timeout=1,
                    poll_interval=0,
                    overwrite=False,
                    stop_checker=lambda: False,
                    progress_callback=lambda *_args: None,
                    log_callback=logs.append,
                )

            self.assertEqual(submit_mock.call_count, 3)
            self.assertIn("qualityWarning", raw_data)
            self.assertTrue(output_path.exists())
            self.assertTrue(any("请核验原件字数" in line for line in logs))


class LLMReviewTests(unittest.TestCase):
    def test_llm_api_sends_minimal_chat_completion(self):
        response = Mock(ok=True)
        response.json.return_value = {"choices": [{"message": {"content": "OK"}}]}
        with patch("paddleocr_pdf_to_md_gui.requests.post", return_value=response) as post_mock:
            reply = check_openai_compatible_api(
                "https://api.example/v1/", "secret", "test-model", timeout=3
            )
        self.assertEqual(reply, "OK")
        self.assertEqual(post_mock.call_args.args[0], "https://api.example/v1/chat/completions")
        self.assertEqual(post_mock.call_args.kwargs["json"]["model"], "test-model")
        self.assertNotIn("max_tokens", post_mock.call_args.kwargs["json"])
        self.assertEqual(post_mock.call_args.kwargs["timeout"], 3)

    def test_llm_api_empty_reply_reports_finish_reason(self):
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}]
        }
        with patch("paddleocr_pdf_to_md_gui.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "finish_reason=length"):
                check_openai_compatible_api(
                    "https://api.example/v1", "secret", "reasoning-model"
                )

    def test_fetches_and_sorts_openai_compatible_models(self):
        response = Mock(ok=True)
        response.json.return_value = {"data": [{"id": "deepseek-reasoner"}, {"id": "deepseek-chat"}]}
        with patch("paddleocr_pdf_to_md_gui.requests.get", return_value=response) as get_mock:
            models = fetch_openai_compatible_models("https://api.example/v1/", "secret")
        self.assertEqual(models, ["deepseek-chat", "deepseek-reasoner"])
        self.assertEqual(get_mock.call_args.args[0], "https://api.example/v1/models")
        self.assertEqual(get_mock.call_args.kwargs["headers"]["Authorization"], "Bearer secret")

    def test_reviews_all_chunks_and_combines_problem_result(self):
        responses = []
        for has_problem in (False, True):
            response = Mock(ok=True)
            response.json.return_value = {
                "choices": [{"message": {"content": json.dumps({
                    "has_problem": has_problem,
                    "severity": "high" if has_problem else "none",
                    "summary": "检测结果",
                    "issues": [],
                    "evidence": [],
                })}}]
            }
            responses.append(response)
        markdown = "字" * 50001
        answers = []
        with patch("paddleocr_pdf_to_md_gui.requests.post", side_effect=responses) as post_mock:
            result = review_markdown_with_llm(
                markdown, "document.md", "https://api.example/v1", "secret", "model",
                response_callback=lambda index, total, content: answers.append(
                    (index, total, content)
                ),
            )
        self.assertTrue(result["hasProblem"])
        self.assertEqual(len(result["chunks"]), 2)
        self.assertEqual(post_mock.call_count, 2)
        self.assertEqual([(item[0], item[1]) for item in answers], [(1, 2), (2, 2)])
        self.assertIn('"has_problem": true', answers[1][2])

    def test_llm_problem_removes_artifacts_and_resubmits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "document.pdf"
            output_path = root / "document.md"
            pdf_path.write_bytes(b"fake pdf")
            submissions = iter(("job-1", "job-2"))

            def submit(**_kwargs):
                return {"data": {"jobId": next(submissions)}}

            def save(_payload, md_path, raw_path, _timeout):
                markdown = "字" * 150
                md_path.write_text(markdown, encoding="utf-8")
                raw_path.write_text("{}", encoding="utf-8")
                return markdown, {}

            reviews = [
                {"hasProblem": True, "chunks": []},
                {"hasProblem": False, "chunks": []},
            ]
            with (
                patch("paddleocr_pdf_to_md_gui.submit_document_job_with_retry", side_effect=submit) as submit_mock,
                patch("paddleocr_pdf_to_md_gui.poll_job_until_done", return_value={"data": {"progress": {"totalPages": 1}}}),
                patch("paddleocr_pdf_to_md_gui.save_result_resources", side_effect=save),
                patch("paddleocr_pdf_to_md_gui.review_markdown_with_llm", side_effect=reviews) as review_mock,
            ):
                _markdown, raw_data = process_one_pdf_async(
                    pdf_path=pdf_path,
                    output_md_path=output_path,
                    output_root=root,
                    token="token",
                    model_name="ocr-model",
                    base_url="https://ocr.invalid",
                    request_timeout=1,
                    poll_timeout=1,
                    poll_interval=0,
                    overwrite=False,
                    stop_checker=lambda: False,
                    progress_callback=lambda *_args: None,
                    log_callback=lambda _message: None,
                    llm_review_enabled=True,
                    llm_base_url="https://llm.invalid/v1",
                    llm_api_key="key",
                    llm_model="llm-model",
                )

            self.assertEqual(submit_mock.call_count, 2)
            self.assertEqual(review_mock.call_count, 2)
            self.assertFalse(raw_data["llmReview"]["hasProblem"])
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
