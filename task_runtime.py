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
    slots = _network_slots
    while not slots.acquire(timeout=.05):
        check()
        if time.monotonic() >= slot_deadline:
            raise RuntimeError(tr("仍有网络请求正在结束，请稍后重试。"))
    try:
        # Cancellation may arrive while the previous transport releases a slot.
        # Do not launch another request after the caller has already stopped.
        check()
    except BaseException:
        slots.release()
        raise
    ready, acknowledged = threading.Event(), threading.Event()
    outcome = []
    accepted = False
    def dispose(value):
        close = getattr(value, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # Cleanup errors must not replace cancellation/timeout or
                # prevent the worker from returning its transport slot.
                pass
    def worker():
        try:
            try:
                value = (True, work())
            except BaseException as exc:
                value = (False, exc)
            outcome.append(value)
            ready.set()
            # The caller always acknowledges in finally, including cancellation
            # before this transport finishes. Cleanup remains on this worker:
            # close() can itself block, and must never delay stop/timeout.
            acknowledged.wait()
            if not accepted and value[0]:
                dispose(value[1])
        finally:
            slots.release()
    thread = threading.Thread(target=worker, daemon=True)
    try:
        thread.start()
    except BaseException:
        slots.release()
        raise
    try:
        while True:
            check()
            if not ready.wait(timeout=.05):
                continue
            check()
            ok, value = outcome[0]
            if ok:
                accepted = True
                return value
            raise value
    finally:
        acknowledged.set()


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
