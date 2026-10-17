import ast
import json
import string
import tempfile
import tkinter as tk
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import paddleocr_pdf_to_md_gui as application
from ui_i18n import ChoiceVar, LocalizedVar, join_text, set_language, tr
from ui_translations import EN_MESSAGES


class TranslationTests(unittest.TestCase):
    def tearDown(self):
        set_language("zh")

    def test_catalog_preserves_format_fields_and_has_unambiguous_english_labels(self):
        formatter = string.Formatter()
        for source, english in EN_MESSAGES.items():
            with self.subTest(source=source):
                self.assertNotRegex(english, r"[\u4e00-\u9fff]")
                source_fields = sorted((field, spec, conversion) for _, field, spec, conversion in formatter.parse(source) if field)
                english_fields = sorted((field, spec, conversion) for _, field, spec, conversion in formatter.parse(english) if field)
                self.assertEqual(source_fields, english_fields)
        self.assertEqual(len(set(EN_MESSAGES.values())), len(EN_MESSAGES))

    def test_every_literal_ui_message_has_an_english_translation(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("workspace_ui.py", "literature_ui.py", "literature_processing.py", "paddleocr_pdf_to_md_gui.py", "github_ui.py", "model_budget.py"):
            for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" and node.args:
                    source = node.args[0]
                    if isinstance(source, ast.Constant) and isinstance(source.value, str):
                        with self.subTest(file=name, line=node.lineno):
                            self.assertIn(source.value, EN_MESSAGES)

    def test_dynamic_messages_can_be_rendered_again_without_changing_document_data(self):
        filename = "中文原件.md"
        original = tr("文献处理失败：{arg0}；{arg1}", arg0=filename, arg1="HTTP 403")
        combined = tr("手动字数检验完成：\n") + original
        joined = join_text("\n", [combined, tr("完成")])
        set_language("en")
        self.assertEqual(str(tr(original)), "Document processing failed: 中文原件.md; HTTP 403")
        self.assertTrue(str(tr(combined)).startswith("Word-count check complete:\nDocument processing failed:"))
        self.assertTrue(str(tr(joined)).endswith("\nComplete"))
        self.assertEqual(str(tr(filename)), filename)
        self.assertEqual(str(tr("模型：{arg0}", arg0="测试模型-ID")), "Model: 测试模型-ID")
        self.assertEqual(str(tr("开始时间：{arg0:%Y-%m-%d %H:%M:%S}", arg0=datetime(2026, 10, 18))),
                         "Started: 2026-10-18 00:00:00")
        set_language("zh")
        self.assertEqual(str(tr(original)), str(original))

    def test_localized_choices_keep_canonical_values_and_status_refreshes(self):
        interpreter = tk.Tcl()
        source = ChoiceVar(master=interpreter, value="自动检测")
        status = LocalizedVar(master=interpreter, value=tr("正在处理 {arg0}/{arg1}：{arg2}", arg0=1, arg1=2, arg2="原文.md"))
        set_language("en")
        self.assertEqual(interpreter.getvar(source._name), "Auto-detect")
        self.assertEqual(source.get(), "自动检测")
        self.assertEqual(status.get(), "Processing 1/2: 原文.md")
        interpreter.setvar(source._name, "English (en)")
        self.assertEqual(source.get(), "英语 (en)")
        set_language("zh")
        self.assertEqual(interpreter.getvar(source._name), "英语 (en)")
        self.assertIn("正在处理 1/2", status.get())

    def test_language_setting_round_trips_and_old_configs_default_to_chinese(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(application, "CONFIG_DIR", Path(directory)), \
                patch.object(application, "CONFIG_PATH", Path(directory) / "config.json"):
            config = application.AppConfig(ui_language="en")
            application.save_config(config)
            self.assertEqual(application.load_config().ui_language, "en")
            application.CONFIG_PATH.write_text(json.dumps({"model": application.DEFAULT_MODEL}), encoding="utf-8")
            self.assertEqual(application.load_config().ui_language, "zh")

    def test_generated_validation_errors_use_the_selected_language(self):
        from literature_processing import ModelProfile
        set_language("en")
        with self.assertRaisesRegex(ValueError, "Enter an API Key"):
            ModelProfile().validate()
        set_language("zh")
        with self.assertRaisesRegex(ValueError, "请填写 API Key"):
            ModelProfile().validate()


if __name__ == "__main__":
    unittest.main()
