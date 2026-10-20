import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import update_cleanup as cleanup


class UpdateCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "PaddleOCR" / "updates"
        self.cache.mkdir(parents=True)
        self.exe = self.root / "application.exe"
        self.exe.write_bytes(b"current")
        self.alive = patch.object(cleanup, "_alive", return_value=False)
        self.alive.start()
        self.addCleanup(self.alive.stop)

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def stage(self, number, source=True, previous=None, success=True):
        stage = self.cache / ("update-%s" % number)
        stage.mkdir()
        cleanup.mark_owned(stage, "source" if source else "package")
        stamp = "%012x" % number
        version = "26.10.20.%02d" % number
        source_dir = stage / "source"
        if source:
            source_dir.mkdir()
            (source_dir / "paddleocr_pdf_to_md_gui.py").write_text("# installed")
        else:
            (stage / "payload.exe").write_bytes(b"payload")
        record = {
            "schema": 1, "application": cleanup.APPLICATION_ID, "version": version,
            "directory": str(source_dir), "files": {"paddleocr_pdf_to_md_gui.py": "hash"},
        }
        plan = {
            "pid": 123456, "target": str(self.exe),
            "backup": str(self.exe.with_name("application.before-update-%s.exe" % stamp)),
            "payload": str(stage if source else stage / "payload.exe"),
            "health": str(stage / "ready"), "log": str(stage / "install.log"),
            "active": str(self.cache / "active-source.json"),
            "source_backup": str(stage / ("previous-source-%s.json" % stamp)),
            "kind": "source" if source else "exe", "version": version,
        }
        self.write(stage / "install.json", plan)
        if previous:
            self.write(Path(plan["source_backup"]), previous)
        if success:
            (stage / "ready").write_text(version)
        (stage / "download.zip").write_bytes(b"download")
        (stage / "install.log").write_bytes(b"log" * cleanup.MAX_LOG)
        os.utime(stage / "install.json", (100 + number, 100 + number))
        return stage, record, plan

    def test_successive_sources_keep_current_and_immediate_rollback_and_drop_zip(self):
        older, record1, _ = self.stage(1)
        previous, record2, _ = self.stage(2, previous=record1)
        current, record3, plan = self.stage(3, previous=record2)
        self.write(self.cache / "active-source.json", record3)
        original_zip = self.root / "user-selected.zip"
        original_zip.write_bytes(b"user's archive")
        cleanup.cleanup_updates(self.cache, current / "source", self.exe)
        self.assertTrue((current / "source/paddleocr_pdf_to_md_gui.py").exists())
        self.assertTrue((previous / "source/paddleocr_pdf_to_md_gui.py").exists())
        self.assertFalse((older / "source").exists())
        self.assertFalse((current / "download.zip").exists())
        self.assertFalse((previous / "download.zip").exists())
        self.assertTrue(Path(plan["source_backup"]).exists())
        self.assertLessEqual((current / "install.log").stat().st_size, cleanup.MAX_LOG)
        self.assertEqual(original_zip.read_bytes(), b"user's archive")
        # Repeat startup and a fourth update must not depend on deleted metadata.
        fourth, record4, _ = self.stage(4, previous=record3)
        self.write(self.cache / "active-source.json", record4)
        cleanup.cleanup_updates(self.cache, fourth / "source", self.exe)
        self.assertFalse((previous / "source").exists())
        self.assertTrue((current / "source").exists())
        self.assertTrue((fourth / "source").exists())

    def test_live_stage_and_other_running_source_are_preserved(self):
        active, record, _ = self.stage(1)
        self.write(self.cache / "active-source.json", record)
        other, _, _ = self.stage(2)
        cleanup.mark_owned(other, "source")
        running, _, _ = self.stage(3)
        self.write(running / ".running-456.json", {"application": cleanup.APPLICATION_ID, "pid": 456})
        with patch.object(cleanup, "_alive", side_effect=lambda pid: pid in {os.getpid(), 456}):
            cleanup.cleanup_updates(self.cache, active / "source", self.exe)
        self.assertTrue((other / "source").exists())
        self.assertTrue((other / "download.zip").exists())
        self.assertTrue((running / "source").exists())

    def test_latest_exe_backup_survives_and_unknown_backup_is_untouched(self):
        stages = [self.stage(number, source=False) for number in (1, 2, 3)]
        for _, _, plan in stages:
            Path(plan["backup"]).write_bytes(b"backup")
        unknown = self.root / "application.before-update-aaaaaaaaaaaa.exe"
        unknown.write_bytes(b"user file")
        cleanup.cleanup_updates(self.cache, current_exe=self.exe)
        self.assertFalse(Path(stages[0][2]["backup"]).exists())
        self.assertFalse(Path(stages[1][2]["backup"]).exists())
        self.assertTrue(Path(stages[2][2]["backup"]).exists())
        self.assertTrue(unknown.exists())
        self.assertTrue(self.exe.exists())
        self.assertTrue(all(not (stage / "payload.exe").exists() for stage, _, _ in stages))

    def test_exe_backup_ownership_survives_many_intervening_source_updates(self):
        first, _, first_plan = self.stage(1, source=False)
        Path(first_plan["backup"]).write_bytes(b"first backup")
        for number in range(2, 7):
            self.stage(number)
        cleanup.cleanup_updates(self.cache, current_exe=self.exe)
        self.assertTrue((first / "install.json").exists())
        self.assertTrue(Path(first_plan["backup"]).exists())
        final, _, final_plan = self.stage(7, source=False)
        Path(final_plan["backup"]).write_bytes(b"latest backup")
        cleanup.cleanup_updates(self.cache, current_exe=self.exe)
        self.assertFalse(Path(first_plan["backup"]).exists())
        self.assertFalse(first.exists())
        self.assertTrue(Path(final_plan["backup"]).exists())
        self.assertTrue((final / "install.json").exists())

    def test_failed_and_abandoned_imports_expire_without_losing_recent_diagnostics(self):
        failed, _, _ = self.stage(1, success=False)
        os.utime(failed, (1, 1))
        recent, _, _ = self.stage(2, success=False)
        unknown = self.cache / "update-user-notes"
        unknown.mkdir()
        (unknown / "notes.md").write_text("keep")
        download = self.cache / "download-abandoned"
        download.mkdir()
        cleanup.mark_owned(download, "download")
        (download / "github-update.zip").write_bytes(b"partial")
        os.utime(download, (1, 1))
        cleanup.cleanup_updates(self.cache, now=time.time())
        self.assertFalse((failed / "download.zip").exists())
        self.assertFalse((failed / "source").exists())
        self.assertTrue((failed / "install.log").exists())
        self.assertTrue((recent / "download.zip").exists())
        self.assertFalse(download.exists())
        self.assertEqual((unknown / "notes.md").read_text(), "keep")

    def test_only_three_historical_transactions_and_bounded_logs_are_retained(self):
        stages = [self.stage(i)[0] for i in range(1, 7)]
        for stage in stages:
            for index in range(5):
                (stage / ("helper-output-%s.log" % index)).write_bytes(b"x" * (cleanup.MAX_LOG * 2))
        cleanup.cleanup_updates(self.cache)
        self.assertFalse(any(stage.exists() for stage in stages[:3]))
        for stage in stages[3:]:
            self.assertLessEqual(len(list(stage.glob("*.log"))), 3)
            self.assertFalse((stage / "source").exists())
            self.assertTrue(all(log.stat().st_size <= cleanup.MAX_LOG for log in stage.glob("*.log")))

    def test_symlinks_and_corrupt_activation_fail_closed(self):
        stage, record, _ = self.stage(1)
        outside = self.root / "private"
        outside.mkdir()
        secret = outside / "notes.md"
        secret.write_text("private")
        try:
            (stage / "source/linked").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        cleanup.cleanup_updates(self.cache)
        self.assertEqual(secret.read_text(), "private")
        self.assertTrue((stage / "source").exists())
        (self.cache / "active-source.json").write_text("broken JSON")
        original = (stage / "source/paddleocr_pdf_to_md_gui.py").read_text()
        cleanup.cleanup_updates(self.cache)
        self.assertEqual((stage / "source/paddleocr_pdf_to_md_gui.py").read_text(), original)

    def test_installer_mutex_prevents_any_cleanup(self):
        stage, _, _ = self.stage(1)
        @contextlib.contextmanager
        def busy():
            yield False
        with patch.object(cleanup, "_installation_idle", busy):
            self.assertEqual(cleanup.cleanup_updates(self.cache), [])
        self.assertTrue((stage / "download.zip").exists())

    def test_maintenance_time_budget_preserves_data_and_can_resume_next_time(self):
        stage, _, _ = self.stage(1)
        with patch.object(cleanup, "MAINTENANCE_SECONDS", 0):
            self.assertEqual(cleanup.cleanup_updates(self.cache), [])
        self.assertTrue((stage / "download.zip").exists())
        cleanup.cleanup_updates(self.cache)
        self.assertFalse((stage / "download.zip").exists())
        self.assertTrue((stage / "install.log").exists())

    @unittest.skipUnless(sys.platform == "win32", "requires the native Windows mutex")
    def test_real_windows_installer_mutex_is_respected_across_threads(self):
        stage, _, _ = self.stage(1)
        acquired, release = threading.Event(), threading.Event()
        ownership = []
        def installer():
            with cleanup._installation_idle() as owned:
                ownership.append(owned)
                acquired.set()
                release.wait(10)
        thread = threading.Thread(target=installer)
        thread.start()
        try:
            self.assertTrue(acquired.wait(5))
            self.assertEqual(ownership, [True])
            self.assertEqual(cleanup.cleanup_updates(self.cache), [])
            self.assertTrue((stage / "download.zip").exists())
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())

    @unittest.skipUnless(sys.platform == "win32", "requires Windows directory junctions")
    def test_windows_junction_never_traverses_into_user_documents(self):
        stage, _, _ = self.stage(1)
        outside = self.root / "private"
        outside.mkdir()
        document = outside / "notes.md"
        document.write_text("private")
        result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", "junction", "private"],
                                cwd=self.root, capture_output=True, timeout=10)
        if result.returncode:
            self.skipTest("this Windows host cannot create directory junctions")
        junction = self.root / "junction"
        junction.rename(stage / "source/linked")
        cleanup.cleanup_updates(self.cache)
        self.assertEqual(document.read_text(), "private")
        self.assertTrue((stage / "source").exists())

    def test_legacy_source_without_process_leases_is_not_assumed_unused(self):
        stage, _, _ = self.stage(1)
        (stage / cleanup.OWNER).unlink()
        cleanup.cleanup_updates(self.cache)
        self.assertTrue((stage / "source/paddleocr_pdf_to_md_gui.py").exists())
        self.assertFalse((stage / "download.zip").exists())

    def test_nuitka_runtime_caches_are_never_treated_as_disposable_downloads(self):
        root = self.cache.parent / "PDFToMarkdown"
        root.mkdir()
        directories = []
        for number in range(1, 6):
            directory = root / ("26.10.20.%02d" % number)
            directory.mkdir()
            (directory / "runtime.dll").write_bytes(b"runtime")
            directories.append(directory)
        cleanup.cleanup_updates(self.cache)
        for directory in directories:
            self.assertEqual(list(directory.iterdir()), [directory / "runtime.dll"])
            self.assertEqual((directory / "runtime.dll").read_bytes(), b"runtime")

    def test_only_three_owned_failed_activation_records_remain(self):
        records = []
        for number in range(1, 6):
            _, record, _ = self.stage(number)
            path = self.cache / ("failed-source-%032x.json" % number)
            self.write(path, record)
            os.utime(path, (number, number))
            records.append(path)
        unrelated = self.cache / "failed-source-personal.json"
        unrelated.write_text("personal notes")
        cleanup.cleanup_updates(self.cache)
        self.assertFalse(records[0].exists())
        self.assertFalse(records[1].exists())
        self.assertTrue(all(path.exists() for path in records[2:]))
        self.assertEqual(unrelated.read_text(), "personal notes")

    def test_health_handshake_waits_for_matching_success_before_maintenance(self):
        stage, _, plan = self.stage(1)
        marker = stage / "ready"
        def complete(_delay):
            self.write(self.cache / "last-update.json", {
                "status": "installed", "version": plan["version"], "log": plan["log"],
            })
        with patch.object(cleanup.threading, "Thread") as thread, \
                patch.object(cleanup.time, "sleep", side_effect=complete), \
                patch.object(cleanup, "cleanup_updates") as clean:
            cleanup.start_maintenance(self.cache, plan["version"], marker)
            thread.call_args.kwargs["target"]()
        clean.assert_called_once()

    def test_failed_health_handshake_does_not_clean_rollback_data(self):
        stage, _, plan = self.stage(1)
        self.write(self.cache / "last-update.json", {
            "status": "failed", "version": plan["version"], "log": plan["log"],
        })
        with patch.object(cleanup.threading, "Thread") as thread, \
                patch.object(cleanup, "cleanup_updates") as clean:
            cleanup.start_maintenance(self.cache, plan["version"], stage / "ready")
            thread.call_args.kwargs["target"]()
        clean.assert_not_called()


if __name__ == "__main__":
    unittest.main()
