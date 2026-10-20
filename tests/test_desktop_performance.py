import queue
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
from tkinter import ttk

from literature_ui import ModelControls
from model_budget import DEFAULT_CONTEXT_LIMIT, effective_limits
from responsive_ui import AdaptiveLabel, ResponsiveForm, fit_lines
from ui_i18n import set_language, widget_text


class CompactTextTests(unittest.TestCase):
    def test_large_unbroken_error_does_not_measure_its_complete_payload(self):
        measured = []
        font = Mock()
        font.measure.side_effect = lambda value: measured.append(len(value)) or len(value) * 8
        text = "文献路径" * 100_000
        visible = fit_lines(text, 240, 2, font)
        self.assertTrue(visible.endswith("…"))
        self.assertLess(len(visible), 100)
        self.assertLess(sum(measured), 9000)
        self.assertEqual(len(text), 400_000)


class DesktopPerformanceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))
        self.root.geometry("620x300")
        self.addCleanup(self.close)

    def close(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()
        set_language("zh")

    def test_output_only_model_metadata_survives_preferences_round_trip(self):
        saved = {"base_url": "https://example.invalid/v1", "model": "output-only",
                 "detected_limits": {"output_limit": 4096}}
        controls = ModelControls(self.root, "model", saved, queue.Queue(), Mock(), Mock())
        self.assertEqual(controls.profile().output_limit, 4096)
        self.assertEqual(controls.limit_value.get(), str(DEFAULT_CONTEXT_LIMIT))
        self.assertEqual(effective_limits(controls.profile()).output_limit, 4096)
        restored = ModelControls(self.root, "restored", controls.config_data(), queue.Queue(), Mock(), Mock())
        self.assertEqual(restored.profile(), controls.profile())
        restored.manual_limit.set(True)
        restored.refresh_limits()
        self.assertEqual(restored.profile().input_limit, DEFAULT_CONTEXT_LIMIT)
        restored.model.set("another-model")
        self.assertEqual(restored.profile().output_limit, 0)

    def test_stable_form_does_not_reapply_grid_but_still_reflows_changed_values(self):
        form = ResponsiveForm(self.root)
        form.pack(fill="x")
        value = tk.StringVar(master=self.root, value="short")
        entry = ttk.Entry(form, textvariable=value)
        form.add("Model", entry)
        self.root.update()
        self.assertFalse(form.stacked)
        with patch.object(entry, "grid", wraps=entry.grid) as grid:
            for _ in range(20):
                form.reflow()
            grid.assert_not_called()
            value.set("very-long-model-name-" * 10)
            self.root.update()
            self.assertTrue(form.stacked)
            self.assertGreater(grid.call_count, 0)
        value.set("short")
        self.root.update()
        self.assertFalse(form.stacked)

    def test_compact_status_retains_full_copy_and_noop_refresh_does_not_rewrite_text(self):
        label = AdaptiveLabel(self.root, text="文献错误 " * 20_000, max_lines=2)
        label.pack(fill="x")
        self.root.update()
        self.assertLess(len(label.display.get()), 200)
        self.assertEqual(widget_text(label), label.source.get())
        with patch.object(label.display, "set", wraps=label.display.set) as changed:
            label.refresh()
            changed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
