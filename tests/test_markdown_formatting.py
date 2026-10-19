import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp
from model_budget import ResponseTooLong, input_budget, request_size

OK = '{"has_problem":false,"issues":[],"summary":"Passed"}'
BAD = '{"has_problem":true,"issues":["Check heading levels"],"summary":"Review needed"}'


class FormattingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'paper.md'
        self.source.write_text('Title\n\nRead 12 papers.\n', encoding='utf-8')
        self.destination = self.root / 'paper_FORMATTED.md'
        self.formatter = lp.ModelProfile('https://example.invalid/v1', 'key', 'format')
        self.verifier = lp.ModelProfile('https://example.invalid/v1', 'key', 'verify')

    def run_format(self, answers, **kwargs):
        with patch.object(lp, 'chat', side_effect=answers) as chat:
            report = lp.format_markdown_document(self.source, self.destination, self.formatter, self.verifier, **kwargs)
        return report, chat

    def test_one_format_call_then_json_only_verification_preserves_source_and_hashes(self):
        original = self.source.read_bytes()
        report, chat = self.run_format(['# Title\n\nRead **12** papers.', OK])
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args_list[0].args[0].model, 'format')
        self.assertEqual(chat.call_args_list[1].args[0].model, 'verify')
        self.assertEqual(chat.call_args_list[1].args[1], lp.FORMAT_VERIFY_PROMPT)
        self.assertEqual(set(chat.call_args_list[1].args[2]), {'source', 'formatted'})
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['formattingPasses'], 1)
        self.assertTrue(report['verificationOnly'])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(report['outputSHA256'], hashlib.sha256(self.destination.read_bytes()).hexdigest())
        self.assertEqual(report['sourceSHA256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(json.loads(self.destination.with_suffix('.formatting.json').read_text())['checks'], report['checks'])
        self.assertEqual(lp.document_upload_evidence(self.destination)[1], 'unverified')

    def test_failed_or_malformed_review_keeps_first_draft_pending_without_reformatting(self):
        for reply in (BAD, 'not JSON', '{"has_problem":"false"}', '{"has_problem":false}',
                      '{"has_problem":false,"issues":["Missing text"]}'):
            with self.subTest(reply=reply):
                self.destination.unlink(missing_ok=True)
                self.destination.with_suffix('.formatting.json').unlink(missing_ok=True)
                decide = Mock(return_value='first')
                report, chat = self.run_format(['# Title\n\nRead 12 papers.', reply], decide=decide)
                self.assertFalse(report['verified'])
                self.assertEqual(report['status'], 'needs_review')
                self.assertEqual(chat.call_count, 2)
                self.assertNotIn('second', decide.call_args.args[0])
                self.assertTrue(self.destination.exists())

    def test_changed_content_is_blocked_even_when_llm_approves(self):
        cases = [
            ('Read 1.0 papers.', 'Read 10 papers.', '数字'),
            ('Read 12 papers.', 'Read 12 new papers.', '文字'),
            ('[link](../paper.pdf)', '[link](../other.pdf)', '链接'),
            ('```py\nx = 1\n```\n', '```py\nx=1\n```', '代码块'),
            ('Use `some_value`.', 'Use `somevalue`.', '行内代码'),
            ('Use $x + y$.', 'Use $x+y$.', '公式'),
        ]
        for source, candidate, reason in cases:
            with self.subTest(reason=reason):
                self.destination.unlink(missing_ok=True)
                self.destination.with_suffix('.formatting.json').unlink(missing_ok=True)
                self.source.write_text(source)
                report, _ = self.run_format([candidate, OK])
                self.assertFalse(report['verified'])
                self.assertTrue(any(reason in issue for issue in report['contentIssues']))

    def test_windows_newlines_do_not_change_code_content(self):
        self.source.write_bytes(b'Title\r\n\r\n```py\r\nx = 1\r\n```\r\n')
        report, _ = self.run_format(['# Title\n\n```py\nx = 1\n```', OK])
        self.assertTrue(report['verified'])

    def test_only_explicit_retry_discards_draft_and_runs_a_new_attempt(self):
        decide = Mock(return_value='retry')
        report, chat = self.run_format(['## Title\n\nRead 12 papers.', BAD, '# Title\n\nRead 12 papers.', OK], decide=decide)
        self.assertEqual(chat.call_count, 4)
        decide.assert_called_once()
        self.assertEqual(report['userRetries'], 1)
        self.assertEqual(report['formattingPasses'], 2)
        self.assertEqual(len(report['checks'][0]['priorAttempts']), 1)
        self.assertEqual(self.destination.read_text(), '# Title\n\nRead 12 papers.\n')

    def test_network_failure_in_verification_does_not_generate_another_draft(self):
        report, chat = self.run_format(['# Title\n\nRead 12 papers.', RuntimeError('HTTP 429')], decide=lambda payload: 'first')
        self.assertEqual(chat.call_count, 2)
        self.assertFalse(report['verified'])
        self.assertIn('429', report['checks'][0]['reviewError'])

    def test_protected_blocks_and_tables_are_whole_and_no_source_text_is_lost(self):
        text = 'A paragraph.\n\n' * 15 + '```py\nx = 1\n```\n\n' + '| A | B |\n| --- | --- |\n| 1 | 2 |\n\n' + '$$x + y$$\n\n' + 'End.\n' * 10
        chunks = lp.formatting_chunks(text, lambda item: len(item) <= 100)
        self.assertEqual(''.join(chunks), text)
        for protected in ('```py\nx = 1\n```', '| A | B |\n| --- | --- |\n| 1 | 2 |', '$$x + y$$'):
            self.assertTrue(any(protected in chunk for chunk in chunks))
        self.assertTrue(all(len(c) <= 100 for c in chunks))

    def test_oversize_atomic_block_fails_before_any_model_request(self):
        self.source.write_text('```\n' + 'x' * 9000 + '\n```\n')
        small = lp.ModelProfile('https://example.invalid/v1', 'key', 'small', input_limit=4000, limit_source='manual')
        with patch.object(lp, 'chat') as chat, self.assertRaisesRegex(ValueError, '代码块'):
            lp.format_markdown_document(self.source, self.destination, self.formatter, small)
        chat.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_model_budgets_include_source_and_formatted_text_and_are_checked_each_call(self):
        self.source.write_text('A research paragraph about institutions.\n\n' * 180)
        small = lp.ModelProfile('https://example.invalid/v1', 'key', 'small', input_limit=10000, limit_source='manual')
        calls = []
        def chat(profile, prompt, data, stop, input_percent):
            self.assertLessEqual(request_size(prompt, data), input_budget(profile, input_percent))
            calls.append((prompt, data))
            return data['source'].strip() if prompt == lp.FORMAT_PROMPT else OK
        with patch.object(lp, 'chat', side_effect=chat):
            report = lp.format_markdown_document(self.source, self.destination, self.formatter, small, input_percent=60)
        self.assertTrue(report['verified'])
        self.assertGreater(len(report['checks']), 1)
        self.assertEqual(len(calls), len(report['checks']) * 2)
        self.assertEqual(''.join(data['source'] for prompt, data in calls if prompt == lp.FORMAT_PROMPT), self.source.read_text())

    def test_cancel_and_truncated_formatting_never_write_partial_outputs_or_auto_retry(self):
        with patch.object(lp, 'chat') as chat, self.assertRaises(lp.ProcessingCancelled):
            lp.format_markdown_document(self.source, self.destination, self.formatter, self.verifier, stop=lambda: True)
        chat.assert_not_called()
        with patch.object(lp, 'chat', side_effect=ResponseTooLong('length')) as chat, self.assertRaises(ResponseTooLong):
            lp.format_markdown_document(self.source, self.destination, self.formatter, self.verifier)
        self.assertEqual(chat.call_count, 1)
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.with_suffix('.formatting.json').exists())

    def test_existing_files_and_reports_are_not_overwritten(self):
        for path in (self.destination, self.destination.with_suffix('.formatting.json')):
            path.write_text('existing')
            with patch.object(lp, 'chat') as chat:
                report = lp.format_markdown_document(self.source, self.destination, self.formatter, self.verifier)
            self.assertEqual(report['status'], 'existing')
            self.assertEqual(path.read_text(), 'existing')
            chat.assert_not_called()
            path.unlink()
        with self.assertRaises(ValueError):
            lp.format_markdown_document(self.source, self.source, self.formatter, self.verifier)

    def test_folder_scan_accepts_translations_but_skips_formatted_outputs_and_output_subtree(self):
        (self.root / 'paper_TRANSLATED.md').write_text('translation')
        (self.root / 'paper_FORMATTED.md').write_text('formatted')
        out = self.root / 'output'; out.mkdir()
        (out / 'other.md').write_text('output')
        paths = lp.find_formatting_files(self.root, output_root=out)
        self.assertEqual([p.name for p in paths], ['paper.md', 'paper_TRANSLATED.md'])
        self.assertEqual(lp.formatted_path(self.source, self.root).name, 'paper_FORMATTED.md')
        self.assertEqual(lp.formatted_path(self.source, self.root, out, True), out / 'FORMATTED_paper.md')

    def test_verified_translation_role_and_upstream_evidence_survive_formatting(self):
        translated = self.root / 'paper_TRANSLATED.md'
        self.source.rename(translated); self.source = translated
        translated.with_suffix('.translation.json').write_text(json.dumps({'verified': True, 'status': 'verified',
            'outputSHA256': hashlib.sha256(translated.read_bytes()).hexdigest()}))
        report, _ = self.run_format(['# Title\n\nRead 12 papers.', OK])
        self.assertEqual(report['documentRole'], 'translation')
        self.assertTrue(report['upstreamVerified'])
        self.assertEqual(lp.document_upload_evidence(self.destination)[:2], ('translation', 'ready'))
        options = lp.GitHubOptions('owner/repo', 'token')
        client = Mock(remote_paths=Mock(return_value=set()))
        scanned = lp.scan_missing_documents(self.root, '仅上传翻译稿', options, client=client)
        self.assertIn(self.destination, [c.path for c in scanned])


class TranslationProblemChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source.md'
        self.source.write_text('English original.\n')
        self.destination = self.source.with_name('source_TRANSLATED.md')
        self.model = lp.ModelProfile('https://example.invalid/v1', 'key', 'model')
        self.detection = '{"language":"English","is_target_language":false}'

    def test_comparison_retry_replaces_current_drafts_only_and_keeps_language_detection(self):
        replies = [self.detection, '旧初稿', '旧二稿', BAD, '新初稿', '新二稿', OK]
        with patch.object(lp, 'chat', side_effect=replies) as chat:
            result = lp.translate_document(self.source, self.destination, lp.TranslationOptions(secondary_review=True),
                self.model, reviewer=self.model, decide=lambda payload: 'retry')
        self.assertEqual(chat.call_count, 7)
        self.assertTrue(result['verified'])
        self.assertEqual(self.destination.read_text(), '新初稿\n')
        self.assertNotIn('旧初稿', self.destination.with_suffix('.translation.json').read_text())
        self.assertEqual(self.source.read_text(), 'English original.\n')

    def test_proofreading_issue_with_only_one_draft_keeps_it_pending(self):
        decide = Mock(return_value='first')
        with patch.object(lp, 'chat', side_effect=[self.detection, '初稿', BAD]) as chat:
            result = lp.translate_document(self.source, self.destination, lp.TranslationOptions(proofreading=True),
                self.model, proofreader=self.model, decide=decide)
        self.assertEqual(chat.call_count, 3)
        self.assertNotIn('second', decide.call_args.args[0])
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(self.destination.read_text(), '初稿\n')

    def test_comparison_api_failure_can_keep_second_draft_without_marking_it_verified(self):
        decide = Mock(return_value='second')
        with patch.object(lp, 'chat', side_effect=[self.detection, '初稿', '二稿', RuntimeError('HTTP 429')]):
            result = lp.translate_document(self.source, self.destination, lp.TranslationOptions(secondary_review=True),
                self.model, reviewer=self.model, decide=decide)
        self.assertIn('429', decide.call_args.args[0]['problem'])
        self.assertEqual(decide.call_args.args[0]['second'], '二稿')
        self.assertFalse(result['verified'])
        self.assertEqual(result['pendingReasons'], ['translation_check_failed'])
        self.assertEqual(self.destination.read_text(), '二稿\n')

    def test_automatic_model_decision_runs_before_fallback_problem_choices(self):
        decide = Mock(return_value='first')
        with patch.object(lp, 'chat', side_effect=[self.detection, '初稿', '二稿', BAD,
                '{"choice":"unresolved","has_problem":true,"reason":"Cannot resolve"}']) as chat:
            result = lp.translate_document(self.source, self.destination,
                lp.TranslationOptions(secondary_review=True, arbitration='大模型裁决'), self.model,
                reviewer=self.model, arbiter=self.model, decide=decide)
        self.assertEqual(chat.call_args_list[-1].args[1], lp.ARBITRATE_PROMPT)
        self.assertIn('arbitration', decide.call_args.args[0]['problem'])
        self.assertEqual(result['status'], 'needs_review')

    def test_cancel_after_retry_does_not_write_current_file(self):
        cancelled = False
        def decide(payload):
            nonlocal cancelled
            cancelled = True
            return 'retry'
        with patch.object(lp, 'chat', side_effect=[self.detection, '初稿', '二稿', BAD]), self.assertRaises(lp.ProcessingCancelled):
            lp.translate_document(self.source, self.destination, lp.TranslationOptions(secondary_review=True),
                self.model, reviewer=self.model, decide=decide, stop=lambda: cancelled)
        self.assertFalse(self.destination.exists())
        self.assertTrue(self.source.exists())

if __name__ == '__main__':
    unittest.main()
