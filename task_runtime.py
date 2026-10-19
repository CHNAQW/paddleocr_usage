"""Bounded background calls and event batches; this module never calls Tk."""
from __future__ import annotations

import queue
import threading
import time

from ui_translations import tr


class TaskCancelled(RuntimeError):
    pass


_network_slots = threading.BoundedSemaphore(6)


def cancellable_call(work, stop=lambda: False, timeout=900, cancelled=TaskCancelled, slot_timeout=5):
    """Stop waiting promptly; late results are disposed and never reach the UI.

    Blocking transports retain their own socket timeout. Bound outstanding calls
    so repeatedly cancelling and restarting cannot create unlimited requests.
    """
    deadline = time.monotonic() + timeout
    def check():
        if stop():
            raise cancelled(tr("用户已停止。"))
        if time.monotonic() >= deadline:
            raise TimeoutError(tr("请求超时，已停止等待；可稍后重试。"))
    check()
    slot_deadline = min(deadline, time.monotonic() + slot_timeout)
    while not _network_slots.acquire(timeout=.05):
        check()
        if time.monotonic() >= slot_deadline:
            raise RuntimeError(tr("仍有网络请求正在结束，请稍后重试。"))
    result = queue.Queue(maxsize=1)
    abandoned = threading.Event()
    delivery_lock = threading.Lock()
    delivered = False
    def dispose(value):
        close = getattr(value, "close", None)
        if callable(close):
            close()
    def worker():
        try:
            try:
                value = (True, work())
            except Exception as exc:
                value = (False, exc)
            with delivery_lock:
                if abandoned.is_set():
                    if value[0]:
                        dispose(value[1])
                else:
                    result.put(value)
        finally:
            _network_slots.release()
    thread = threading.Thread(target=worker, daemon=True)
    try:
        thread.start()
    except BaseException:
        _network_slots.release()
        raise
    try:
        while True:
            check()
            try:
                ok, value = result.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                check()
            except BaseException:
                if ok:
                    dispose(value)
                raise
            delivered = True
            if ok:
                return value
            raise value
    finally:
        if not delivered:
            with delivery_lock:
                abandoned.set()
                try:
                    ok, value = result.get_nowait()
                    if ok:
                        dispose(value)
                except queue.Empty:
                    pass


def drain_events(events, limit=60, seconds=.012):
    """Yield a bounded batch so paint, stop and close events get their turn."""
    deadline = time.monotonic() + seconds
    for _ in range(limit):
        if time.monotonic() >= deadline:
            return
        try:
            yield events.get_nowait()
        except queue.Empty:
            return
