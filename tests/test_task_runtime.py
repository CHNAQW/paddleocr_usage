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
