import base64
import hashlib
import io
import json
import tempfile
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
        self.assertTrue(offer.url.endswith('/zipball/' + 'a' * 40))

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
