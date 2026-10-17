"""Chinese/English UI text, with stable option values and live language switching."""
from __future__ import annotations

import tkinter as tk
import weakref
from tkinter import filedialog as _files, messagebox as _messages, simpledialog as _simple, ttk

from ui_translations import (
    Message, join_text, language, source_text, tr, ui_text, set_language as _set_catalog_language,
)


_variables = []


def set_language(locale):
    _set_catalog_language(locale)
    alive = []
    for reference in _variables:
        variable = reference()
        if variable is None:
            continue
        try:
            variable.refresh()
            alive.append(reference)
        except tk.TclError:
            pass
    _variables[:] = alive


class LocalizedVar(tk.StringVar):
    """A display-only variable; paths, keys and model IDs use ordinary StringVar."""
    def __init__(self, master=None, value="", **kwargs):
        self.message = value if isinstance(value, Message) else source_text(value)
        super().__init__(master=master, value=str(tr(value)), **kwargs)
        _variables.append(weakref.ref(self))

    def set(self, value):
        self.message = value if isinstance(value, Message) else source_text(value)
        super().set(str(tr(value)))

    def refresh(self):
        super().set(str(tr(self.message)))


class ChoiceVar(tk.StringVar):
    """Localize an option's label while returning its original stable value."""
    def __init__(self, master=None, value="", **kwargs):
        super().__init__(master=master, value=str(ui_text(value)), **kwargs)
        _variables.append(weakref.ref(self))

    def get(self):
        return source_text(super().get())

    def set(self, value):
        super().set(str(ui_text(value)))

    def refresh(self):
        self.set(self.get())


def localize_widgets(widget):
    """Update captions, menus and enumerated choices in place; never rebuild jobs."""
    options = widget.keys()
    if "text" in options and not ("textvariable" in options and widget.cget("textvariable")):
        widget.configure(text=ui_text(widget.cget("text")))
    if getattr(widget, "localized_field_label", False):
        widget.configure(width=16 if language() == "en" else 10)
    if isinstance(widget, ttk.Combobox) and getattr(widget, "localized_choices", False):
        widget.configure(values=[ui_text(value) for value in widget.cget("values")])
    if isinstance(widget, ttk.Notebook):
        for tab in widget.tabs():
            widget.tab(tab, text=ui_text(widget.tab(tab, "text")))
    if isinstance(widget, tk.Menu):
        end = widget.index("end")
        for index in range(end + 1 if end is not None else 0):
            if widget.type(index) not in {"separator", "tearoff"}:
                widget.entryconfigure(index, label=ui_text(widget.entrycget(index, "label")))
    if isinstance(widget, (tk.Tk, tk.Toplevel)):
        widget.title(tr(widget.localized_title) if hasattr(widget, "localized_title") else ui_text(widget.title()))
    for child in widget.winfo_children():
        localize_widgets(child)


class _Dialogs:
    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        def show(*args, **kwargs):
            args = tuple(tr(value) if isinstance(value, (str, Message)) else value for value in args)
            for key in ("title", "message", "prompt", "detail"):
                if key in kwargs:
                    kwargs[key] = tr(kwargs[key])
            if "filetypes" in kwargs:
                kwargs["filetypes"] = [(tr(label), pattern) for label, pattern in kwargs["filetypes"]]
            return getattr(self.module, name)(*args, **kwargs)
        return show


messagebox = _Dialogs(_messages)
filedialog = _Dialogs(_files)
simpledialog = _Dialogs(_simple)
