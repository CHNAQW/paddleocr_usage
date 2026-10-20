import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

from task_runtime import TaskCancelled, cancellable_call, drain_events


class RuntimeTests(unittest.TestCase):
    def test_work_runs_outside_the_waiting_thread_and_transfers_results(self):
        caller = threading.get_ident()
        identity = cancellable_call(threading.get_ident)
        self.assertNotEqual(identity, caller)
        response = Mock()
        self.assertIs(cancellable_call(lambda: response), response)
        time.sleep(.01)
        response.close.assert_not_called()

    def test_cancel_interrupts_wait_and_disposes_a_late_response(self):
        stop, release, finished = threading.Event(), threading.Event(), threading.Event()
        response = Mock()
        def work():
            release.wait(2)
            finished.set()
            return response
        timer = threading.Timer(.05, stop.set)
        timer.start()
        try:
            started = time.monotonic()
            with self.assertRaises(TaskCancelled):
                cancellable_call(work, stop.is_set)
            self.assertLess(time.monotonic() - started, .5)
        finally:
            release.set()
            timer.join()
        self.assertTrue(finished.wait(1))
        deadline = time.monotonic() + 1
        while not response.close.called and time.monotonic() < deadline:
            time.sleep(.005)
        response.close.assert_called_once()

    def test_deadline_and_early_cancel_do_not_wait_for_a_blocked_transport(self):
        release = threading.Event()
        try:
            with self.assertRaises(TimeoutError):
                cancellable_call(lambda: release.wait(2), timeout=.05)
        finally:
            release.set()
        work = Mock()
        with self.assertRaises(TaskCancelled):
            cancellable_call(work, lambda: True)
        work.assert_not_called()

    def test_worker_errors_are_propagated_and_pool_slots_are_released(self):
        for _ in range(10):
            with self.assertRaisesRegex(ValueError, 'network failure'):
                cancellable_call(Mock(side_effect=ValueError('network failure')))
        self.assertEqual(cancellable_call(lambda: 'usable'), 'usable')

    def test_exhausted_transport_slots_fail_without_launching_more_requests(self):
        work = Mock()
        with patch('task_runtime._network_slots', threading.BoundedSemaphore(0)):
            with self.assertRaises(RuntimeError):
                cancellable_call(work, slot_timeout=.03)
        work.assert_not_called()

    def test_cancel_during_slot_acquisition_does_not_start_a_request(self):
        stop = threading.Event()
        slot = Mock()
        slot.acquire.side_effect = lambda **kwargs: stop.set() or True
        work = Mock()
        with patch('task_runtime._network_slots', slot), self.assertRaises(TaskCancelled):
            cancellable_call(work, stop.is_set)
        work.assert_not_called()
        slot.release.assert_called_once()

    def test_aborted_worker_propagates_without_waiting_for_the_deadline(self):
        class WorkerAbort(BaseException):
            pass
        with self.assertRaises(WorkerAbort):
            cancellable_call(Mock(side_effect=WorkerAbort()), timeout=.2)
        self.assertEqual(cancellable_call(lambda: 'slot released'), 'slot released')

    def test_failed_late_response_cleanup_does_not_leak_a_transport_slot(self):
        release = threading.Event()
        closed = threading.Event()
        def fail_close():
            closed.set()
            raise OSError('socket already closed')
        response = Mock(close=Mock(side_effect=fail_close))
        slot = threading.BoundedSemaphore(1)
        with patch('task_runtime._network_slots', slot):
            try:
                with self.assertRaises(TimeoutError):
                    cancellable_call(lambda: (release.wait(1), response)[1], timeout=.05)
            finally:
                release.set()
            self.assertTrue(closed.wait(1))
            self.assertEqual(cancellable_call(lambda: 'slot released'), 'slot released')

    def test_cancel_at_delivery_does_not_wait_for_blocked_close_or_release_its_slot_early(self):
        close_started, release_close, closed = threading.Event(), threading.Event(), threading.Event()
        caller = threading.get_ident()
        cleanup_thread = []
        def close():
            cleanup_thread.append(threading.get_ident())
            close_started.set()
            release_close.wait(2)
            closed.set()
        response = Mock(close=close)
        checks = 0
        def stop_on_delivery():
            nonlocal checks
            checks += 1
            return checks >= 4
        with patch('task_runtime._network_slots', threading.BoundedSemaphore(1)):
            try:
                started = time.monotonic()
                with self.assertRaises(TaskCancelled):
                    cancellable_call(lambda: response, stop_on_delivery)
                self.assertLess(time.monotonic() - started, .5)
                self.assertTrue(close_started.wait(.5))
                self.assertFalse(closed.is_set())
                self.assertNotEqual(cleanup_thread, [caller])
                work = Mock()
                with self.assertRaises(RuntimeError):
                    cancellable_call(work, slot_timeout=.03)
                work.assert_not_called()
            finally:
                release_close.set()
            self.assertTrue(closed.wait(1))
            self.assertEqual(cancellable_call(lambda: 'ready again'), 'ready again')

    def test_successful_response_is_never_closed_when_stop_changes_after_return(self):
        stop = threading.Event()
        response = Mock()
        with patch('task_runtime._network_slots', threading.BoundedSemaphore(1)):
            self.assertIs(cancellable_call(lambda: response, stop.is_set), response)
            stop.set()
            # A subsequent call proves the original worker acknowledged delivery
            # and returned its slot without disposing the caller-owned response.
            self.assertEqual(cancellable_call(lambda: 'done'), 'done')
        response.close.assert_not_called()

    def test_start_failure_returns_its_slot_for_the_next_call(self):
        import task_runtime
        with patch.object(task_runtime, '_network_slots', threading.BoundedSemaphore(1)):
            with patch.object(task_runtime.threading.Thread, 'start', side_effect=RuntimeError('no thread')):
                with self.assertRaisesRegex(RuntimeError, 'no thread'):
                    cancellable_call(lambda: None)
            self.assertEqual(cancellable_call(lambda: 'ready'), 'ready')

    def test_event_flood_is_bounded_and_remaining_events_are_preserved(self):
        events = queue.Queue()
        for index in range(10000):
            events.put(index)
        batch = list(drain_events(events, limit=25, seconds=1))
        self.assertEqual(batch, list(range(25)))
        self.assertEqual(events.qsize(), 9975)

    def test_slow_event_consumers_yield_to_tk_before_draining_the_queue(self):
        events = queue.Queue()
        for index in range(100):
            events.put(index)
        count = 0
        started = time.monotonic()
        for _ in drain_events(events, seconds=.012):
            count += 1
            time.sleep(.003)
        self.assertLess(count, 10)
        self.assertGreater(events.qsize(), 90)
        self.assertLess(time.monotonic() - started, .1)


if __name__ == '__main__':
    unittest.main()
