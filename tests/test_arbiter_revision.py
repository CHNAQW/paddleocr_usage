import hashlib
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp
from literature_ui import LiteratureControls
from model_budget import input_budget, request_size


class ArbiterRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'paper.md'
        self.source.write_text('# Paper\n\nThe institution opened in 1999.', encoding='utf-8')
        self.output = self.root / 'paper_TRANSLATED.md'
        self.models = {role: lp.ModelProfile('https://example.invalid/v1', 'test-key', role)
                       for role in ('translator', 'reviewer', 'proofreader', 'arbiter')}
        self.detect = '{"language":"English","is_target_language":false}'
        self.problem = '{"has_problem":true,"issues":["wrong year"]}'
        self.clean = '{"has_problem":false,"issues":[]}'

    def options(self, **kwargs):
        return lp.TranslationOptions(**{'secondary_review': True, 'arbitration': '大模型裁决',
                                        'allow_arbiter_revision': True, **kwargs})

    def verdict(self, candidate='完整修订译文 1999', stage='translation', **changes):
        return json.dumps({('choice' if stage == 'translation' else 'decision'): 'revised',
                           'has_problem': False, 'reason': 'Fixed the year', 'revised_translation': candidate, **changes})

    def run_translation(self, responses, options=None, decide=None):
        with patch.object(lp, 'chat', side_effect=[self.detect] + responses) as chat:
            result = lp.translate_document(self.source, self.output, options or self.options(),
                **self.models, decide=decide)
        return result, chat

    def test_default_permission_does_not_apply_a_model_requested_rewrite(self):
        decide = Mock(return_value='unresolved')
        result, chat = self.run_translation(['first', 'second', self.problem, self.verdict()],
            self.options(allow_arbiter_revision=False), decide)
        self.assertFalse(result['arbiterRevisionAuthorized'])
        self.assertFalse(result['verified'])
        self.assertEqual(self.output.read_text(), 'first\n')
        self.assertEqual(chat.call_args_list[-1].args[1], lp.ARBITRATE_PROMPT)
        decide.assert_called_once()

    def test_authorized_revision_is_checked_applied_and_audited_without_user_action(self):
        original = self.source.read_bytes()
        decide = Mock(side_effect=AssertionError('A checked automatic revision must not ask again'))
        result, chat = self.run_translation(['wrong 1998', 'wrong 2000', self.problem, self.verdict(), self.clean], decide=decide)
        self.assertTrue(result['verified'])
        self.assertTrue(result['arbiterRevisionAuthorized'])
        self.assertEqual(result['checks'][0]['arbitrationChoice'], 'revised')
        revision = result['checks'][0]['revisions'][0]
        self.assertEqual(revision['before'], 'wrong 1998')
        self.assertTrue(revision['accepted'])
        self.assertEqual(revision['verifier'], 'reviewer')
        self.assertEqual(chat.call_args_list[-1].args[1], lp.REVISION_VERIFY_PROMPT)
        self.assertEqual(chat.call_args_list[-1].args[0], self.models['reviewer'])
        self.assertEqual(self.output.read_text(), '完整修订译文 1999\n')
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(result['outputSHA256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertNotIn('test-key', self.output.with_suffix('.translation.json').read_text())
        decide.assert_not_called()

    def test_proofreading_only_can_revise_and_verify_without_a_second_translation(self):
        decide = Mock(side_effect=AssertionError('No manual confirmation expected'))
        result, chat = self.run_translation(['wrong 1998', self.problem,
            self.verdict(stage='proofreading'), self.clean],
            self.options(secondary_review=False, proofreading=True), decide)
        self.assertTrue(result['verified'])
        self.assertEqual(result['checks'][0]['revisions'][0]['stage'], 'proofreading')
        self.assertEqual(chat.call_args_list[-1].args[0], self.models['proofreader'])
        self.assertEqual(chat.call_count, 5)
        decide.assert_not_called()

    def test_both_stages_can_revise_without_losing_either_audit_record(self):
        result, _ = self.run_translation(['first', 'second', self.problem, self.verdict('修订一'), self.clean,
            self.problem, self.verdict('修订二', stage='proofreading'), self.clean],
            self.options(proofreading=True), Mock(side_effect=AssertionError('Unexpected decision')))
        self.assertTrue(result['verified'])
        self.assertEqual([item['stage'] for item in result['checks'][0]['revisions']], ['translation', 'proofreading'])
        self.assertEqual(result['checks'][0]['revisions'][1]['before'], '修订一')
        self.assertEqual(self.output.read_text(), '修订二\n')

    def test_user_mode_does_not_gain_revision_authority_from_a_remembered_checkbox(self):
        decide = Mock(return_value='second')
        result, chat = self.run_translation(['first', 'second', self.problem],
            self.options(arbitration='用户自行裁决'), decide)
        self.assertFalse(result['arbiterRevisionAuthorized'])
        self.assertEqual(chat.call_count, 4)
        self.assertFalse(result['verified'])
        self.assertEqual(self.output.read_text(), 'second\n')

    def test_empty_or_non_text_revisions_cannot_replace_the_current_draft(self):
        for candidate in ('', '  ', None, {'body': 'invalid'}):
            with self.subTest(candidate=candidate):
                self.output.unlink(missing_ok=True)
                result, chat = self.run_translation(['first', 'second', self.problem, self.verdict(candidate)],
                                                     decide=Mock(return_value='first'))
                self.assertFalse(result['verified'])
                self.assertEqual(self.output.read_text(), 'first\n')
                self.assertEqual(chat.call_count, 5)
                self.assertFalse(result['checks'][0]['revisions'][0]['accepted'])

    def test_failed_verification_keeps_revision_available_but_pending(self):
        for check in (self.problem, '{"has_problem":false,"issues":["missing citation"]}'):
            with self.subTest(check=check):
                self.output.unlink(missing_ok=True)
                decide = Mock(return_value='first')
                result, _ = self.run_translation(['first', 'second', self.problem, self.verdict(), check], decide=decide)
                self.assertFalse(result['verified'])
                self.assertEqual(self.output.read_text(), 'first\n')
                self.assertEqual(decide.call_args.args[0]['second'], '完整修订译文 1999')
                self.assertFalse(result['checks'][0]['revisions'][0]['accepted'])

    def test_malformed_verification_is_never_a_quality_approval(self):
        for check in ('{"has_problem":false}', '{"has_problem":false,"issues":"none"}', '{"has_problem":"false","issues":[]}'):
            with self.subTest(check=check):
                self.output.unlink(missing_ok=True)
                result, _ = self.run_translation(['first', 'second', self.problem, self.verdict(), check],
                                                 decide=Mock(return_value='first'))
                self.assertFalse(result['verified'])
                self.assertIn('error', result['checks'][0]['revisions'][0])

    def test_failed_verification_can_be_kept_by_the_user_without_upload_approval(self):
        result, _ = self.run_translation(['first', 'second', self.problem, self.verdict(), RuntimeError('offline')],
                                         decide=Mock(return_value='second'))
        self.assertEqual(self.output.read_text(), '完整修订译文 1999\n')
        self.assertEqual(result['status'], 'needs_review')
        self.assertFalse(result['verified'])
        self.assertEqual(result['checks'][0]['revisions'][0]['error'], 'offline')

    def test_cancel_during_revision_verification_writes_no_document(self):
        with self.assertRaises(lp.ProcessingCancelled):
            self.run_translation(['first', 'second', self.problem, self.verdict(), lp.ProcessingCancelled('stop')],
                                 decide=Mock(side_effect=AssertionError('Cancelled operation asked for input')))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.translation.json').exists())

    def test_authorization_still_allows_selecting_a_good_existing_draft(self):
        result, chat = self.run_translation(['first', 'second', self.problem, '{"choice":"second","has_problem":false}'])
        self.assertTrue(result['verified'])
        self.assertNotIn('revisions', result['checks'][0])
        self.assertEqual(chat.call_count, 5)
        self.assertEqual(self.output.read_text(), 'second\n')

    def test_a_model_that_admits_remaining_errors_cannot_apply_a_rewrite(self):
        result, chat = self.run_translation(['first', 'second', self.problem, self.verdict(has_problem=True)])
        self.assertFalse(result['verified'])
        self.assertEqual(self.output.read_text(), 'first\n')
        self.assertEqual(chat.call_count, 5)

    def test_revision_requests_respect_the_smallest_enabled_model_budget(self):
        self.source.write_text('A' * 2400)
        self.models['reviewer'] = lp.ModelProfile('https://example.invalid/v1', 'key', 'reviewer', input_limit=8000)
        calls = []
        def chat(profile, prompt, data, stop, input_percent=50):
            self.assertLessEqual(request_size(prompt, data), input_budget(profile, input_percent))
            calls.append((prompt, data))
            if 'sample' in data:
                return self.detect
            if prompt == lp.TRANSLATE_PROMPT:
                return 'draft'
            if prompt == lp.COMPARE_PROMPT:
                return self.problem
            if prompt == lp.ARBITRATE_REVISE_PROMPT:
                return self.verdict(data['source'])
            return self.clean
        with patch.object(lp, 'chat', side_effect=chat):
            result = lp.translate_document(self.source, self.output, self.options(), **self.models)
        self.assertTrue(result['verified'])
        self.assertGreater(len(result['checks']), 1)
        self.assertEqual(''.join(data['source'] for prompt, data in calls if prompt == lp.ARBITRATE_REVISE_PROMPT), 'A' * 2400)

    def test_post_ocr_uses_captured_permission_and_uploads_only_checked_revision(self):
        controls = object.__new__(LiteratureControls)
        controls.snapshot = {'auto_translate': True, 'output': None, 'prefix': False, 'profiles': self.models,
                            'options': self.options(secondary_review=False, proofreading=True), 'github': None}
        controls.stopped = Mock(return_value=False)
        controls.events = queue.Queue()
        controls.log = Mock()
        controls.maybe_upload = Mock()
        controls.decide = Mock(side_effect=AssertionError('Post-OCR revision asked for confirmation'))
        with patch.object(lp, 'chat', side_effect=[self.detect, 'wrong 1998', self.problem,
                          self.verdict(stage='proofreading'), self.clean]):
            controls.after_ocr(self.source, self.root, {'llmReview': {'hasProblem': False}}, self.source.read_text())
        report = json.loads(self.output.with_suffix('.translation.json').read_text())
        self.assertTrue(report['verified'])
        self.assertTrue(report['arbiterRevisionAuthorized'])
        self.assertTrue(controls.maybe_upload.call_args.args[2])
        self.assertEqual(self.output.read_text(), '完整修订译文 1999\n')
        controls.decide.assert_not_called()
