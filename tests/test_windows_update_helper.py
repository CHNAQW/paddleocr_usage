"""Exercise the real Windows PowerShell host, stopping before any EXE replacement."""
import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_updater as updates
from test_app_updater import pe_payload


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell')
class NativeWindowsHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="PaddleOCR ' & 测试 ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.exe = self.root / "当前程序 ' & test.exe"
        self.exe.write_bytes(pe_payload())
        archive = updates.build_package(self.exe, '26.10.19.04', self.root)
        self.package = updates.import_package(archive, '26.10.19.03', cache=self.root / 'cache')
        self.processes = []
        self.addCleanup(self.stop_helpers)

    def stop_helpers(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)

    def spawn(self, *args, **kwargs):
        process = self.native_popen(*args, **kwargs)
        self.processes.append(process)
        return process

    def test_real_powershell_acknowledges_startup_with_unicode_and_quoted_paths(self):
        self.native_popen = subprocess.Popen
        with patch.object(updates.subprocess, 'Popen', side_effect=self.spawn):
            plan = updates.launch_install(self.package, self.exe, '26.10.19.03', cache=self.root / 'cache')
        self.assertEqual(Path(plan['handshake']).read_text(), 'ready')
        self.assertIsNone(self.processes[0].poll())
        self.assertTrue(Path(plan['log']).is_file())
        self.assertTrue(Path(plan['helper_output']).is_file())
        self.assertEqual(self.exe.read_bytes(), pe_payload())
        # The helper is waiting for this test process. Cleanup terminates it
        # before it can replace or launch the deliberately non-runnable EXE.

    def test_real_powershell_parser_error_is_captured_before_handshake(self):
        self.native_popen = subprocess.Popen
        def fail_parse(arguments, **kwargs):
            arguments = list(arguments)
            arguments[-1] = base64.b64encode('if ('.encode('utf-16le')).decode('ascii')
            return self.spawn(arguments, **kwargs)
        with patch.object(updates.subprocess, 'Popen', side_effect=fail_parse):
            with self.assertRaisesRegex(RuntimeError, '更新助手'):
                updates.launch_install(self.package, self.exe, '26.10.19.03', cache=self.root / 'cache')
        output = next(self.package.directory.glob('helper-output-*.log'))
        self.assertGreater(output.stat().st_size, 0)
        self.assertIn('PowerShell exit code:', (self.package.directory / 'install.log').read_text(encoding='utf-8'))
        self.assertFalse((self.package.directory / 'install.json').exists())
        self.assertEqual(self.exe.read_bytes(), pe_payload())
