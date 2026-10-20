import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import literature_processing as lp
from model_budget import request_size, input_budget
from prompt_templates import MAX_PROMPT_CHARS, PROMPTS, normalize_overrides, resolve_prompt, snapshot


class PromptTemplateTests(unittest.TestCase):
    def test_all_editable_roles_keep_the_application_response_contract(self):
        self.assertEqual(len(PROMPTS), 14)
        for role in PROMPTS:
            with self.subTest(role=role):
                prompt = resolve_prompt(role, {role: "Custom instructions with {literal braces}."})
                self.assertTrue(prompt.startswith("Custom instructions with {literal braces}."))
                self.assertIn("应用程序输出要求", prompt)
                if role not in {"translation", "translation_second_pass", "markdown_format"}:
                    self.assertIn("JSON", prompt)

    def test_defaults_and_blank_edits_are_omitted_and_snapshots_are_detached(self):
        overrides = {"translation": "Keep all statements.", "proofreading": "", "ocr_review": PROMPTS["ocr_review"]}
        self.assertEqual(normalize_overrides(overrides), {"translation": "Keep all statements."})
        captured = snapshot(overrides)
        overrides["translation"] = "New preference"
        self.assertEqual(captured["translation"], "Keep all statements.")
        self.assertEqual(set(captured), set(PROMPTS))
        self.assertEqual(resolve_prompt("proofreading", captured), lp.PROOFREAD_PROMPT)
        self.assertEqual(resolve_prompt("proofreading", captured).count("应用程序输出要求"), 1)

    def test_invalid_override_data_is_rejected_before_it_can_reach_a_provider(self):
        for value in ([], {"unknown": "text"}, {"translation": False}, {"translation": "x" * (MAX_PROMPT_CHARS + 1)},
                      {"translation": "bad\x00text"}):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                snapshot(value)


class PromptPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "paper.md"
        self.source.write_text("# Evidence\n\nFirst paragraph.\n\nConclusion.", encoding="utf-8")
        self.destination = self.root / "paper_TRANSLATED.md"
        self.profile = lp.ModelProfile("https://example.invalid/v1", "key", "model")
        self.detect = '{"language":"English","is_target_language":false}'
        self.clean = '{"has_problem":false,"issues":[],"omissions":[],"mistranslations":[]}'

    def translate(self, replies, options=None, prompts=None):
        options = options or lp.TranslationOptions(proofreading=True)
        with patch.object(lp, "chat", side_effect=replies) as chat:
            result = lp.translate_document(self.source, self.destination, options, self.profile,
                reviewer=self.profile, proofreader=self.profile, arbiter=self.profile, prompts=prompts)
        return result, chat

    def test_language_translation_comparison_and_proofreading_use_the_same_captured_overrides(self):
        prompts = snapshot({role: "CUSTOM " + role for role in PROMPTS})
        result, chat = self.translate([self.detect, "初译", "独立重译", self.clean, self.clean],
            lp.TranslationOptions(secondary_review=True, proofreading=True), prompts)
        expected = ["language_detection", "translation", "translation_second_pass", "translation_compare", "proofreading"]
        self.assertEqual(chat.call_count, 5)
        self.assertTrue(result["verified"])
        for call, role in zip(chat.call_args_list, expected):
            self.assertEqual(call.args[1], resolve_prompt(role, prompts))
        self.assertNotIn("first", chat.call_args_list[2].args[2])

    def test_inconsistent_proofreading_approval_cannot_hide_missing_paragraph(self):
        result, chat = self.translate([self.detect, "省略结论的译文",
            '{"has_problem":false,"issues":["遗漏整段结论"]}'])
        self.assertFalse(result["verified"])
        self.assertEqual(chat.call_count, 3)
        review = result["checks"][0]["proofreading"]
        self.assertTrue(review["has_problem"])
        self.assertTrue(review["inconsistentApproval"])
        self.assertFalse(review["reportedHasProblem"])

    def test_two_translations_with_a_reported_shared_omission_cannot_be_approved(self):
        result, chat = self.translate([self.detect, "第一稿", "第二稿",
            '{"has_problem":false,"issues":[],"omissions":["两份都漏掉参考文献"]}'],
            lp.TranslationOptions(secondary_review=True))
        self.assertFalse(result["verified"])
        self.assertEqual(chat.call_count, 4)

    def test_arbiter_approval_with_explicit_remaining_omissions_stays_pending(self):
        result, chat = self.translate([self.detect, "译文", '{"has_problem":true,"issues":["待复核"]}',
            '{"decision":"approve","has_problem":false,"issues":[],"omissions":["Conclusion"]}'],
            lp.TranslationOptions(proofreading=True, arbitration="大模型裁决"))
        self.assertFalse(result["verified"])
        self.assertEqual(chat.call_count, 4)

    def test_revision_with_omissions_cannot_replace_the_original_draft(self):
        result, chat = self.translate([self.detect, "第一稿", '{"has_problem":true,"issues":["遗漏"]}',
            '{"decision":"revised","has_problem":false,"revised_translation":"仍不完整的修订"}',
            '{"has_problem":false,"issues":[],"omissions":["结论仍被省略"]}'],
            lp.TranslationOptions(proofreading=True, arbitration="大模型裁决", allow_arbiter_revision=True))
        self.assertFalse(result["verified"])
        self.assertEqual(self.destination.read_text(encoding="utf-8"), "第一稿\n")
        self.assertFalse(result["checks"][0]["revisions"][0]["accepted"])
        self.assertEqual(chat.call_count, 5)

    def test_malformed_problem_lists_are_not_positive_approval(self):
        for field in ("issues", "omissions", "mistranslations"):
            for value in ("missing", [False], {"paragraph": 2}):
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                    lp.review_reply(json.dumps({"has_problem": False, field: value}))

    def test_user_instructions_are_budgeted_together_with_the_fixed_contract(self):
        self.source.write_text("Evidence and citations.\n\n" * 180, encoding="utf-8")
        profile = lp.ModelProfile("https://example.invalid/v1", "key", "model", input_limit=10000)
        prompts = snapshot({"translation": "Detailed instruction. " * 60})
        translated_chunks = []
        def respond(model, instruction, data, *args, **kwargs):
            self.assertLessEqual(request_size(instruction, data), input_budget(model, 50))
            if "sample" in data:
                return self.detect
            translated_chunks.append(data["source"])
            return data["source"]
        with patch.object(lp, "chat", side_effect=respond):
            lp.translate_document(self.source, self.destination, lp.TranslationOptions(), profile, prompts=prompts)
        self.assertGreater(len(translated_chunks), 1)
        self.assertEqual("".join(translated_chunks), self.source.read_text(encoding="utf-8"))

    def test_markdown_overrides_retain_one_format_pass_and_cannot_hide_an_omission(self):
        prompts = snapshot({"markdown_format": "Keep each original paragraph.", "markdown_verify": "Check every paragraph."})
        with patch.object(lp, "chat", side_effect=[self.source.read_text(encoding="utf-8"),
                '{"has_problem":false,"issues":[],"omissions":["Final paragraph not checked"]}']) as chat:
            result = lp.format_markdown_document(self.source, self.destination, self.profile, self.profile, prompts=prompts)
        self.assertFalse(result["verified"])
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args_list[0].args[1], resolve_prompt("markdown_format", prompts))
        self.assertEqual(chat.call_args_list[1].args[1], resolve_prompt("markdown_verify", prompts))


if __name__ == "__main__":
    unittest.main()
