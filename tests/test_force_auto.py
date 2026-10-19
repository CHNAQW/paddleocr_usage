import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import literature_processing as lp
from literature_ui import LiteratureControls


class AutomaticProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'paper.md'
        self.source.write_text('# Paper\n\nThe institution opened in 1999.', encoding='utf-8')
        self.output = self.root / 'paper_TRANSLATED.md'
        self.models = {role: lp.ModelProfile('https://example.invalid/v1', 'fixture-key', role)
                       for role in ('translator', 'reviewer', 'proofreader', 'arbiter')}
        self.detect = '{"language":"English","is_target_language":false}'
        self.clean = '{"has_problem":false,"issues":[]}'
        self.problem = '{"has_problem":true,"issues":["incorrect year"]}'
        self.decide = Mock(side_effect=AssertionError('Automatic mode must never ask a user'))

    def translate(self, replies, **options):
        with patch.object(lp, 'chat', side_effect=[self.detect] + replies) as request:
            result = lp.translate_document(self.source, self.output, lp.TranslationOptions(force_auto=True, **options),
                **self.models, decide=self.decide)
        self.decide.assert_not_called()
        return result, request

    def test_forces_proofreading_model_arbitration_and_revision_authorization(self):
        result, request = self.translate(['译文 1999', self.clean])
        self.assertTrue(result['verified'])
        self.assertTrue(result['forceAutomatic'])
        self.assertEqual(result['arbitrationMode'], '大模型裁决')
        self.assertTrue(result['arbiterRevisionAuthorized'])
        self.assertEqual(request.call_args_list[-1].args[0].model, 'proofreader')

    def test_proofreading_revision_is_verified_and_applied_without_dialog(self):
        revision = json.dumps({'decision': 'revised', 'has_problem': False, 'revised_translation': '修订译文 1999'})
        result, _ = self.translate(['错误译文 1998', self.problem, revision, self.clean])
        self.assertTrue(result['verified'])
        self.assertEqual(self.output.read_text(encoding='utf-8'), '修订译文 1999\n')
        self.assertTrue(result['checks'][0]['revisions'][0]['accepted'])

    def test_inconclusive_model_decision_keeps_pending_draft_and_continues(self):
        result, _ = self.translate(['译文', self.problem, '{"decision":"unresolved","has_problem":true}'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(self.output.is_file())

    def test_provider_error_after_translation_preserves_auditable_draft(self):
        result, _ = self.translate(['译文', RuntimeError('offline')])
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'], 'needs_review')
        self.assertIn('offline', result['checks'][0]['checkError'])
        self.assertEqual(self.output.read_text(encoding='utf-8'), '译文\n')

    def test_independent_review_can_select_second_translation_then_proofread_it(self):
        result, _ = self.translate(['第一稿', '第二稿', self.problem,
            '{"choice":"second","has_problem":false}', self.clean], secondary_review=True)
        self.assertTrue(result['verified'])
        self.assertEqual(self.output.read_text(encoding='utf-8'), '第二稿\n')

    def test_failed_operations_have_two_attempts_without_user_waits(self):
        controls = object.__new__(LiteratureControls)
        controls.stopped = Mock(return_value=False)
        controls.log = Mock()
        controls.decide = self.decide
        work = Mock(side_effect=RuntimeError('offline'))
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            controls.run_with_issue_dialog(self.source, work, automatic=True)
        self.assertEqual(work.call_count, 2)
        self.decide.assert_not_called()

    def test_automatic_retry_can_recover_and_cancellation_is_not_retried(self):
        controls = object.__new__(LiteratureControls)
        controls.stopped = Mock(return_value=False)
        controls.log = Mock()
        controls.decide = self.decide
        work = Mock(side_effect=[RuntimeError('temporary'), 'recovered'])
        self.assertEqual(controls.run_with_issue_dialog(self.source, work, automatic=True), 'recovered')
        cancelled = Mock(side_effect=lp.ProcessingCancelled('stop'))
        with self.assertRaises(lp.ProcessingCancelled):
            controls.run_with_issue_dialog(self.source, cancelled, automatic=True)
        self.assertEqual(cancelled.call_count, 1)
        self.decide.assert_not_called()

    def format(self, candidate, arbitration):
        original = self.source.read_text(encoding='utf-8')
        with patch.object(lp, 'chat', side_effect=[candidate, self.problem, arbitration]) as request:
            result = lp.format_markdown_document(self.source, self.root/'paper_FORMATTED.md',
                self.models['translator'], self.models['reviewer'], force_auto=True,
                arbiter=self.models['arbiter'], decide=self.decide)
        self.assertEqual(self.source.read_text(encoding='utf-8'), original)
        self.decide.assert_not_called()
        self.assertEqual(request.call_args_list[-1].args[0].model, 'arbiter')
        return result

    def test_formatting_uses_verification_only_arbitration_without_another_format(self):
        result = self.format(self.source.read_text(encoding='utf-8'),
                             '{"decision":"approve","has_problem":false,"issues":[]}')
        self.assertTrue(result['verified'])
        self.assertTrue(result['forceAutomatic'])
        self.assertEqual(result['formattingPasses'], 1)

    def test_formatting_arbitration_cannot_override_structural_content_loss(self):
        result = self.format('# Paper\n\nThe institution opened.',
                             '{"decision":"approve","has_problem":false,"issues":[]}')
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'], 'needs_review')

    def test_formatting_arbitration_failure_preserves_pending_output(self):
        result = self.format(self.source.read_text(encoding='utf-8'), RuntimeError('offline'))
        self.assertFalse(result['verified'])
        self.assertEqual(result['formattingPasses'], 1)
        self.assertIn('offline', result['checks'][0]['arbitrationError'])

    def test_post_ocr_errors_use_automatic_bounded_retry(self):
        controls = object.__new__(LiteratureControls)
        controls.snapshot = {'auto_translate': True, 'force_auto': True}
        controls.stopped = Mock(return_value=False)
        controls.maybe_upload = Mock()
        controls.process = Mock(side_effect=RuntimeError('offline'))
        controls.log = Mock()
        controls.decide = self.decide
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            controls.after_ocr(self.source, self.root, {})
        self.assertEqual(controls.process.call_count, 2)
        self.decide.assert_not_called()


if __name__ == '__main__':
    unittest.main()
