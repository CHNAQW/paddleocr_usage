import base64
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import app_updater as updates
from test_app_updater import pe_payload

CURRENT = '26.10.19.01'
NEXT = '26.10.19.02'


def response(content=b'', status=200, headers=None):
    value = Mock(status_code=status, headers=headers or {})
    value.iter_content.side_effect = lambda size: iter([content])
    return value


class OnlineUpdateTests(unittest.TestCase):
    def test_cancelled_download_releases_waiter_and_does_not_resume_when_stop_is_reset(self):
        self._blocked_download(timeout=False)

    def test_stalled_download_has_a_total_deadline_and_cleans_up_when_transport_finishes(self):
        self._blocked_download(timeout=True)

    def _blocked_download(self, timeout):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        value = response()
        def blocked(_size):
            entered.set()
            release.wait(3)
            yield b"late ZIP data"
        value.iter_content.side_effect = blocked
        cache = self.root / "cache"
        offer = updates.OnlineUpdate(NEXT, "https://github.com/update.zip", "", "")
        outcome = []
        def download():
            try:
                updates.download_github_update(offer, CURRENT, cache=cache, stop=cancelled.is_set)
            except (updates.UpdateCancelled, TimeoutError) as exc:
                outcome.append(type(exc))
        with patch.object(updates, "_github_response", return_value=value), \
                patch.object(updates, "DOWNLOAD_TIMEOUT", .15 if timeout else 3), \
                patch.object(updates, "import_package") as imported:
            worker = threading.Thread(target=download)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                if not timeout:
                    cancelled.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcome, [TimeoutError if timeout else updates.UpdateCancelled])
                cancelled.clear()  # A subsequent UI task can reuse the same event.
            finally:
                release.set()
                worker.join(3)
            deadline = time.monotonic() + 1
            while (not value.close.called or list(cache.iterdir())) and time.monotonic() < deadline:
                time.sleep(.01)
            imported.assert_not_called()
            value.close.assert_called_once()
            self.assertEqual(list(cache.iterdir()), [])

    def test_package_finishing_after_cancellation_is_discarded(self):
        executable = self.root / "next.exe"
        executable.write_bytes(pe_payload())
        source = updates.build_package(executable, NEXT, self.root)
        package = updates.import_package(source, CURRENT, cache=self.root / "cache")
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        def finishing(*args):
            entered.set()
            release.wait(3)
            return package
        outcome = []
        def download():
            try:
                updates.download_github_update(updates.OnlineUpdate(NEXT, "https://github.com/update.zip", "", ""),
                                               CURRENT, stop=cancelled.is_set)
            except updates.UpdateCancelled:
                outcome.append("cancelled")
        with patch.object(updates, "_download_github_update", side_effect=finishing):
            worker = threading.Thread(target=download)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                cancelled.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcome, ["cancelled"])
            finally:
                release.set()
                worker.join(3)
            deadline = time.monotonic() + 1
            while package.directory.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(package.directory.exists())
            self.assertTrue(source.exists())

    def test_cancelled_request_does_not_wait_for_github_headers(self):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        value = response()
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(3)
            return value
        outcome = []
        def check():
            try:
                updates._github_response("https://github.com/update.zip", stop=cancelled.is_set)
            except updates.UpdateCancelled:
                outcome.append("cancelled")
        with patch.object(requests, "get", side_effect=blocked):
            worker = threading.Thread(target=check)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                cancelled.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcome, ["cancelled"])
            finally:
                release.set()
                worker.join(3)
            deadline = time.monotonic() + 1
            while not value.close.called and time.monotonic() < deadline:
                time.sleep(.01)
            value.close.assert_called_once()

    def test_cancelled_metadata_read_discards_late_body_and_closes_response(self):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        value = response()
        def blocked(_size):
            entered.set()
            release.wait(3)
            yield b'{"version":"late"}'
        value.iter_content.side_effect = blocked
        outcome = []
        def check():
            try:
                updates._github_bytes("https://github.com/update.json", cancelled.is_set)
            except updates.UpdateCancelled:
                outcome.append("cancelled")
        with patch.object(updates, "_github_response", return_value=value):
            worker = threading.Thread(target=check)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                cancelled.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcome, ["cancelled"])
            finally:
                release.set()
                worker.join(3)
            deadline = time.monotonic() + 1
            while not value.close.called and time.monotonic() < deadline:
                time.sleep(.01)
            value.close.assert_called_once()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def release(self, assets=None):
        return {'tag_name': 'v' + NEXT, 'body': 'Release notes', 'assets': assets or []}

    def test_release_prefers_named_full_package_and_records_digest(self):
        asset = {'name': 'PaddleOCR_Update_' + NEXT + '.zip', 'size': 1024, 'digest': 'sha256:' + 'f' * 64}
        with patch.object(updates, '_github_json', return_value=self.release([asset])) as get:
            offer = updates.check_github_update(CURRENT)
        self.assertEqual(offer.version, NEXT)
        self.assertIn('/releases/download/v' + NEXT, offer.url)
        self.assertEqual(offer.sha256, 'f' * 64)
        self.assertEqual(get.call_count, 1)

    def test_release_without_zip_pins_source_archive_to_release_commit(self):
        with patch.object(updates, '_github_json', side_effect=[self.release(), {'sha': 'a' * 40}]):
            offer = updates.check_github_update(CURRENT)
        self.assertEqual(offer.url, f'https://codeload.github.com/{updates.GITHUB_REPOSITORY}/zip/' + 'a' * 40)

    def test_main_reads_literal_version_without_executing_code_and_pins_commit(self):
        code = 'APP_VERSION = "' + NEXT + '"\nraise RuntimeError("never execute")\n'
        values = [{'sha': 'b' * 40, 'commit': {'message': 'New features'}},
                  {'encoding': 'base64', 'size': len(code), 'content': base64.b64encode(code.encode()).decode()}]
        with patch.object(updates, '_github_json', side_effect=values) as get:
            offer = updates.check_github_update(CURRENT, 'main')
        self.assertEqual(offer.version, NEXT)
        self.assertTrue(offer.url.endswith('/' + 'b' * 40))
        self.assertIn('?ref=' + 'b' * 40, get.call_args.args[0])

    def test_equal_or_older_release_does_not_download_or_resolve_source(self):
        for version in (CURRENT, '26.8.13.04'):
            with patch.object(updates, '_github_json', return_value={'tag_name': version}) as get:
                self.assertIsNone(updates.check_github_update(CURRENT))
            self.assertEqual(get.call_count, 1)

    def test_api_403_and_429_use_public_feed_and_pinned_raw_source(self):
        sha = 'c' * 40
        feed = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                '<id>tag:github.com,2008:Grit::Commit/' + sha + '</id><title>Fix updates</title>'
                '</entry></feed>').encode()
        source = ('APP_VERSION = "' + NEXT + '"\nraise RuntimeError("never execute")\n').encode()
        for status in (403, 429):
            with self.subTest(status=status), patch.object(requests, 'get', side_effect=[
                    response(status=status), response(feed), response(source)]) as get:
                offer = updates.check_github_update(CURRENT, 'main')
            self.assertEqual(offer.version, NEXT)
            self.assertEqual(offer.url, f'https://codeload.github.com/{updates.GITHUB_REPOSITORY}/zip/{sha}')
            calls = [call.args[0] for call in get.call_args_list]
            self.assertTrue(calls[1].endswith('/commits/main.atom'))
            self.assertEqual(calls[2], f'https://raw.githubusercontent.com/{updates.GITHUB_REPOSITORY}/{sha}/paddleocr_pdf_to_md_gui.py')
            self.assertEqual(get.call_args.kwargs['headers']['Accept'], 'text/plain')

    def test_contents_api_403_reuses_known_commit_without_a_new_branch_lookup(self):
        sha = 'd' * 40
        content = ('APP_VERSION = "' + NEXT + '"').encode()
        with patch.object(requests, 'get', side_effect=[response(json.dumps({'sha': sha}).encode()),
                          response(status=403), response(content)]) as get:
            offer = updates.check_github_update(CURRENT, 'main')
        self.assertTrue(offer.url.endswith('/' + sha))
        self.assertEqual(get.call_count, 3)
        self.assertIn('/' + sha + '/', get.call_args.args[0])

    def test_invalid_fallback_metadata_and_cancellation_cannot_offer_an_update(self):
        for feed in (b'<html>Blocked</html>', b'<feed>',
                     b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>evil</id></entry></feed>'):
            with patch.object(requests, 'get', side_effect=[response(status=403), response(feed)]) as get:
                with self.assertRaises(ValueError):
                    updates.check_github_update(CURRENT, 'main')
            self.assertEqual(get.call_count, 2)
        with patch.object(requests, 'get') as get, self.assertRaises(updates.UpdateCancelled):
            updates.check_github_update(CURRENT, 'main', stop=lambda: True)
        get.assert_not_called()

    def test_403_diagnostic_names_failed_url_and_never_forwards_application_tokens(self):
        with patch.object(requests, 'get', return_value=response(status=403)) as get:
            with self.assertRaises(updates.GitHubHTTPError) as failure:
                updates.check_github_update(CURRENT, 'release')
        self.assertEqual(failure.exception.status, 403)
        self.assertIn('https://api.github.com/repos/' + updates.GITHUB_REPOSITORY, str(failure.exception))
        self.assertIn('403', str(failure.exception))
        self.assertNotIn('Authorization', get.call_args.kwargs['headers'])

    def test_download_imports_through_existing_validator_and_keeps_original_installation(self):
        executable = self.root / 'next.exe'
        executable.write_bytes(pe_payload())
        zipped = updates.build_package(executable, NEXT, self.root)
        content = zipped.read_bytes()
        offer = updates.OnlineUpdate(NEXT, 'https://github.com/example.zip', '', '', hashlib.sha256(content).hexdigest(), len(content))
        result = response(content, headers={'Content-Length': str(len(content))})
        with patch.object(requests, 'get', return_value=result) as get:
            package = updates.download_github_update(offer, CURRENT, cache=self.root / 'cache')
        self.assertEqual(package.version, NEXT)
        self.assertTrue(package.source.is_file())
        self.assertTrue(package.payload.is_file())
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertNotIn('Authorization', get.call_args.kwargs['headers'])
        self.assertEqual(get.call_args.kwargs['headers']['Accept'], 'application/zip')
        self.assertEqual(executable.read_bytes(), pe_payload())
        self.assertFalse(list((self.root / 'cache').glob('download-*')))
        updates.discard_package(package)
        self.assertFalse(package.source.exists())

    def test_corrupt_digest_truncation_cancel_and_version_mismatch_leave_no_staged_update(self):
        exe = self.root / 'next.exe'; exe.write_bytes(pe_payload())
        content = updates.build_package(exe, NEXT, self.root).read_bytes()
        cases = [
            (updates.OnlineUpdate(NEXT, 'https://github.com/x.zip', '', '', '0' * 64), response(content)),
            (updates.OnlineUpdate(NEXT, 'https://github.com/x.zip', '', ''), response(content, headers={'Content-Length': str(len(content)+1)})),
            (updates.OnlineUpdate('26.10.20.01', 'https://github.com/x.zip', '', ''), response(content)),
        ]
        for offer, result in cases:
            cache = self.root / 'cache'
            with patch.object(requests, 'get', return_value=result), self.assertRaises(ValueError):
                updates.download_github_update(offer, CURRENT, cache=cache)
            self.assertEqual(list(cache.iterdir()), [])
        with patch.object(requests, 'get') as get, self.assertRaises(updates.UpdateCancelled):
            updates.download_github_update(cases[0][0], CURRENT, cache=self.root / 'cache', stop=lambda: True)
        get.assert_not_called()
        self.assertEqual(list((self.root / 'cache').iterdir()), [])

    def test_response_close_error_preserves_download_result_and_cleans_its_directory(self):
        executable = self.root / "next.exe"
        executable.write_bytes(pe_payload())
        content = updates.build_package(executable, NEXT, self.root).read_bytes()
        cache = self.root / "cache"
        for offered_version in (NEXT, "26.10.20.01"):
            with self.subTest(version=offered_version):
                result = response(content)
                result.close.side_effect = OSError("transport cleanup failed")
                offer = updates.OnlineUpdate(offered_version, "https://github.com/update.zip", "", "")
                with patch.object(updates, "_github_response", return_value=result):
                    if offered_version == NEXT:
                        package = updates.download_github_update(offer, CURRENT, cache=cache)
                        self.assertEqual(package.version, NEXT)
                        self.assertTrue(package.payload.is_file())
                        self.assertTrue(package.source.is_file())
                        self.assertEqual(list(cache.iterdir()), [package.directory])
                        updates.discard_package(package)
                    else:
                        # Failure happens after import, so both the extracted
                        # package and the download directory need reclaiming.
                        with self.assertRaises(ValueError):
                            updates.download_github_update(offer, CURRENT, cache=cache)
                result.close.assert_called_once()
                self.assertEqual(list(cache.iterdir()), [])
                self.assertTrue(executable.is_file())

    def test_response_close_error_does_not_mask_metadata_or_http_status(self):
        value = response(b'{"ok": true}')
        value.close.side_effect = OSError("transport cleanup failed")
        with patch.object(updates, "_github_response", return_value=value):
            self.assertEqual(updates._github_bytes("https://github.com/update.json", lambda: False),
                             b'{"ok": true}')
        value.close.assert_called_once()
        denied = response(status=403)
        denied.close.side_effect = OSError("transport cleanup failed")
        with patch.object(requests, "get", return_value=denied):
            with self.assertRaises(updates.GitHubHTTPError) as failure:
                updates._github_response("https://api.github.com/repos/owner/repo")
        self.assertEqual(failure.exception.status, 403)
        denied.close.assert_called_once()

    def test_host_redirect_and_http_errors_never_follow_untrusted_addresses(self):
        for url in ('http://github.com/x', 'https://github.com.evil.invalid/x', 'https://user:secret@github.com/x', 'https://github.com:444/x'):
            with patch.object(requests, 'get') as get, self.assertRaises(ValueError):
                updates._github_response(url)
            get.assert_not_called()
        first = response(status=302, headers={'Location': 'https://untrusted.invalid/payload.zip'})
        with patch.object(requests, 'get', return_value=first) as get, self.assertRaises(ValueError):
            updates._github_response('https://api.github.com/repos/example/zipball/a')
        self.assertEqual(get.call_count, 1)
        first.close.assert_called_once()
        for status in (403, 404, 429, 500):
            with patch.object(requests, 'get', return_value=response(status=status)), self.assertRaises((ValueError, RuntimeError)):
                updates.check_github_update(CURRENT)

    def test_allowed_redirect_and_bounded_metadata(self):
        first = response(status=302, headers={'Location': 'https://codeload.github.com/owner/repo/zip/a'})
        second = response(b'ZIP')
        with patch.object(requests, 'get', side_effect=[first, second]) as get:
            self.assertIs(updates._github_response('https://api.github.com/repos/owner/repo/zipball/a'), second)
        self.assertEqual(get.call_count, 2)
        with patch.object(requests, 'get', return_value=response(b'X' * (4 * updates.BLOCK_SIZE + 1))), self.assertRaises(ValueError):
            updates._github_json('/releases/latest', lambda: False)


if __name__ == '__main__':
    unittest.main()
