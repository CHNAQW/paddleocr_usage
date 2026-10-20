"""Chinese/English UI text, with stable option values and live language switching."""
from __future__ import annotations

import tkinter as tk
import time
import weakref
from tkinter import filedialog as _files, messagebox as _messages, simpledialog as _simple, ttk

from ui_translations import (
    Message, join_text, language, source_text, tr, ui_text, set_language as _set_catalog_language,
)


_variables = weakref.WeakValueDictionary()


def set_language(locale):
    _set_catalog_language(locale)
    for variable in list(_variables.values()):
        try:
            variable.refresh()
        except tk.TclError:
            _variables.pop(id(variable), None)


class LocalizedVar(tk.StringVar):
    """A display-only variable; paths, keys and model IDs use ordinary StringVar."""
    def __init__(self, master=None, value="", **kwargs):
        self.message = value if isinstance(value, Message) else source_text(value)
        super().__init__(master=master, value=str(tr(value)), **kwargs)
        _variables[id(self)] = self

    def set(self, value):
        self.message = value if isinstance(value, Message) else source_text(value)
        super().set(str(tr(value)))

    def refresh(self):
        super().set(str(tr(self.message)))


class ChoiceVar(tk.StringVar):
    """Localize an option's label while returning its original stable value."""
    def __init__(self, master=None, value="", **kwargs):
        super().__init__(master=master, value=str(ui_text(value)), **kwargs)
        _variables[id(self)] = self

    def get(self):
        return source_text(super().get())

    def set(self, value):
        super().set(str(ui_text(value)))

    def refresh(self):
        self.set(self.get())


def copy_text(widget, text):
    """Copy explicitly requested text, keeping an existing clipboard if empty."""
    _cancel_pending_copy(widget._root())
    if not str(text):
        return False
    try:
        widget.clipboard_clear()
        widget.clipboard_append(str(text))
        return True
    except tk.TclError:
        widget.bell()
        return False


def _entry_value(widget):
    value = str(widget.get())
    mask = str(widget.cget("show")) if "show" in widget.keys() else ""
    return mask[:1] * len(value) if mask else value


def _tree_rows(widget, parent=""):
    stack = [iter(widget.get_children(parent))]
    while stack:
        try:
            row = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        yield row
        children = widget.get_children(row)
        if children:
            stack.append(iter(children))


def _tree_lines(widget, rows, headings=False):
    generation = getattr(widget, "_copy_generation", 0)
    all_columns = tuple(map(str, widget.cget("columns")))
    columns = all_columns
    displayed = tuple(map(str, widget.cget("displaycolumns")))
    if displayed != ("#all",):
        columns = tuple(columns[int(c)] if str(c).isdigit() else str(c) for c in displayed)
    shown = tuple(map(str, widget.cget("show")))
    tree = "tree" in shown
    indices = [all_columns.index(column) for column in columns]
    if headings and "headings" in shown:
        headers = ([str(widget.heading("#0", "text"))] if tree else [])
        headers += [str(widget.heading(column, "text")) for column in columns]
        if any(headers):
            yield "\t".join(headers)
    for row in rows:
        if getattr(widget, "_copy_generation", 0) != generation:
            raise tk.TclError("Table changed while copying")
        item = widget.item(row)
        stored = item["values"]
        values = ([str(item["text"])] if tree else [])
        values += [str(stored[index]) if index < len(stored) else "" for index in indices]
        yield "\t".join(values)


def _tree_text(widget, rows, headings=False):
    return "\n".join(_tree_lines(widget, rows, headings))


def invalidate_copy(widget):
    """A rebuilt table may reuse row IDs; never mix two generations of rows."""
    widget._copy_generation = getattr(widget, "_copy_generation", 0) + 1


def widget_text(widget, selected=False):
    """Read complete display text; explicit field selections retain native copying."""
    if isinstance(widget, tk.Text):
        if selected:
            return widget.get("sel.first", "sel.last") if widget.tag_ranges("sel") else ""
        full_text = getattr(widget, "_copy_full_text", None)
        return str(full_text()) if callable(full_text) else widget.get("1.0", "end-1c")
    if isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox)):
        value = _entry_value(widget)
        if selected:
            # An explicit selection in a key field is a deliberate copy request.
            return str(widget.get())[int(widget.index("sel.first")):int(widget.index("sel.last"))] if widget.selection_present() else ""
        return value
    if isinstance(widget, ttk.Treeview):
        return _tree_text(widget, widget.selection() if selected else _tree_rows(widget), headings=not selected)
    if isinstance(widget, tk.Listbox):
        indices = widget.curselection() if selected else range(widget.size())
        return "\n".join(str(widget.get(index)) for index in indices)
    if isinstance(widget, ttk.Notebook):
        tabs = ([widget.select()] if widget.select() else []) if selected else widget.tabs()
        return "\n".join(str(widget.tab(tab, "text")) for tab in tabs)
    if isinstance(widget, tk.Menu):
        end = widget.index("end")
        indices = [widget.index("active")] if selected else range((end + 1) if end is not None else 0)
        return "\n".join(str(widget.entrycget(index, "label")) for index in indices
                         if index is not None and widget.type(index) not in {"separator", "tearoff"})
    if isinstance(widget, tk.Canvas):
        return "\n".join(str(widget.itemcget(item, "text")) for item in widget.find_all()
                         if widget.type(item) == "text")
    if isinstance(widget, (tk.Tk, tk.Toplevel)):
        return str(widget.title())
    source = getattr(widget, "source", None)
    if callable(getattr(source, "get", None)):
        return str(source.get())
    options = widget.keys()
    if "text" in options:
        variable = widget.cget("textvariable") if "textvariable" in options else ""
        return str(widget.getvar(variable)) if variable else str(widget.cget("text"))
    return ""


def _interface_parts(widget):
    title = widget.winfo_toplevel().title()
    if title:
        yield str(title)

    def collect(item):
        yield None  # Empty layout widgets also count toward each GUI work slice.
        if getattr(item, "_copy_support_menu", False):
            return
        if isinstance(item, (tk.Tk, tk.Toplevel)) and item is not widget:
            return  # A separate dialog has its own scope and shortcut.
        if isinstance(item, ttk.Notebook):
            for tab in item.tabs():
                yield "[" + str(item.tab(tab, "text")) + "]"
                yield from collect(item.nametowidget(tab))
            return
        if isinstance(item, ttk.Treeview):
            yield from _tree_lines(item, _tree_rows(item), headings=True)
        elif not isinstance(item, (tk.Tk, tk.Toplevel)):
            value = widget_text(item)
            if value:
                yield value
        if isinstance(item, ttk.Combobox):
            # The selected value and the complete list are both interface text.
            values = [str(value) for value in item.cget("values")]
            if item.cget("show"):
                values = [str(item.cget("show"))[:1] * len(value) for value in values]
            if values:
                yield "\n".join(values)
        for child in item.winfo_children():
            yield from collect(child)
    yield from collect(widget)


def interface_text(widget):
    """Synchronous text export for callers; UI copy actions use bounded work slices."""
    return "\n".join(part for part in _interface_parts(widget) if part is not None)


def _cancel_pending_copy(root):
    job = getattr(root, "_pending_text_copy", None)
    root._pending_text_copy = None
    if job and job["pending"] is not None:
        try:
            root.after_cancel(job["pending"])
        except tk.TclError:
            pass


def _copy_parts(widget, parts):
    """Keep Tk reads on its owner thread while allowing large tables to yield."""
    root = widget._root()
    _cancel_pending_copy(root)
    job = {"pending": None}
    root._pending_text_copy = job
    parts, collected = iter(parts), []

    def advance():
        if getattr(root, "_pending_text_copy", None) is not job:
            return
        job["pending"] = None
        deadline = time.monotonic() + .008
        try:
            if not widget.winfo_exists():
                _cancel_pending_copy(root)
                return
            for _ in range(128):
                part = next(parts)
                if part is not None:
                    collected.append(part)
                if time.monotonic() >= deadline:
                    break
        except StopIteration:
            copy_text(widget, "\n".join(collected))
            return
        except tk.TclError:
            # A closed window or replaced table must not overwrite the clipboard.
            _cancel_pending_copy(root)
            return
        job["pending"] = root.after(1, advance)

    advance()
    return True


def copy_interface_text(widget):
    return _copy_parts(widget, _interface_parts(widget))


def _popup_menu(menu, owner, event):
    previous = str(owner.tk.call("grab", "current", owner))
    grab_kind = str(owner.tk.call("grab", "status", previous)) if previous else ""
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        try:
            menu.grab_release()
            if previous and owner.tk.call("winfo", "exists", previous):
                if grab_kind == "global":
                    owner.tk.call("grab", "set", "-global", previous)
                else:
                    owner.tk.call("grab", "set", previous)
        except tk.TclError:
            pass  # The owning dialog may have closed while its menu was open.
    return "break"


def _install_copy_shortcuts(widget):
    root = widget._root()
    if getattr(root, "_interface_copy_support", False):
        return
    root._interface_copy_support = True

    def whole_window(event):
        target = event.widget if isinstance(event.widget, tk.Misc) else root
        copy_interface_text(target.winfo_toplevel())
        return "break"

    def mapped(event):
        if isinstance(event.widget, tk.Misc):
            enable_copy(event.widget)

    def dropdown_copy(event, popup=False):
        # ttk creates its popup listbox in Tcl, without a Python widget wrapper.
        path = str(event.widget)
        try:
            indices = root.tk.splitlist(root.tk.call(path, "curselection"))
            if popup:
                clicked = int(root.tk.call(path, "nearest", event.y))
                if str(clicked) not in {str(index) for index in indices}:
                    indices = (clicked,)
            text = "\n".join(str(root.tk.call(path, "get", index)) for index in indices)
            if not text:
                text = "\n".join(map(str, root.tk.splitlist(root.tk.call(path, "get", 0, "end"))))
            if not popup:
                copy_text(root, text)
                return "break"
            menu = getattr(root, "_dropdown_copy_menu", None)
            if menu is None:
                menu = root._dropdown_copy_menu = tk.Menu(root, tearoff=False)
                menu._copy_support_menu = True
                menu.add_command()
                menu.add_command()
            all_text = "\n".join(map(str, root.tk.splitlist(root.tk.call(path, "get", 0, "end"))))
            menu.entryconfigure(0, label=tr("复制"), command=lambda: copy_text(root, text))
            menu.entryconfigure(1, label=tr("复制全部"), command=lambda: copy_text(root, all_text))
            # A combobox's native popup owns a grab outside this menu. Closing
            # it preserves the selected value and lets the copy menu receive clicks.
            root.tk.call("ttk::combobox::Unpost", path.rsplit(".popdown", 1)[0])
            return _popup_menu(menu, root, event)
        except tk.TclError:
            return "break"

    root.bind_all("<Control-Shift-C>", whole_window, add="+")
    root.bind_all("<<CopyInterface>>", whole_window, add="+")
    root.bind_all("<Map>", mapped, add="+")
    for sequence in ("<Control-c>", "<Control-Insert>", "<<Copy>>"):
        root.bind_class("ComboboxListbox", sequence, dropdown_copy, add="+")
    root.bind_class("ComboboxListbox", "<Button-3>", lambda event: dropdown_copy(event, True), add="+")


def enable_copy(widget):
    _install_copy_shortcuts(widget)
    supported = (tk.Text, tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox,
                 tk.Label, ttk.Label, tk.Message, ttk.Treeview, tk.Listbox, ttk.Notebook,
                 tk.LabelFrame, ttk.LabelFrame, tk.Button, ttk.Button, tk.Checkbutton,
                 ttk.Checkbutton, tk.Radiobutton, ttk.Radiobutton, tk.Menubutton,
                 ttk.Menubutton, tk.Menu, tk.Canvas,
                 tk.Tk, tk.Toplevel)
    if (not isinstance(widget, supported) or getattr(widget, "_copy_support", False)
            or getattr(widget, "_copy_support_menu", False)):
        return
    widget._copy_support = True
    widget._copy_menu = None
    is_entry = isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox))
    selectable = is_entry or isinstance(widget, (tk.Text, ttk.Treeview, tk.Listbox))
    context_value = None
    context_rows = None

    def copy(_event=None, all_text=False, context=False):
        try:
            if isinstance(widget, ttk.Treeview) and not (context and not all_text and context_value is not None):
                rows = context_rows if context and not all_text and context_rows is not None else (
                    () if all_text else widget.selection())
                _copy_parts(widget, _tree_lines(widget, rows or _tree_rows(widget), headings=not rows))
                return "break"
            text = context_value if context and not all_text and context_value is not None else widget_text(widget, selected=not all_text)
            if not text:
                text = widget_text(widget)
            copy_text(widget, text)
        except tk.TclError:
            pass
        return "break"

    def select_all(_event=None):
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
        elif is_entry:
            widget.selection_range(0, "end")
        elif isinstance(widget, ttk.Treeview):
            widget.selection_set(tuple(_tree_rows(widget)))
        elif isinstance(widget, tk.Listbox):
            widget.selection_set(0, "end")
        return "break"

    def popup(event):
        nonlocal context_value, context_rows
        context_value = None
        context_rows = None
        if isinstance(widget, ttk.Treeview):
            if widget.identify_region(event.x, event.y) == "heading":
                context_value = str(widget.heading(widget.identify_column(event.x), "text"))
            else:
                row = widget.identify_row(event.y)
                if row:
                    context_rows = widget.selection() if row in widget.selection() else (row,)
        elif isinstance(widget, ttk.Notebook):
            try:
                context_value = str(widget.tab(widget.index("@%s,%s" % (event.x, event.y)), "text"))
            except tk.TclError:
                pass
        elif isinstance(widget, tk.Menu):
            try:
                index = widget.index("@%s" % event.y)
                if index is not None and widget.type(index) not in {"separator", "tearoff"}:
                    context_value = str(widget.entrycget(index, "label"))
            except tk.TclError:
                pass
        if widget._copy_menu is None:
            menu = tk.Menu(widget, tearoff=False)
            menu._copy_support_menu = True
            menu.add_command(command=lambda: copy(context=True))
            menu.add_command(command=lambda: copy(all_text=True))
            if selectable:
                menu.add_separator()
                menu.add_command(command=select_all)
            if is_entry or isinstance(widget, tk.Text):
                menu.add_separator()
                menu.add_command(command=lambda: widget.event_generate("<<Cut>>"))
                menu.add_command(command=lambda: widget.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(command=lambda: copy_interface_text(widget.winfo_toplevel()))
            widget._copy_menu = menu
        menu = widget._copy_menu
        captions = ["复制", "复制全部"] + ([None, "全选"] if selectable else [])
        if is_entry or isinstance(widget, tk.Text):
            captions += [None, "剪切", "粘贴"]
        captions += [None, "复制界面文字"]
        for index, caption in enumerate(captions):
            if caption:
                menu.entryconfigure(index, label=tr(caption))
        if is_entry or isinstance(widget, tk.Text):
            editable = str(widget.cget("state")) == "normal"
            menu.entryconfigure(5, state="normal" if editable and widget_text(widget, True) else "disabled")
            menu.entryconfigure(6, state="normal" if editable else "disabled")
        widget.focus_set()
        return _popup_menu(menu, widget, event)

    for event in ("<Control-c>", "<Control-Insert>", "<<Copy>>"):
        widget.bind(event, copy)
    if selectable:
        widget.bind("<Control-a>", select_all)
    widget.bind("<Button-3>", popup)

def localize_widgets(widget):
    _install_copy_shortcuts(widget)
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
            if self.module is _messages and name in {"askyesno", "askyesnocancel", "askokcancel", "askretrycancel", "askquestion"}:
                return copyable_confirmation(name, *args, **kwargs)
            return getattr(self.module, name)(*args, **kwargs)
        return show


def copyable_notice(title="", message="", *, detail="", parent=None, **_options):
    return _copyable_dialog(title, message, detail=detail, parent=parent,
                            choices=(("关闭", "ok"),), cancel="ok", default="ok")


def copyable_confirmation(kind, title="", message="", *, detail="", parent=None, default=None, **_options):
    """Copyable questions with the same return values as tkinter.messagebox."""
    definitions = {
        "askyesno": ((("是", "yes"), ("否", "no")), "no"),
        "askyesnocancel": ((("是", "yes"), ("否", "no"), ("取消", "cancel")), "cancel"),
        "askokcancel": ((("确定", "ok"), ("取消", "cancel")), "cancel"),
        "askretrycancel": ((("重试", "retry"), ("取消", "cancel")), "cancel"),
        "askquestion": ((("是", "yes"), ("否", "no")), "no"),
    }
    choices, cancel = definitions[kind]
    answer = _copyable_dialog(title, message, detail=detail, parent=parent, choices=choices,
                              cancel=cancel, default=default or cancel)
    if kind == "askquestion":
        return answer
    if kind == "askyesnocancel" and answer == "cancel":
        return None
    return answer in {"yes", "ok", "retry"}


def _copyable_dialog(title, message, *, detail, parent, choices, cancel, default):
    """One selectable dialog body shared by notices and confirmations."""
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
    preview = content
    if len(preview) > 100000:
        preview = preview[:100000] + "\n" + str(tr("预览已截短；使用复制信息查看完整内容。"))
    body._copy_full_text = lambda: content
    body.insert("1.0", preview)
    body.configure(state="disabled")
    body.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(frame, command=body.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    body.configure(yscrollcommand=scrollbar.set)
    actions = ttk.Frame(frame)
    actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    actions.columnconfigure(1, weight=1)
    copy_button = ttk.Button(actions, text=tr("复制信息"),
                             command=lambda: copy_text(dialog, str(title) + "\n\n" + content))
    copy_button.grid(row=0, column=0)
    copy_button.bind("<Return>", lambda _event: (copy_button.invoke(), "break")[1])
    answer = cancel

    def finish(value):
        nonlocal answer
        answer = value
        dialog.destroy()

    for index, (caption, value) in enumerate(choices):
        button = ttk.Button(actions, text=tr(caption), command=lambda selected=value: finish(selected))
        button.grid(row=0, column=index + 2, padx=(6, 0))
        button.bind("<Return>", lambda _event, selected=value: (finish(selected), "break")[1])
    default = default if default in {value for _, value in choices} else cancel
    dialog.bind("<Escape>", lambda _event: finish(cancel))
    dialog.bind("<Return>", lambda _event: finish(default))
    dialog.protocol("WM_DELETE_WINDOW", lambda: finish(cancel))
    localize_widgets(dialog)
    dialog.deiconify()
    dialog.lift()
    dialog.grab_set()
    body.focus_force()
    try:
        dialog.wait_window()
    finally:
        try:
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.grab_set()
        except tk.TclError:
            pass  # The application may have closed while the modal was open.
        if temporary is not None:
            try:
                temporary.destroy()
            except tk.TclError:
                pass
    return answer


messagebox = _Dialogs(_messages)
filedialog = _Dialogs(_files)
simpledialog = _Dialogs(_simple)
