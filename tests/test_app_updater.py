import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import app_updater as updates
import source_bootstrap as bootstrap


def pe_payload(size=512):
    value = bytearray(size)
    value[:2] = b"MZ"
    value[60:64] = (128).to_bytes(4, "little")
    value[128:132] = b"PE\0\0"
    value[132:134] = (0x8664).to_bytes(2, "little")
    value[150:152] = (2).to_bytes(2, "little")
    value[152:154] = b"\x0b\x02"
    return bytes(value)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.version = "26.10.18.05"
        self.current = "26.10.18.04"
        self.exe = self.root / "new.exe"
        self.exe.write_bytes(pe_payload())

    def package(self):
        return updates.build_package(self.exe, self.version, self.root / "packages")

    def rewrite_zip(self, path, change):
        with zipfile.ZipFile(path) as archive:
            items = {name: archive.read(name) for name in archive.namelist()}
        change(items)
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in items.items():
                archive.writestr(name, data)

    def source_zip(self, entry=None, requirements=None, additions=None):
        files = {name: "" for name in ("literature_processing.py", "literature_ui.py", "workspace_ui.py",
            "ui_translations.py", "ui_i18n.py", "responsive_ui.py", "github_ui.py", "model_budget.py",
            "app_updater.py", "update_ui.py", "update_helper.ps1")}
        files.update({"paddleocr_pdf_to_md_gui.py": entry or 'APP_VERSION="26.10.18.05"\nraise RuntimeError("must not execute during import")\n',
                      "requirements.txt": requirements if requirements is not None else "requests>=2.31\npypdf>=5.0\n",
                      "app_icon.png": b"icon", "app_icon.ico": b"icon"})
        files.update(additions or {})
        path = self.root / "paddleocr_usage-main.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr("paddleocr_usage-main/" + name, data)
        return path

    def test_full_program_package_round_trip(self):
        package = updates.import_package(self.package(), self.current, cache=self.cache)
        self.assertEqual(package.payload.read_bytes(), self.exe.read_bytes())
        self.assertEqual(package.sha256, hashlib.sha256(self.exe.read_bytes()).hexdigest())
        self.assertEqual(package.version, self.version)
        self.assertTrue(package.source.is_file())

    def test_equal_older_and_malformed_versions_are_rejected(self):
        path = self.package()
        for current in (self.version, "26.10.18.6", "27.1.1.1"):
            with self.subTest(current=current), self.assertRaises(ValueError):
                updates.import_package(path, current, cache=self.cache)
        for invalid in ("26.1", "v26.1.1.1", "1.2.3.70000", "../../file", True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                updates.version_tuple(invalid)

    def test_tampered_executable_is_rejected_and_cache_removed(self):
        path = self.package()
        def tamper(items):
            name = next(name for name in items if name.endswith(".exe"))
            items[name] = items[name][:-1] + b"X"
        self.rewrite_zip(path, tamper)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            updates.import_package(path, self.current, cache=self.cache)
        self.assertFalse(list(self.cache.iterdir()))

    def test_wrong_size_platform_filename_and_sha_manifest_fail_before_staging(self):
        for field, value in (("size", updates.MAX_PAYLOAD + 1), ("platform", "linux"),
                             ("filename", "../bad.exe"), ("sha256", "bad"), ("schema", True)):
            with self.subTest(field=field):
                path = self.package()
                def tamper(items):
                    manifest = json.loads(items["update.json"])
                    manifest[field] = value
                    items["update.json"] = json.dumps(manifest).encode()
                self.rewrite_zip(path, tamper)
                with self.assertRaises(ValueError):
                    updates.import_package(path, self.current, cache=self.cache)
                self.assertFalse(self.cache.exists())

    def test_path_traversal_and_duplicate_zip_members_are_rejected(self):
        path = self.package()
        self.rewrite_zip(path, lambda items: items.update({"../escape.exe": b"escape"}))
        with self.assertRaises(ValueError):
            updates.import_package(path, self.current, cache=self.cache)
        self.assertFalse((self.root / "escape.exe").exists())
        path = self.package()
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("UPDATE.JSON", "{}")
        with self.assertRaises(ValueError):
            updates.import_package(path, self.current, cache=self.cache)

    def test_corrupted_or_non_executable_packages_are_rejected(self):
        broken = self.root / "broken.zip"
        broken.write_text("not a ZIP")
        with self.assertRaises(ValueError):
            updates.import_package(broken, self.current, cache=self.cache)
        self.exe.write_bytes(b"html" * 128)
        with self.assertRaises(ValueError):
            self.package()

    def test_cancelled_import_cleans_created_files_and_preserves_original_zip(self):
        self.exe.write_bytes(pe_payload(3 * 1024 * 1024))
        path = self.package()
        cancelled = False
        def progress(done, total):
            nonlocal cancelled
            cancelled = True
        with self.assertRaises(updates.UpdateCancelled):
            updates.import_package(path, self.current, cache=self.cache, stop=lambda: cancelled, progress=progress)
        self.assertTrue(path.is_file())
        self.assertFalse(list(self.cache.iterdir()))

    def test_github_source_zip_is_validated_without_executing_it(self):
        package = updates.import_package(self.source_zip(), self.current, cache=self.cache)
        self.assertIsInstance(package, updates.SourcePackage)
        self.assertEqual(package.version, self.version)
        bootstrap.validated_source(package.record, self.cache)
        self.assertIn('raise RuntimeError', (package.directory / "source/paddleocr_pdf_to_md_gui.py").read_text())

    def test_source_dependency_change_requires_full_program_update(self):
        with self.assertRaisesRegex(ValueError, "依赖"):
            updates.import_package(self.source_zip(requirements="numpy>=2\n"), self.current, cache=self.cache)
        self.assertFalse(self.cache.exists())

    def test_unbundled_import_is_rejected_before_source_activation(self):
        entry = 'APP_VERSION="26.10.18.05"\nimport dependency_that_is_not_installed_1234\n'
        with self.assertRaisesRegex(ValueError, "dependency_that_is_not_installed_1234"):
            updates.import_package(self.source_zip(entry=entry), self.current, cache=self.cache)
        self.assertFalse(self.cache.exists())

    def test_source_traversal_syntax_and_symlinks_are_rejected(self):
        cases = ({"../escape.py": "BAD=1"}, {"extra.py": "def ("})
        for additions in cases:
            with self.subTest(additions=additions), self.assertRaises(ValueError):
                updates.import_package(self.source_zip(additions=additions), self.current, cache=self.cache)
        path = self.source_zip()
        with zipfile.ZipFile(path, "a") as archive:
            link = zipfile.ZipInfo("paddleocr_usage-main/extra.py")
            link.external_attr = (0o120777 << 16)
            archive.writestr(link, "../../escape")
        with self.assertRaises(ValueError):
            updates.import_package(path, self.current, cache=self.cache)

    def test_install_rechecks_staged_source_and_executable_integrity(self):
        for source in (False, True):
            with self.subTest(source=source):
                package = updates.import_package(self.source_zip() if source else self.package(), self.current, cache=self.cache)
                target = package.directory / "source/literature_ui.py" if source else package.payload
                target.write_bytes(b"tampered")
                with patch.object(updates.sys, "platform", "win32"), patch.object(updates.subprocess, "Popen") as popen:
                    with self.assertRaises(ValueError):
                        updates.launch_install(package, self.exe, self.current, cache=self.cache)
                self.assertEqual(popen.call_count, 0)

    def test_install_plan_preserves_unicode_paths_without_shell_interpolation(self):
        folder = self.root / "Unicode ' & 测试"
        folder.mkdir()
        current = folder / "current.exe"
        current.write_bytes(pe_payload())
        for source in (False, True):
            with self.subTest(source=source):
                package = updates.import_package(self.source_zip() if source else self.package(), self.current, cache=self.cache)
                with patch.object(updates.sys, "platform", "win32"), patch.object(updates.subprocess, "Popen") as popen:
                    plan = updates.launch_install(package, current, self.current, cache=self.cache)
                self.assertEqual(plan["kind"], "source" if source else "exe")
                self.assertEqual(plan["target"], str(current))
                arguments = popen.call_args.args[0]
                self.assertNotIn(str(current), arguments[-1])
                self.assertNotIn("Bypass", arguments)
                actual = json.loads(Path(popen.call_args.kwargs["env"]["PADDLEOCR_UPDATE_PLAN"]).read_text())
                self.assertEqual(actual["target"], str(current))

    def test_startup_acknowledgement_is_limited_to_update_cache(self):
        local = self.root / "local"
        stage = local / "PaddleOCR/updates/update-test"
        stage.mkdir(parents=True)
        marker = stage / "ready"
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local), "PADDLEOCR_UPDATE_HEALTH": str(marker)}):
            updates.signal_ready(self.version)
        self.assertEqual(marker.read_text(), self.version)
        outside = self.root / "outside"
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local), "PADDLEOCR_UPDATE_HEALTH": str(outside)}):
            updates.signal_ready(self.version)
        self.assertFalse(outside.exists())

    def test_last_result_handles_powershell_bom_and_invalid_json(self):
        self.cache.mkdir()
        path = self.cache / "last-update.json"
        path.write_text(json.dumps({"status": "failed", "restored": True}), encoding="utf-8-sig")
        self.assertTrue(updates.last_result(self.cache)["restored"])
        path.write_text("bad")
        self.assertIsNone(updates.last_result(self.cache))


class BootstrapTests(unittest.TestCase):
    def test_updated_module_overrides_preloaded_builtin_and_state_is_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            cache = local / "PaddleOCR/updates"
            source = cache / "update-one/source"
            source.mkdir(parents=True)
            result = local / "result.txt"
            files = {"paddleocr_pdf_to_md_gui.py": 'import update_smoke_feature\nfrom pathlib import Path\nPath(' + repr(str(result)) + ').write_text(update_smoke_feature.VALUE)\n',
                     "update_smoke_feature.py": 'VALUE="updated"\n'}
            for name, text in files.items():
                (source / name).write_text(text)
            record = {"schema": 1, "application": updates.APPLICATION_ID, "version": "26.10.18.05", "directory": str(source),
                      "files": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in files}}
            pointer = cache / "active-source.json"
            pointer.write_text(json.dumps(record))
            old = types.ModuleType("update_smoke_feature")
            old.__file__, old.VALUE = "builtin.py", "original"
            with patch.dict(sys.modules, {"update_smoke_feature": old}), patch.dict(os.environ, {"LOCALAPPDATA": folder}):
                self.assertTrue(bootstrap.run_installed_source("26.10.18.04"))
                self.assertIs(sys.modules["update_smoke_feature"], old)
            self.assertEqual(result.read_text(), "updated")
            (source / "update_smoke_feature.py").write_text('VALUE="tampered"')
            with patch.dict(os.environ, {"LOCALAPPDATA": folder}):
                self.assertFalse(bootstrap.run_installed_source("26.10.18.04"))
            self.assertFalse(pointer.exists())
            self.assertTrue(list(cache.glob("failed-source-*.json")))

    def test_installer_owned_startup_failure_keeps_activation_record_for_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "PaddleOCR/updates"
            cache.mkdir(parents=True)
            pointer = cache / "active-source.json"
            pointer.write_text(json.dumps({"schema": 1, "application": updates.APPLICATION_ID,
                "version": "26.10.18.05", "directory": str(cache / "missing"), "files": {}}))
            with patch.dict(os.environ, {"LOCALAPPDATA": folder, "PADDLEOCR_UPDATE_HEALTH": str(cache / "ready")}), self.assertRaises(ValueError):
                bootstrap.run_installed_source("26.10.18.04")
            self.assertTrue(pointer.is_file())

    def test_failed_source_gui_is_restarted_in_a_clean_builtin_process(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "PaddleOCR/updates"
            source = cache / "update-failed/source"
            source.mkdir(parents=True)
            entry = source / "paddleocr_pdf_to_md_gui.py"
            entry.write_text('import os\nos.environ["LOCALAPPDATA"]="unexpected-folder"\nraise RuntimeError("startup failure")\n')
            record = {"schema": 1, "application": updates.APPLICATION_ID, "version": "26.10.18.05",
                      "directory": str(source), "files": {entry.name: hashlib.sha256(entry.read_bytes()).hexdigest()}}
            pointer = cache / "active-source.json"
            pointer.write_text(json.dumps(record))
            with patch.dict(os.environ, {"LOCALAPPDATA": folder, "NUITKA_ONEFILE_PARENT": "123"}), \
                    patch.object(sys, "platform", "win32"), \
                    patch.object(sys, "_paddleocr_launcher", "previous.exe", create=True), \
                    patch.object(sys, "_paddleocr_source_error", None, create=True), \
                    patch.object(bootstrap.subprocess, "Popen") as restart:
                self.assertTrue(bootstrap.run_installed_source("26.10.18.04"))
                self.assertEqual(restart.call_count, 1)
                self.assertNotIn("NUITKA_ONEFILE_PARENT", restart.call_args.kwargs["env"])
                self.assertEqual(restart.call_args.kwargs["env"]["LOCALAPPDATA"], folder)
            self.assertFalse(pointer.exists())


if __name__ == "__main__":
    unittest.main()
