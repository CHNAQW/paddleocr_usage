"""Content-sized labels and forms that reflow when translated text needs room."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont, ttk

from ui_i18n import LocalizedVar


class AdaptiveLabel(ttk.Label):
    def __init__(self, parent, *, text="", textvariable=None, max_lines=None, **kwargs):
        self.source = textvariable if textvariable is not None else LocalizedVar(master=parent, value=text)
        self.max_lines = max_lines
        self.display = tk.StringVar(master=parent, value=textvariable.get() if textvariable else text)
        kwargs.setdefault("wraplength", 280)
        if "font" not in kwargs:
            font = ttk.Style(parent).lookup(kwargs.get("style", "TLabel"), "font")
            if font:
                kwargs["font"] = font
        # Text does not dictate the form's minimum width. The grid allocates the
        # available width; wrapping determines height, so long captions stay visible.
        kwargs.setdefault("width", 1)
        super().__init__(parent, textvariable=self.display, **kwargs)
        self.scheduler = self._root()
        self.pending = None
        self.trace = self.source.trace_add("write", self.schedule)
        self.bind("<Configure>", self.schedule, add="+")
        self.bind("<Destroy>", self.cleanup, add="+")

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs:
            self.source.set(kwargs.pop("text"))
            self.schedule()
        return super().configure(cnf, **kwargs)

    config = configure

    def schedule(self, *_):
        if self.pending is None:
            self.pending = self.scheduler.after_idle(self.refresh)

    def refresh(self):
        self.pending = None
        width = max(60, self.winfo_width() - 4)
        if self.winfo_width() <= 1:
            self.display.set(self.source.get())
            return
        if int(self.cget("wraplength")) != width:
            self.configure(wraplength=width)
        if self.source is not None:
            text = self.source.get()
            if self.max_lines:
                font = tkfont.Font(self, font=self.cget("font") or ttk.Style(self).lookup(self.cget("style"), "font"))
                text = fit_lines(text, width, self.max_lines, font)
            self.display.set(text)

    def cleanup(self, _event=None):
        if self.pending is not None:
            self.scheduler.after_cancel(self.pending)
            self.pending = None
        if self.trace is not None:
            self.source.trace_remove("write", self.trace)
            self.trace = None


def fit_lines(text, width, maximum, font):
    """Keep compact status labels bounded; their original value remains available."""
    lines, used, end = 1, 0, 0
    for token in re.findall(r"\n|[^\S\n]+|[^\s]+", text):
        if token == "\n":
            lines, used = lines + 1, 0
            if lines > maximum:
                break
            end += 1
            continue
        size = font.measure(token)
        if used and used + size > width and not token.isspace():
            lines, used = lines + 1, 0
        for char in token:
            size = font.measure(char)
            if used + size > width:
                lines, used = lines + 1, 0
            if lines > maximum:
                return text[:max(0, end - 2)].rstrip() + "…"
            used += size
            end += 1
    return text if end == len(text) else text[:max(0, end - 2)].rstrip() + "…"


class ResponsiveForm(ttk.Frame):
    """Align natural-width captions; stack captions above fields when space is tight."""
    def __init__(self, parent, *, style="Paper.TFrame", **kwargs):
        super().__init__(parent, style=style, **kwargs)
        self.scheduler = self._root()
        self.rows = []
        self.traces = []
        self.pending = None
        self.stacked = None
        self.bind("<Configure>", self.schedule, add="+")
        self.bind("<Destroy>", self.cleanup, add="+")

    def add(self, caption, field):
        label = ttk.Label(self, text=caption, style="Card.TLabel" if self.cget("style") == "Paper.TFrame" else "TLabel")
        label.bind("<Configure>", self.schedule, add="+")
        if "width" in field.keys():
            field.configure(width=1)
        variable = field.cget("textvariable") if "textvariable" in field.keys() else ""
        if variable:
            callback = self.register(self.schedule)
            self.tk.call("trace", "add", "variable", variable, "write", callback)
            self.traces.append((variable, callback))
        self.rows.append((label, field))
        self.schedule()
        return field

    def schedule(self, *_):
        if self.pending is None:
            self.pending = self.scheduler.after_idle(self.reflow)

    def reflow(self):
        self.pending = None
        width = self.winfo_width()
        if not self.rows:
            return
        font = tkfont.nametofont("TkDefaultFont", root=self)
        label_width = max(font.measure(str(label.cget("text"))) + 8 for label, _ in self.rows)
        field_width = 200
        for _, field in self.rows:
            if "textvariable" not in field.keys() or not field.cget("textvariable"):
                continue
            value = str(self.tk.getvar(field.cget("textvariable")))
            if "show" in field.keys() and field.cget("show"):
                value = str(field.cget("show")) * min(len(value), 32)
            field_width = max(field_width, font.measure(value) + 40)
        stacked = width < label_width + field_width + 16
        self.columnconfigure(0, weight=1 if stacked else 0)
        self.columnconfigure(1, weight=0 if stacked else 1)
        for index, (label, field) in enumerate(self.rows):
            label.configure(wraplength=max(80, width - 8) if stacked else 0)
            label.grid(row=index * 2 if stacked else index, column=0, sticky="ew" if stacked else "w",
                       padx=0 if stacked else (0, 14), pady=(6, 4) if stacked else (6, 6))
            field.grid(row=index * 2 + 1 if stacked else index, column=0 if stacked else 1,
                       sticky="ew", pady=(0, 8) if stacked else (6, 6))
        self.stacked = stacked

    def cleanup(self, _event=None):
        if self.pending is not None:
            self.scheduler.after_cancel(self.pending)
            self.pending = None
        for variable, callback in self.traces:
            self.tk.call("trace", "remove", "variable", variable, "write", callback)
        self.traces.clear()
