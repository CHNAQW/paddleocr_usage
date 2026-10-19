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


def copy_text(widget, text):
    """Copy explicitly requested text, keeping an existing clipboard if empty."""
    if not str(text):
        return False
    try:
        widget.clipboard_clear()
        widget.clipboard_append(str(text))
        widget.update_idletasks()
        return True
    except tk.TclError:
        widget.bell()
        return False


def widget_text(widget, selected=False):
    """Read disabled previews and the unabridged source of adaptive labels."""
    if isinstance(widget, tk.Text):
        if selected:
            return widget.get("sel.first", "sel.last") if widget.tag_ranges("sel") else ""
        return widget.get("1.0", "end-1c")
    if isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox)):
        if selected:
            return widget.get()[int(widget.index("sel.first")):int(widget.index("sel.last"))] if widget.selection_present() else ""
        return widget.get()
    if isinstance(widget, ttk.Treeview):
        rows = widget.selection() if selected else widget.get_children()
        return "\n".join("\t".join(str(value) for value in
                                  ([widget.item(row, "text")] if widget.item(row, "text") else []) + list(widget.item(row, "values")))
                         for row in rows)
    if isinstance(widget, (tk.Label, ttk.Label)):
        source = getattr(widget, "source", None)
        if source is not None:
            return source.get()
        variable = widget.cget("textvariable")
        return str(widget.getvar(variable)) if variable else str(widget.cget("text"))
    return ""


def enable_copy(widget):
    supported = (tk.Text, tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox,
                 tk.Label, ttk.Label, ttk.Treeview)
    if not isinstance(widget, supported) or getattr(widget, "_copy_support", False):
        return
    widget._copy_support = True
    widget._copy_menu = None
    is_label = isinstance(widget, (tk.Label, ttk.Label))
    is_entry = isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox))

    def copy(_event=None, all_text=False):
        text = widget_text(widget, selected=not all_text)
        if not text and (is_label or isinstance(widget, tk.Text)):
            text = widget_text(widget)
        copy_text(widget, text)
        return "break"

    def select_all(_event=None):
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
        elif is_entry:
            widget.selection_range(0, "end")
        elif isinstance(widget, ttk.Treeview):
            widget.selection_set(widget.get_children())
        return "break"

    def popup(event):
        if widget._copy_menu is None:
            menu = tk.Menu(widget, tearoff=False)
            menu.add_command(command=copy)
            menu.add_command(command=lambda: copy(all_text=True))
            if not is_label:
                menu.add_separator()
                menu.add_command(command=select_all)
            if is_entry or isinstance(widget, tk.Text):
                menu.add_separator()
                menu.add_command(command=lambda: widget.event_generate("<<Cut>>"))
                menu.add_command(command=lambda: widget.event_generate("<<Paste>>"))
            widget._copy_menu = menu
        menu = widget._copy_menu
        captions = ["复制", "复制全部"] + ([] if is_label else [None, "全选"])
        if is_entry or isinstance(widget, tk.Text):
            captions += [None, "剪切", "粘贴"]
        for index, caption in enumerate(captions):
            if caption:
                menu.entryconfigure(index, label=tr(caption))
        if is_entry or isinstance(widget, tk.Text):
            editable = str(widget.cget("state")) == "normal"
            menu.entryconfigure(len(captions) - 2, state="normal" if editable and widget_text(widget, True) else "disabled")
            menu.entryconfigure(len(captions) - 1, state="normal" if editable else "disabled")
        widget.focus_set()
        previous_grab = widget.grab_current()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.grab_set()
        return "break"

    for event in ("<Control-c>", "<Control-Insert>", "<<Copy>>"):
        widget.bind(event, copy)
    if not is_label:
        widget.bind("<Control-a>", select_all)
    widget.bind("<Button-3>", popup)


def localize_widgets(widget):
    enable_copy(widget)
    if isinstance(widget, ttk.Combobox) and not getattr(widget, "_wheel_guard", False):
        def wheel(event, combo=widget):
            popup = str(combo) + ".popdown"
            if combo.tk.call("winfo", "exists", popup) and combo.tk.call("winfo", "ismapped", popup):
                return
            parent = combo.master
            while parent is not None:
                if isinstance(parent, tk.Canvas):
                    up = getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0
                    parent.yview_scroll(-3 if up else 3, "units")
                    break
                parent = getattr(parent, "master", None)
            return "break"
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(event, wheel, add="+")
        widget._wheel_guard = True
    """Update captions, menus and enumerated choices in place; never rebuild jobs."""
    options = widget.keys()
    if "text" in options and not ("textvariable" in options and widget.cget("textvariable")):
        widget.configure(text=ui_text(widget.cget("text")))
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
    if hasattr(widget, "reflow"):
        widget.reflow()


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
            if self.module is _messages and name in {"showerror", "showwarning", "showinfo"}:
                return copyable_notice(*args, **kwargs)
            return getattr(self.module, name)(*args, **kwargs)
        return show


def copyable_notice(title="", message="", *, detail="", parent=None, **_options):
    """Selectable messages with an explicit copy action; confirmation dialogs keep native semantics."""
    temporary = None
    if parent is None:
        parent = tk._default_root
        if parent is None:
            temporary = parent = tk.Tk()
            parent.withdraw()
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent.winfo_toplevel())
    dialog.geometry("620x340")
    dialog.minsize(380, 220)
    dialog.columnconfigure(0, weight=1)
    dialog.rowconfigure(0, weight=1)
    previous_grab = dialog.grab_current()
    frame = ttk.Frame(dialog, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    body = tk.Text(frame, wrap="word", width=1, height=6, relief="flat", padx=8, pady=8,
                   background=ttk.Style(frame).lookup("TFrame", "background") or parent.cget("background"),
                   foreground=ttk.Style(frame).lookup("TLabel", "foreground") or "#25332e")
    content = str(message) + ("\n\n" + str(detail) if detail else "")
    body.insert("1.0", content)
    body.configure(state="disabled")
    body.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(frame, command=body.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    body.configure(yscrollcommand=scrollbar.set)
    actions = ttk.Frame(frame)
    actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    actions.columnconfigure(1, weight=1)
    ttk.Button(actions, text=tr("复制信息"), command=lambda: copy_text(dialog, str(title) + "\n\n" + content)).grid(row=0, column=0)
    close = ttk.Button(actions, text=tr("关闭"), command=dialog.destroy)
    close.grid(row=0, column=2)
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    dialog.bind("<Return>", lambda _event: dialog.destroy())
    localize_widgets(dialog)
    dialog.grab_set()
    body.focus_set()
    try:
        dialog.wait_window()
    finally:
        if previous_grab is not None and previous_grab.winfo_exists():
            previous_grab.grab_set()
        if temporary is not None:
            temporary.destroy()
    return "ok"


messagebox = _Dialogs(_messages)
filedialog = _Dialogs(_files)
simpledialog = _Dialogs(_simple)
