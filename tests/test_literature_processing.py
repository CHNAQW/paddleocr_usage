import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "paper.md"
        self.source.write_text("# Foreign paper\n\nEvidence and conclusions.", encoding="utf-8")
        self.output = self.root / "paper_TRANSLATED.md"
        self.profile = lp.ModelProfile("https://example.invalid/v1", "secret", "translator")
        self.detect = json.dumps({"language": "English", "is_target_language": False})

    def translate(self, responses, **kwargs):
        with patch.object(lp, "chat", side_effect=responses) as chat:
            result = lp.translate_document(self.source, self.output, kwargs.pop("options", lp.TranslationOptions()),
                                           self.profile, **kwargs)
        return result, chat

    def test_detection_only_sends_first_300_characters(self):
        with patch.object(lp, "chat", return_value=self.detect) as chat:
            lp.detect_language("A" * 900, "简体中文 (ch)", self.profile)
        self.assertEqual(chat.call_args.args[2]["sample"], "A" * 300)

    def test_target_language_is_skipped_without_translation(self):
        result, chat = self.translate(['{"language":"Chinese","is_target_language":true}'])
        self.assertEqual(result["status"], "target_language")
        self.assertEqual(chat.call_count, 1)
        self.assertFalse(self.output.exists())

    def test_translation_preserves_original_and_writes_report_without_keys(self):
        original = self.source.read_bytes()
        result, _ = self.translate([self.detect, "# 外文文献\n\n证据与结论。"])
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(result["outputSHA256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        report = self.output.with_suffix(".translation.json").read_text(encoding="utf-8")
        self.assertNotIn("secret", report)
        self.assertNotIn("api_key", report)

    def test_existing_translation_is_never_reused_as_verified_or_overwritten(self):
        self.output.write_text("previous", encoding="utf-8")
        result, chat = self.translate([])
        self.assertEqual(result["status"], "existing")
        self.assertFalse(result["verified"])
        chat.assert_not_called()
        self.assertEqual(self.output.read_text(), "previous")

    def test_source_digest_matches_original_windows_file_with_bom(self):
        original = b"\xef\xbb\xbf# Paper\r\n\r\nEvidence."
        self.source.write_bytes(original)
        result, _ = self.translate([self.detect, "译文"])
        self.assertEqual(result["sourceSHA256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.source.read_bytes(), original)

    def test_cannot_overwrite_source(self):
        with self.assertRaises(ValueError):
            lp.translate_document(self.source, self.source, lp.TranslationOptions(), self.profile)

    def test_manual_source_language_still_checks_target(self):
        _, chat = self.translate([self.detect, "译文"], options=lp.TranslationOptions(source="法语 (fr)"))
        self.assertEqual(chat.call_args_list[1].args[2]["source_language"], "French")

    def test_secondary_review_independently_retranslates_and_compares(self):
        reviewer = lp.ModelProfile(self.profile.base_url, "other-key", "reviewer")
        result, chat = self.translate([self.detect, "首次", "二次", '{"has_problem":false}'],
                options=lp.TranslationOptions(secondary_review=True), reviewer=reviewer)
        self.assertTrue(result["verified"])
        self.assertEqual(chat.call_args_list[2].args[0], reviewer)
        self.assertNotIn("first", chat.call_args_list[2].args[2])
        self.assertEqual(chat.call_args_list[3].args[2]["first"], "首次")

    def test_user_arbitration_can_select_second_translation(self):
        decide = Mock(return_value="second")
        result, _ = self.translate([self.detect, "首次", "修正后", '{"has_problem":true,"issues":["漏译"]}'],
            options=lp.TranslationOptions(secondary_review=True), reviewer=self.profile, decide=decide)
        self.assertTrue(result["verified"])
        self.assertEqual(self.output.read_text(encoding="utf-8"), "修正后\n")
        self.assertEqual(decide.call_args.args[0]["source"], self.source.read_text())

    def test_unresolved_dispute_is_saved_without_upload_eligibility(self):
        result, _ = self.translate([self.detect, "首次", "二次", '{"has_problem":true}'],
            options=lp.TranslationOptions(secondary_review=True), reviewer=self.profile,
            decide=lambda payload: "unresolved")
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["verified"])
        self.assertEqual(result["checks"][0]["candidates"]["second"], "二次")

    def test_model_arbitration_requires_positive_approval(self):
        for verdict, verified in (({"choice": "second", "has_problem": False}, True),
                                  ({"choice": "second", "has_problem": True}, False),
                                  ({"choice": "unresolved", "has_problem": False}, False)):
            with self.subTest(verdict=verdict):
                if self.output.exists():
                    self.output.unlink()
                result, _ = self.translate([self.detect, "首次", "二次", '{"has_problem":true}', json.dumps(verdict)],
                    options=lp.TranslationOptions(secondary_review=True, arbitration="大模型裁决"),
                    reviewer=self.profile, arbiter=self.profile)
                self.assertEqual(result["verified"], verified)

    def test_proofreading_failure_blocks_otherwise_approved_translation(self):
        result, _ = self.translate([self.detect, "首次", "二次", '{"has_problem":false}',
                                   '{"has_problem":true,"issues":["缺字"]}'],
            options=lp.TranslationOptions(secondary_review=True, proofreading=True),
            reviewer=self.profile, proofreader=self.profile)
        self.assertEqual(result["status"], "needs_review")

    def test_proofreading_can_be_used_alone(self):
        result, _ = self.translate([self.detect, "译文", '{"has_problem":false}'],
            options=lp.TranslationOptions(proofreading=True), proofreader=self.profile)
        self.assertTrue(result["verified"])

    def test_malformed_review_does_not_produce_approved_output(self):
        with self.assertRaises(RuntimeError):
            self.translate([self.detect, "译文", '{"has_problem":"false"}'],
                options=lp.TranslationOptions(proofreading=True), proofreader=self.profile)
        self.assertFalse(self.output.exists())

    def test_multiple_chunks_require_all_checks_to_pass(self):
        self.source.write_text("A" * 3500, encoding="utf-8")
        self.profile = lp.ModelProfile(self.profile.base_url, "secret", "translator", input_limit=18000)
        result, chat = self.translate([self.detect, "第一段", '{"has_problem":false}', "第二段", '{"has_problem":true}'],
            options=lp.TranslationOptions(proofreading=True), proofreader=self.profile)
        self.assertEqual(len(result["checks"]), 2)
        self.assertFalse(result["verified"])
        self.assertEqual(chat.call_args_list[1].args[2]["source"] + chat.call_args_list[3].args[2]["source"], "A" * 3500)

    def test_empty_or_unknown_language_cannot_be_misreported_as_translated(self):
        with self.assertRaises(ValueError):
            lp.detect_language("  ", "Chinese", self.profile)
        with patch.object(lp, "chat", return_value='{"language":"unknown","is_target_language":false}'):
            with self.assertRaises(RuntimeError):
                lp.detect_language("---", "Chinese", self.profile)

    def test_cancelled_document_creates_no_output(self):
        with self.assertRaises(lp.ProcessingCancelled):
            self.translate([self.detect], stop=lambda: True)
        self.assertFalse(self.output.exists())

    def test_scan_excludes_generated_outputs_and_preserves_nested_paths(self):
        nested = self.root / "nested"
        nested.mkdir()
        source = nested / "a.MD"
        source.write_text("source")
        (nested / "TRANSLATED_a.md").touch()
        (nested / "a_TRANSLATED.md").touch()
        output = self.root / "output"
        output.mkdir()
        (output / "other.md").touch()
        self.assertEqual(lp.find_markdown_files(self.root, True, output), [source, self.source])
        self.assertEqual(lp.translated_path(source, self.root, output, True), output / "nested" / "TRANSLATED_a.md")
        self.assertEqual(lp.translated_path(source, self.root, None), nested / "a_TRANSLATED.md")


class ChatTests(unittest.TestCase):
    def test_truncated_response_is_rejected(self):
        response = Mock(ok=True)
        response.json.return_value = {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}
        with patch.object(lp.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "截断"):
                lp.chat(lp.ModelProfile("https://example.invalid/v1", "key", "model"), "translate", {})

    def test_compatible_request_has_no_mandatory_json_or_token_features(self):
        response = Mock(ok=True)
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
        profile = lp.ModelProfile("https://example.invalid/custom/", "key", "endpoint-id")
        with patch.object(lp.requests, "post", return_value=response) as post:
            self.assertEqual(lp.chat(profile, "translate", {"source": "document"}), "OK")
        self.assertEqual(post.call_args.args[0], "https://example.invalid/custom/chat/completions")
        body = post.call_args.kwargs["json"]
        self.assertEqual(set(body), {"model", "messages"})
        self.assertEqual(body["messages"][0]["role"], "system")


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "已核验.md"
        self.path.write_bytes(b"reviewed content")
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.options = lp.GitHubOptions("owner/repo", "secret", "papers", "literature")

    def upload(self, verified=True, sha=None, name="nested/已核验.md"):
        return lp.upload_verified_file(self.path, name, verified, self.options, sha or self.sha)

    def test_unverified_or_modified_file_causes_no_network_requests(self):
        with patch.object(lp.requests, "get") as get, patch.object(lp.requests, "put") as put:
            with self.assertRaises(ValueError):
                self.upload(False)
            self.path.write_bytes(b"modified")
            with self.assertRaises(ValueError):
                self.upload()
        get.assert_not_called()
        put.assert_not_called()

    def test_existing_remote_is_not_overwritten(self):
        with patch.object(lp.requests, "get", return_value=Mock(status_code=200)), patch.object(lp.requests, "put") as put:
            with self.assertRaises(FileExistsError):
                self.upload()
        put.assert_not_called()

    def test_upload_uses_selected_branch_encoded_path_and_content(self):
        with patch.object(lp.requests, "get", return_value=Mock(status_code=404)) as get, \
                patch.object(lp.requests, "put", return_value=Mock(status_code=201)) as put:
            self.assertEqual(self.upload(), "literature/nested/已核验.md")
        self.assertEqual(get.call_args.kwargs["params"], {"ref": "papers"})
        self.assertIn("/literature/nested/%", put.call_args.args[0])
        self.assertEqual(put.call_args.kwargs["json"]["branch"], "papers")
        self.assertNotIn("sha", put.call_args.kwargs["json"])

    def test_api_errors_never_count_as_success(self):
        with patch.object(lp.requests, "get", return_value=Mock(status_code=404)), \
                patch.object(lp.requests, "put", return_value=Mock(status_code=403)):
            with self.assertRaisesRegex(RuntimeError, "403"):
                self.upload()

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            self.upload(name="../outside.md")
        with self.assertRaises(ValueError):
            lp.GitHubOptions("owner/repo", "key", folder="../outside").validate()

    def test_ocr_approval_requires_complete_positive_evidence(self):
        positive = {"llmReview": {"hasProblem": False}, "wordCountCheck": {"passed": True}}
        for raw, expected in (({}, False), (positive, True),
                ({**positive, "qualityWarning": "too short"}, False),
                ({**positive, "llmReviewError": "network failed"}, False),
                ({"parts": [{"rawResult": positive}, {"rawResult": {}}]}, False),
                ({"parts": [{"rawResult": positive}, {"rawResult": positive}]}, True)):
            with self.subTest(raw=raw):
                self.assertEqual(lp.ocr_verified(raw), expected)


if __name__ == "__main__":
    unittest.main()
