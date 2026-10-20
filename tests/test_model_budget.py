import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp
from model_budget import (BudgetExceeded, ModelCatalog, ResponseTooLong, budget_chunks,
                          effective_limits, input_budget, messages, prepare_request,
                          read_limits, request_size)


class BudgetTests(unittest.TestCase):
    def profile(self, **limits):
        return lp.ModelProfile("https://example.invalid/v1", "secret", "model", **limits)

    def test_standard_model_object_uses_documented_fallback(self):
        catalog = ModelCatalog([{"id": "small"}, {"id": "large", "context_length": 131072}])
        self.assertEqual(catalog, ["large", "small"])
        self.assertNotIn("small", catalog.limits)
        limits = effective_limits(self.profile())
        self.assertEqual((limits.context_limit, limits.output_limit), (1_000_000, 256_000))
        self.assertEqual(input_budget(self.profile()), 500000 - 256)

    def test_reads_explicit_input_context_output_fields_and_nested_provider_limits(self):
        limits = read_limits({"max_input_tokens": 96000, "context_length": 128000,
                              "top_provider": {"context_length": 100000, "max_completion_tokens": 16000}})
        self.assertEqual((limits.input_limit, limits.context_limit, limits.output_limit), (96000, 100000, 16000))
        self.assertIsNone(read_limits({"max_tokens": 8192, "max_input_tokens": True}))
        self.assertIsNone(read_limits({"max_input_tokens": -10, "context_window": 1.25}))

    def test_output_only_metadata_preserves_cap_with_fallback_input_budget(self):
        catalog = ModelCatalog([{"id": "limited-output", "max_output_tokens": 8000}])
        metadata = catalog.limits["limited-output"]
        self.assertEqual(metadata.output_limit, 8000)
        profile = self.profile(output_limit=metadata.output_limit)
        limits = effective_limits(profile)
        self.assertEqual(limits.context_limit, 1_000_000)
        self.assertEqual(limits.output_limit, 8000)
        response = Mock(ok=True)
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
        with patch.object(lp.requests, "post", return_value=response) as post:
            lp.chat(profile, "translate", {"source": "paper"})
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 8000)

    def test_malformed_oversized_limit_does_not_break_other_model_metadata(self):
        maximum_digits = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        if not maximum_digits:
            self.skipTest("Interpreter does not limit integer-string conversion")
        limits = read_limits({"context_length": "9" * (maximum_digits + 1), "max_output_tokens": 8000})
        self.assertEqual(limits.context_limit, 0)
        self.assertEqual(limits.output_limit, 8000)

    def test_percentage_changes_budget_and_preserves_output_reserve(self):
        profile = self.profile(input_limit=10000, context_limit=11000, output_limit=4000)
        self.assertEqual(input_budget(profile, 50), 4744)
        self.assertEqual(input_budget(profile, 80), 6744)
        for invalid in (49, 81, 50.5, "60", True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                input_budget(profile, invalid)

    def test_unicode_and_json_escaping_are_budgeted_not_character_ratios(self):
        plain = request_size("translate", {"source": "A" * 100})
        self.assertGreater(request_size("translate", {"source": "中" * 100}), plain + 150)
        self.assertGreater(request_size("translate", {"source": '"' * 100}), plain)

    def test_prepared_request_serializes_multilingual_data_only_once(self):
        data = {"source": ('中文 / العربية / 😀 / "quoted" / \n\t' * 1000)}
        with patch("model_budget.json.dumps", wraps=json.dumps) as serialize:
            payload, size = prepare_request(self.profile(), "translate", data)
        serialize.assert_called_once()
        self.assertEqual(payload, messages("translate", data))
        self.assertEqual(size, request_size("translate", data))
        self.assertEqual(size, sum(len(item["content"].encode("utf-8")) for item in payload) + 128)
        with self.assertRaises(BudgetExceeded):
            prepare_request(self.profile(input_limit=100), "translate", data)

    def test_chunking_fills_budget_without_losing_markdown_or_unicode(self):
        text = ("# Heading\n\n" + "Citations [1]. 中文。\n\n" * 20 + "```python\nprint('x')\n```\n\n") * 15
        fits = lambda value: request_size("translate", {"source": value}) <= 1600
        chunks = budget_chunks(text, fits)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(fits(chunk) for chunk in chunks))
        self.assertTrue(all(chunk.endswith("\n\n") for chunk in chunks[:-1]))
        self.assertEqual(budget_chunks("a" * 10000, lambda value: len(value) <= 3000),
                         ["a" * 3000] * 3 + ["a" * 1000])

    def test_long_document_with_small_budget_does_not_rescan_remaining_document(self):
        text = "A" * 200000
        inspected = 0
        def fits(value):
            nonlocal inspected
            inspected += len(value)
            return len(value) <= 1000
        chunks = budget_chunks(text, fits)
        self.assertEqual(chunks, ["A" * 1000] * 200)
        # Bound work directly rather than depending on CI CPU timing.
        self.assertLess(inspected, len(text) * 20)

    def test_fitting_fences_are_not_split_after_a_short_introduction(self):
        blocks = [
            "```python\n" + "print('text')\n" * 6 + "```\n",
            "~~~python\n" + "中文 = '😀'\n" * 6 + "~~~~\n",
            "````text\n```not a closing fence\n\n" + "source\n" * 6 + "````\n",
            "```python\r\n" + "print('text')\r\n" * 6 + "```\r\n",
        ]
        for block in blocks:
            with self.subTest(block=block[:20]):
                text = "Introduction.\n\n" + block + "\n" + "Conclusion.\n" * 15
                budget = len(block.encode("utf-8")) + 4
                fits = lambda value: len(value.encode("utf-8")) <= budget
                chunks = budget_chunks(text, fits)
                self.assertEqual("".join(chunks), text)
                self.assertTrue(all(fits(chunk) for chunk in chunks))
                self.assertTrue(any(block in chunk for chunk in chunks))

    def test_a_single_oversized_fence_still_splits_without_losing_content(self):
        text = "```text\n" + "中文😀 data\n" * 100 + "```\n"
        fits = lambda value: len(value.encode("utf-8")) <= 100
        chunks = budget_chunks(text, fits)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(fits(chunk) for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_tiny_budget_fails_before_sending_an_oversized_request(self):
        with self.assertRaises(BudgetExceeded), patch.object(lp.requests, "post") as post:
            lp.chat(self.profile(input_limit=100), "long prompt", {"source": "paper"})
        post.assert_not_called()

    def test_fetch_models_preserves_ids_and_actual_provider_limits(self):
        import paddleocr_pdf_to_md_gui as app
        response = Mock(ok=True)
        response.json.return_value = {"data": [{"id": "model", "max_input_tokens": 32000, "max_output_tokens": 8000}]}
        with patch.object(app.requests, "get", return_value=response):
            catalog = app.fetch_openai_compatible_models("https://example.invalid/v1", "secret")
        self.assertEqual(catalog, ["model"])
        self.assertEqual(catalog.limits["model"].input_limit, 32000)

    def test_known_output_cap_is_sent_so_large_translations_do_not_use_a_small_server_default(self):
        response = Mock(ok=True)
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
        for profile, cap in ((lp.ModelProfile("https://api.deepseek.com/v1", "secret", "deepseek-flash"), 256000),
                             (self.profile(input_limit=32000, output_limit=8000), 8000)):
            with self.subTest(model=profile.model), patch.object(lp.requests, "post", return_value=response) as post:
                lp.chat(profile, "translate", {"source": "paper"})
            self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], cap)

    def run_document(self, text, options, profiles, responder):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / "paper.md", Path(folder) / "paper_TRANSLATED.md"
            source.write_text(text, encoding="utf-8")
            with patch.object(lp, "chat", side_effect=responder) as chat:
                report = lp.translate_document(source, destination, options, **profiles)
            return report, chat.call_args_list, destination.read_text(encoding="utf-8")

    def test_normal_paper_larger_than_old_4000_char_limit_stays_in_one_chunk(self):
        text = "A full paragraph. " * 1500
        def responder(profile, prompt, data, *args, **kwargs):
            return json.dumps({"language": "English", "is_target_language": False}) if "sample" in data else data["source"]
        report, calls, output = self.run_document(text, lp.TranslationOptions(), {"translator": self.profile()}, responder)
        self.assertEqual(len(report["checks"]), 1)
        self.assertEqual(output.rstrip(), text.rstrip())
        self.assertEqual(len(calls), 2)
        self.assertNotIn("secret", json.dumps(report))

    def test_smaller_review_model_limits_all_stages_and_preserves_every_source_character(self):
        translator = self.profile(input_limit=80000)
        reviewer = replace(translator, model="reviewer", input_limit=16000)
        arbiter = replace(translator, model="arbiter", input_limit=24000)
        proofreader = replace(translator, model="proofreader", input_limit=16000)
        options = lp.TranslationOptions(secondary_review=True, proofreading=True, arbitration="大模型裁决", input_percent=65)
        def responder(profile, prompt, data, *args, **kwargs):
            self.assertLessEqual(request_size(prompt, data), input_budget(profile, options.input_percent))
            if "sample" in data:
                return '{"language":"English","is_target_language":false}'
            if prompt == lp.COMPARE_PROMPT:
                return '{"has_problem":true,"issues":["review"]}'
            if prompt == lp.ARBITRATE_PROMPT:
                return '{"has_problem":false,"choice":"first"}'
            if prompt == lp.PROOFREAD_PROMPT:
                return '{"has_problem":false}'
            return data["source"]
        text = "Evidence and citations [1].\n\n" * 600
        report, calls, _ = self.run_document(text, options, dict(translator=translator, reviewer=reviewer,
                               arbiter=arbiter, proofreader=proofreader), responder)
        self.assertTrue(report["verified"])
        originals = [call.args[2]["source"] for call in calls if call.args[0].model == "model" and "source" in call.args[2]]
        self.assertEqual("".join(originals), text)
        self.assertGreater(len(report["checks"]), 1)

    def test_proofreading_only_decision_respects_a_smaller_arbiter_budget(self):
        translator = self.profile(input_limit=80000)
        proofreader = replace(translator, model="proofreader")
        arbiter = replace(translator, model="arbiter", input_limit=12000)
        options = lp.TranslationOptions(proofreading=True, arbitration="大模型裁决")
        def responder(profile, prompt, data, *args, **kwargs):
            self.assertLessEqual(request_size(prompt, data), input_budget(profile))
            if "sample" in data:
                return '{"language":"English","is_target_language":false}'
            if prompt == lp.TRANSLATE_PROMPT:
                return data["source"]
            if prompt == lp.PROOFREAD_PROMPT:
                return '{"has_problem":true,"issues":["suspected missing word"]}'
            self.assertEqual(profile.model, "arbiter")
            self.assertEqual(prompt, lp.PROOF_ARBITRATE_PROMPT)
            return '{"decision":"approve","has_problem":false}'
        text = "Evidence and conclusions.\n\n" * 500
        report, calls, _ = self.run_document(text, options, dict(translator=translator,
                                proofreader=proofreader, arbiter=arbiter), responder)
        self.assertTrue(report["verified"])
        self.assertGreater(len(report["checks"]), 1)
        originals = [call.args[2]["source"] for call in calls if call.args[1] == lp.TRANSLATE_PROMPT]
        self.assertEqual("".join(originals), text)

    def test_expanded_translation_is_retranslated_in_smaller_source_chunks(self):
        profile = self.profile(input_limit=20000)
        options = lp.TranslationOptions(proofreading=True)
        def responder(profile, prompt, data, *args, **kwargs):
            if "sample" in data:
                return '{"language":"English","is_target_language":false}'
            if prompt == lp.TRANSLATE_PROMPT:
                return data["source"] * 6
            self.assertLessEqual(request_size(prompt, data), input_budget(profile))
            return '{"has_problem":false}'
        text = "A" * 2000
        report, calls, output = self.run_document(text, options, dict(translator=profile, proofreader=profile), responder)
        self.assertTrue(report["verified"])
        self.assertEqual(len(report["checks"]), 2)
        self.assertEqual(output.replace("\n", ""), text * 6)
        self.assertEqual(sum(call.args[1] == lp.TRANSLATE_PROMPT for call in calls), 3)

    def test_truncated_response_retries_and_never_saves_partial_translation(self):
        attempts = 0
        def responder(profile, prompt, data, *args, **kwargs):
            nonlocal attempts
            if "sample" in data:
                return '{"language":"English","is_target_language":false}'
            attempts += 1
            if attempts == 1:
                raise ResponseTooLong("truncated")
            return data["source"]
        report, _, output = self.run_document("A" * 8000, lp.TranslationOptions(), {"translator": self.profile()}, responder)
        self.assertEqual(len(report["checks"]), 2)
        self.assertEqual(output.replace("\n", ""), "A" * 8000)


if __name__ == "__main__":
    unittest.main()
