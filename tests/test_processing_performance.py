import subprocess
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp
import model_budget


class ProcessingPerformanceTests(unittest.TestCase):
    def test_response_cleanup_error_does_not_replace_content_or_http_failure(self):
        profile = lp.ModelProfile("https://example.invalid/v1", "key", "model")
        response = Mock(ok=True, status_code=503)
        response.json.return_value = {"choices": [{"message": {"content": "Complete translation"}}]}
        response.close.side_effect = OSError("socket cleanup failed")
        with patch.object(lp.requests, "post", return_value=response):
            self.assertEqual(lp.chat(profile, "Translate faithfully.", {"source": "Text"}), "Complete translation")
            response.ok = False
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                lp.chat(profile, "Translate faithfully.", {"source": "Text"})

    def test_completed_upload_remains_successful_if_response_close_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.md"
            path.write_bytes(b"Verified document")
            lookup, uploaded = Mock(status_code=404), Mock(status_code=201)
            for response in (lookup, uploaded):
                response.close.side_effect = OSError("socket cleanup failed")
            with patch.object(lp.requests, "get", return_value=lookup), \
                    patch.object(lp.requests, "put", return_value=uploaded) as put:
                result = lp.upload_verified_file(path, "paper.md", True,
                    lp.GitHubOptions("owner/repository", "fixture-key"),
                    hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(result, "paper.md")
            put.assert_called_once()

    def test_many_math_blocks_do_not_rebudget_every_growing_prefix(self):
        text = "Text\n\n$$x$$\n\n" * 1000
        for limit in (600, 1000000):
            with self.subTest(limit=limit):
                inspected = 0
                def fits(value):
                    nonlocal inspected
                    inspected += len(value)
                    return len(value) <= limit
                chunks = lp.formatting_chunks(text, fits)
                self.assertEqual("".join(chunks), text)
                self.assertTrue(all(len(chunk) <= limit for chunk in chunks))
                self.assertTrue(all(chunk.count("$$") % 2 == 0 for chunk in chunks))
                self.assertLess(inspected, len(text) * 20)

    def test_malformed_long_ocr_lines_do_not_cause_regex_backtracking_hangs(self):
        # Isolate the check because a regressed C regex can hold the GIL and
        # prevent an in-process timer from firing. Current work is linear and
        # takes milliseconds; the former patterns take tens of seconds.
        code = (
            "from literature_processing import _markdown_protected\n"
            "assert _markdown_protected('|' * 300000 + '\\nOrdinary prose.\\n') == []\n"
            "assert _markdown_protected(r'\\[x ' * 30000) == []\n"
        )
        result = subprocess.run([sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_table_final_row_without_a_newline_remains_in_the_protected_block(self):
        table = "|Name|Value|\n|---|---|\n|Evidence|12|"
        text = "A short introduction.\n\n" + table
        chunks = lp.formatting_chunks(text, lambda value: len(value) <= len(table) + 1)
        self.assertEqual("".join(chunks), text)
        self.assertIn(table, chunks)

    def test_math_matching_preserves_mixed_inline_and_display_content(self):
        samples = [
            r"$x$ and $$y$$ and \[z\]",
            r"\[unclosed $$x$$ and $y$",
            r"$a \[b\] c$",
            "$x\n$$y$$",
            r"\[a $$b$$ c\]",
        ]
        import re
        pattern = r"\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|(?<!\$)\$(?!\$)[^\n$]+\$(?!\$)"
        for text in samples:
            with self.subTest(text=text):
                expected = [(match.start(), match.end()) for match in re.finditer(pattern, text)]
                self.assertEqual(list(lp._math_blocks(text, include_inline=True)), expected)
                self.assertEqual(lp.formatting_content_issues(text, text), [])

    def test_chat_serializes_once_for_budget_body_and_output_reservation(self):
        profile = lp.ModelProfile("https://example.invalid/v1", "key", "model", output_limit=8000)
        response = Mock(ok=True)
        response.json.return_value = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}
        data = {"source": "中文 😀\n" * 1000}
        with patch.object(model_budget, "messages", wraps=model_budget.messages) as serialize, \
                patch.object(lp.requests, "post", return_value=response) as post:
            self.assertEqual(lp.chat(profile, "Translate faithfully.", data), "OK")
        serialize.assert_called_once_with("Translate faithfully.", data)
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 8000)
        self.assertEqual(post.call_args.kwargs["json"]["messages"], model_budget.messages("Translate faithfully.", data))
        response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
