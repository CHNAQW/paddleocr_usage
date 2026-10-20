import queue
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import literature_processing as lp
import paddleocr_pdf_to_md_gui as application
from ui_i18n import set_language


def response(data=None, status=200):
    value = Mock(status_code=status)
    value.json.return_value = data
    return value


class GitHubConnectionTests(unittest.TestCase):
    def setUp(self):
        set_language("zh")
        self.client = lp.GitHubSetupClient("session-secret")

    def test_repository_links_are_normalized_without_accepting_other_hosts_or_traversal(self):
        for value in ("owner/repo", "https://github.com/owner/repo", "github.com/owner/repo/",
                      "https://github.com/owner/repo.git", "https://github.com/owner/repo/tree/main/papers"):
            self.assertEqual(lp.github_repository_name(value), "owner/repo")
        for value in ("https://example.invalid/owner/repo", "https://github.com.evil.invalid/owner/repo",
                      "https://user:secret@github.com/owner/repo", "../repo", "owner/..", "owner", "owner/repo/extra"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lp.github_repository_name(value)

    def test_connect_paginates_and_filters_archived_and_read_only_repositories(self):
        page = [{"full_name": f"owner/repo{i}", "permissions": {"push": True}} for i in range(100)]
        final = [{"full_name": "owner/archived", "archived": True},
                 {"full_name": "owner/read-only", "permissions": {"push": False}}, {"full_name": "owner/private"}]
        with patch.object(lp.requests, "get", side_effect=[response({"login": "reader"}), response(page), response(final)]) as get:
            result = self.client.connect()
        self.assertEqual(result["login"], "reader")
        self.assertEqual(len(result["repositories"]), 101)
        self.assertIn("owner/private", result["repositories"])
        self.assertEqual(get.call_args.kwargs["params"]["page"], 2)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertNotIn("session-secret", repr(self.client))

    def test_real_default_branch_and_branch_names_are_preserved(self):
        with patch.object(lp.requests, "get", side_effect=[response({"default_branch": "master"}),
                response([{"name": "master"}, {"name": "review/papers"}])]):
            result = self.client.prepare_repository("owner/repo")
        self.assertEqual(result["default_branch"], "master")
        self.assertEqual(result["branches"], ["master", "review/papers"])

    def test_empty_archived_and_read_only_repositories_have_actionable_errors(self):
        for info in ({"archived": True}, {"disabled": True}, {"permissions": {"push": False}}):
            with self.subTest(info=info), patch.object(lp.requests, "get", return_value=response(info)), self.assertRaises(ValueError):
                self.client.prepare_repository("owner/repo")
        with patch.object(lp.requests, "get", side_effect=[response({}), response([])]), self.assertRaisesRegex(ValueError, "README"):
            self.client.prepare_repository("owner/repo")

    def test_authentication_errors_do_not_echo_tokens_or_response_bodies(self):
        for status in (401, 403, 404, 429, 500, 302):
            value = response({"message": "session-secret"}, status)
            with self.subTest(status=status), patch.object(lp.requests, "get", return_value=value):
                with self.assertRaises((ValueError, RuntimeError)) as caught:
                    self.client.connect()
                self.assertNotIn("session-secret", str(caught.exception))
        with patch.object(lp.requests, "get", side_effect=lp.requests.RequestException("session-secret")):
            with self.assertRaisesRegex(RuntimeError, "网络") as caught:
                self.client.connect()
            self.assertNotIn("session-secret", str(caught.exception))

    def test_setup_only_reads_and_allows_a_new_folder_without_creating_it(self):
        options = lp.GitHubOptions("owner/repo", "session-secret", "review/papers", "papers/2026")
        with patch.object(lp.requests, "get", side_effect=[response({}), response({"name": "review/papers"}),
                response(status=404), response([])]) as get, \
                patch.object(lp.requests, "put") as put, patch.object(lp.requests, "post") as post:
            self.assertTrue(self.client.check_destination(options))
        put.assert_not_called()
        post.assert_not_called()
        self.assertIn("review%2Fpapers", get.call_args_list[1].args[0])
        self.assertEqual(get.call_args_list[-1].kwargs["params"]["ref"], "review/papers")

    def test_destination_checks_existing_ancestors_and_rejects_a_file_as_a_folder(self):
        options = lp.GitHubOptions("owner/repo", "session-secret", "main", "README.md/papers")
        with patch.object(lp.requests, "get", side_effect=[response({}), response({}), response(status=404),
                response({"type": "file"})]), self.assertRaisesRegex(ValueError, "同名文件"):
            self.client.check_destination(options)

    def test_folder_browser_only_returns_directories_and_keeps_unicode_paths(self):
        values = [{"type": "dir", "path": "papers/中文"}, {"type": "file", "path": "papers/index.md"}]
        with patch.object(lp.requests, "get", return_value=response(values)) as get:
            self.assertEqual(self.client.folders("owner/repo", "main", "papers"), ["papers/中文"])
        self.assertEqual(get.call_args.kwargs["params"], {"ref": "main"})
        with patch.object(lp.requests, "get", return_value=response({"type": "file"})), self.assertRaisesRegex(ValueError, "文件"):
            self.client.folders("owner/repo", "main", "README.md")

    def test_cancelled_or_missing_credentials_never_make_a_request(self):
        with patch.object(lp.requests, "get") as get:
            with self.assertRaises(lp.ProcessingCancelled):
                lp.GitHubSetupClient("key", lambda: True).connect()
            with self.assertRaises(ValueError):
                lp.GitHubSetupClient("").connect()
        get.assert_not_called()


class GitHubWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"GUI tests need a display: {exc}")
        cls.load = patch.object(application, "load_config", return_value=application.AppConfig())
        cls.save = patch.object(application, "save_config")
        cls.load.start()
        cls.save.start()
        application.configure_unicode_ui_fonts(cls.root)
        application.configure_design_language(cls.root)
        cls.app = application.PaddleOCRBatchGUI(cls.root)
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.root.tk.call("after", "info"):
            cls.root.after_cancel(timer)
        cls.root.destroy()
        cls.load.stop()
        cls.save.stop()

    def setUp(self):
        self.app.change_ui_language("zh")
        self.c = self.app.literature
        self.c.repository.set("original/repo")
        self.c.branch.set("main")
        self.c.folder.set("original")
        self.c.github_token.set("original-secret")
        self.c.upload.set(False)
        self.before = (self.c.config_data(), self.c.github_token.get())
        self.app.workspace_layout.show_settings(2)
        self.c.github_setup.open()
        self.w = self.c.github_setup.wizard
        self.root.update()

    def tearDown(self):
        if self.w.window.winfo_exists():
            self.w.close()
        self.app.workspace_layout.settings.withdraw()
        self.c.upload.set(False)
        self.app.change_ui_language("zh")

    def pump(self, condition, timeout=2):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertTrue(condition())

    def review(self):
        with patch.object(lp.GitHubSetupClient, "connect", return_value={"login": "reader", "repositories": ["reader/papers"]}), \
                patch.object(lp.GitHubSetupClient, "prepare_repository", return_value={"repository": "reader/papers", "default_branch": "master", "branches": ["master", "review"]}), \
                patch.object(lp.GitHubSetupClient, "check_destination", return_value=True):
            self.w.token.set("wizard-session-secret")
            self.w.next()
            self.pump(lambda: self.w.step == 1)
            self.w.repository.set("https://github.com/reader/papers")
            self.w.next()
            self.pump(lambda: self.w.step == 2)
            self.assertEqual(self.w.branch.get(), "master")
            self.w.folder.set("papers/2026")
            self.w.next()
            self.pump(lambda: self.w.step == 3)

    def test_four_steps_only_apply_after_review_and_keep_the_token_out_of_config(self):
        self.review()
        self.assertEqual((self.c.config_data(), self.c.github_token.get()), self.before)
        with patch.object(lp.requests, "put") as put:
            self.w.next()
        put.assert_not_called()
        self.assertFalse(self.w.window.winfo_exists())
        self.assertEqual(self.c.repository.get(), "reader/papers")
        self.assertEqual(self.c.branch.get(), "master")
        self.assertEqual(self.c.folder.get(), "papers/2026")
        self.assertTrue(self.c.upload.get())
        self.assertNotIn("wizard-session-secret", repr(self.app.config))

    def test_cancel_keeps_every_original_setting_and_credential(self):
        self.review()
        self.w.close()
        self.assertEqual((self.c.config_data(), self.c.github_token.get()), self.before)

    def test_config_write_failure_rolls_back_the_destination_and_session_token(self):
        self.review()
        with patch.object(application, "save_config", side_effect=OSError("cannot save config")):
            self.w.next()
        self.assertTrue(self.w.window.winfo_exists())
        self.assertIn("cannot save config", self.w.status.get())
        self.assertEqual((self.c.config_data(), self.c.github_token.get()), self.before)

    def test_changed_destination_must_be_checked_again_before_saving(self):
        self.review()
        self.w.folder.set("different")
        self.w.next()
        self.assertEqual(self.w.step, 2)
        self.assertIn("重新", self.w.status.get())
        self.assertEqual((self.c.config_data(), self.c.github_token.get()), self.before)

    def test_connection_failure_stays_on_the_same_step(self):
        with patch.object(lp.GitHubSetupClient, "connect", side_effect=ValueError("访问凭据无效或已过期，请重新生成并粘贴 Token。")):
            self.w.next()
            self.pump(lambda: not self.w.busy)
        self.assertEqual(self.w.step, 0)
        self.assertIn("Token", self.w.status.get())
        self.assertNotIn("original-secret", self.w.status.get())

    def test_late_result_for_an_old_token_is_discarded(self):
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        def connect():
            entered.set()
            release.wait(1)
            returned.set()
            return {"login": "stale-account", "repositories": ["stale/repo"]}
        with patch.object(lp.GitHubSetupClient, "connect", side_effect=connect):
            self.w.next()
            worker = self.w.worker_thread
            self.assertTrue(entered.wait(0.5))
            self.w.token.set("replacement-token")
            release.set()
            self.assertTrue(returned.wait(0.5))
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.pump(lambda: self.w.events.empty())
        self.assertEqual(self.w.step, 0)
        self.assertNotIn("stale-account", self.w.account.get())

    def test_destroying_wizard_cancels_active_request_and_removes_its_poll_timer(self):
        entered, release = threading.Event(), threading.Event()
        def request(client):
            entered.set()
            release.wait(2)
            return {"login": "late-account", "repositories": []}
        try:
            self.w.run(request, self.w.connected)
            self.assertTrue(entered.wait(1))
            timer = self.w.poll_id
            self.w.window.destroy()
            self.assertTrue(self.w.closed)
            self.assertTrue(self.w.cancel.is_set())
            self.assertNotIn(timer, self.root.tk.call("after", "info"))
            self.assertEqual(self.w.traces, [])
        finally:
            release.set()
            if getattr(self.w, "worker_thread", None):
                self.w.worker_thread.join(2)

    def test_bilingual_wizard_and_folder_browser_work_at_small_sizes(self):
        self.app.change_ui_language("en")
        self.root.update()
        from test_literature_ui import assert_english_captions
        assert_english_captions(self, self.w.window, self.app.workspace_layout.language_selector)
        self.w.window.geometry("480x420")
        self.w.show(2)
        self.w.show_folders("papers", ["papers/中文"])
        self.w.directory_list.selection_set("0")
        self.w.select_folder()
        self.assertEqual(self.w.folder.get(), "papers/中文")
        for step in range(4):
            self.w.show(step)
            self.root.update()
            button = self.w.next_button
            self.assertTrue(button.winfo_viewable())
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), self.w.window.winfo_rootx() + 480)


if __name__ == "__main__":
    unittest.main()
