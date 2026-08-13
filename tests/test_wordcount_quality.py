import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paddleocr_pdf_to_md_gui import (
    count_words_and_cjk,
    markdown_is_too_short,
    process_one_pdf_async,
    remove_low_wordcount_artifacts,
)


class WordCountQualityTests(unittest.TestCase):
    def test_counts_cjk_characters_and_latin_words(self):
        self.assertEqual(count_words_and_cjk("你好 PaddleOCR works well"), 5)

    def test_threshold_is_applied_per_page(self):
        self.assertEqual(markdown_is_too_short("字" * 299, 2), (True, 299))
        self.assertEqual(markdown_is_too_short("字" * 300, 2), (False, 300))

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


if __name__ == "__main__":
    unittest.main()
