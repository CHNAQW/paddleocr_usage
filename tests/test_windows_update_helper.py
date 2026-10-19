"""Exercise native PowerShell startup, source activation and startup rollback."""
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


@unittest.skipUnless(sys.platform == 'win32', 'Requires Windows PowerShell')
class NativeSourceActivationTests(unittest.TestCase):
    """Run actual source activation and rollback under Windows PowerShell 5.1."""
    @classmethod
    def setUpClass(cls):
        import os
        cls.build = tempfile.TemporaryDirectory(prefix="PaddleOCR native probe ")
        cls.addClassCleanup(cls.build.cleanup)
        cls.probe = Path(cls.build.name) / 'probe.exe'
        source = Path(cls.build.name) / 'probe.cs'
        source.write_text(r'''
using System;
using System.IO;
public class UpdateProbe {
    public static int Main() {
        string active = Environment.GetEnvironmentVariable("PADDLEOCR_TEST_ACTIVE");
        string health = Environment.GetEnvironmentVariable("PADDLEOCR_UPDATE_HEALTH");
        string expected = Environment.GetEnvironmentVariable("PADDLEOCR_TEST_VERSION");
        if (String.IsNullOrEmpty(health)) {
            string restarted = Environment.GetEnvironmentVariable("PADDLEOCR_TEST_RESTARTED");
            File.WriteAllText(restarted + ".probe-tmp", File.Exists(active) ? File.ReadAllText(active) : "builtin");
            File.Move(restarted + ".probe-tmp", restarted);
            return 0;
        }
        if (Environment.GetEnvironmentVariable("PADDLEOCR_TEST_FAIL_HEALTH") == "1") return 42;
        if (!File.Exists(active) || !File.ReadAllText(active).Contains(expected)) return 43;
        File.WriteAllText(health + ".probe-tmp", expected);
        File.Move(health + ".probe-tmp", health);
        return 0;
    }
}
''', encoding='utf-8')
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        command = ('Add-Type -TypeDefinition (Get-Content -LiteralPath $env:PADDLEOCR_TEST_CS -Raw) '
                   '-Language CSharp -OutputAssembly $env:PADDLEOCR_TEST_EXE -OutputType ConsoleApplication')
        encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
        completed = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            env={**os.environ, 'PADDLEOCR_TEST_CS': str(source), 'PADDLEOCR_TEST_EXE': str(cls.probe)},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
        if completed.returncode or not cls.probe.is_file():
            raise AssertionError(completed.stdout.decode('utf-8', errors='replace'))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="PaddleOCR 源码 ' & ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / 'cache'
        self.exe = self.root / "应用程序 ' & test.exe"
        self.exe.write_bytes(self.probe.read_bytes())
        self.package = self.source_package('26.10.19.07')
        self.active = self.cache / 'active-source.json'
        self.restarted = self.root / 'restarted.txt'
        self.processes = []
        self.native_popen = subprocess.Popen
        self.addCleanup(self.stop_helpers)

    stop_helpers = NativeWindowsHelperTests.stop_helpers
    spawn = NativeWindowsHelperTests.spawn

    def source_package(self, version):
        import test_app_updater as fixtures
        archive = fixtures.UpdateTests.source_zip(self, entry='APP_VERSION="' + version + '"\n')
        return updates.import_package(archive, '26.10.19.05', cache=self.cache)

    def previous_installation(self):
        import hashlib
        directory = self.cache / 'source-before'
        directory.mkdir()
        entry = directory / 'paddleocr_pdf_to_md_gui.py'
        entry.write_bytes(b'APP_VERSION="26.10.19.06"\n')
        record = {**self.package.record, 'version': '26.10.19.06', 'directory': str(directory),
                  'files': {entry.name: hashlib.sha256(entry.read_bytes()).hexdigest()}}
        # Preserve the previous record byte-for-byte, including Unicode and BOM.
        self.active.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8-sig')
        return self.active.read_bytes()

    def install(self, current='26.10.19.06', fail_health=False):
        import os
        import time
        old_process = self.native_popen([sys.executable, '-c', 'import time; time.sleep(120)'])
        self.processes.append(old_process)
        environment = {'PADDLEOCR_TEST_ACTIVE': str(self.active), 'PADDLEOCR_TEST_VERSION': self.package.version,
                       'PADDLEOCR_TEST_RESTARTED': str(self.restarted),
                       'PADDLEOCR_TEST_FAIL_HEALTH': '1' if fail_health else '0'}
        with patch.dict(os.environ, environment), patch.object(updates.os, 'getpid', return_value=old_process.pid), \
                patch.object(updates.subprocess, 'Popen', side_effect=self.spawn):
            plan = updates.launch_install(self.package, self.exe, current, cache=self.cache)
        helper = self.processes[-1]
        self.assertEqual(Path(plan['handshake']).read_text(), 'ready')
        time.sleep(.2)  # Let Wait-Process subscribe before the old process exits.
        old_process.terminate()
        old_process.wait(timeout=10)
        helper.wait(timeout=30)
        diagnostic = Path(plan['log']).read_text(encoding='utf-8-sig', errors='replace')
        result = json.loads(Path(plan['result']).read_text(encoding='utf-8-sig'))
        if fail_health:
            deadline = time.monotonic() + 5
            while not self.restarted.is_file() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(self.restarted.is_file(), diagnostic)
        self.assertEqual(self.exe.read_bytes(), self.probe.read_bytes())
        return plan, result, diagnostic

    def test_first_source_install_activates_and_acknowledges_startup(self):
        plan, result, log = self.install()
        self.assertEqual(result['status'], 'installed', log)
        self.assertEqual(json.loads(self.active.read_text(encoding='utf-8-sig'))['version'], '26.10.19.07')
        self.assertFalse(Path(plan['source_backup']).exists())

    def test_successive_source_updates_atomically_replace_and_back_up_previous_record(self):
        previous = self.previous_installation()
        plan, result, log = self.install()
        self.assertEqual(result['status'], 'installed', log)
        self.assertEqual(Path(plan['source_backup']).read_bytes(), previous)
        first_record = self.active.read_bytes()
        self.package = self.source_package('26.10.19.08')
        second_plan, result, log = self.install(current='26.10.19.07')
        self.assertEqual(result['status'], 'installed', log)
        self.assertNotEqual(second_plan['source_backup'], plan['source_backup'])
        self.assertEqual(Path(second_plan['source_backup']).read_bytes(), first_record)
        self.assertEqual(Path(plan['source_backup']).read_bytes(), previous)
        self.assertEqual(json.loads(self.active.read_text())['version'], '26.10.19.08')

    def test_failed_startup_restores_exact_previous_record_and_restarts_it(self):
        previous = self.previous_installation()
        plan, result, log = self.install(fail_health=True)
        self.assertEqual(result['status'], 'failed', log)
        self.assertTrue(result['restored'], log)
        self.assertEqual(self.active.read_bytes(), previous)
        self.assertEqual(Path(plan['source_backup']).read_bytes(), previous)
        self.assertEqual(json.loads(self.restarted.read_text())['version'], '26.10.19.06')

    def test_failed_first_install_removes_activation_record_and_restarts_builtin(self):
        _, result, log = self.install(fail_health=True)
        self.assertEqual(result['status'], 'failed', log)
        self.assertTrue(result['restored'], log)
        self.assertFalse(self.active.exists())
        self.assertEqual(self.restarted.read_text(), 'builtin')
