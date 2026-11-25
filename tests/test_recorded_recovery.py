"""Recovery waits across the existing freshness boundary; no hardware access."""
from concurrent.futures import Future
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/control/leap_hand_control'))
from leap_hand_control.hardware_adapter import AdapterError, HandAdapter, HandSample
from leap_hand_control.recorded_recovery import CommunicationRecovery
from leap_hand_control.recorded_backend import RecordedMotionBackend
from test_recorded_backend import command, MemoryRuntime

G = (2048,)*16


def state(at=0., *, current=0.):
    return HandSample(at, G, G, (current,)*16, (5.,)*16, (25,)*16, (1,)*16, (0,)*16)


class Backend:
    simulated = False
    motion_capable = True

    def __init__(self):
        self.sample = state()
        self.communication = dict(active=False, read_in_progress=False)
        self.done = False
        self.stops = 0

    def open(self):
        pass

    def read(self, now):
        return self.sample

    def begin(self, command, now):
        pass

    def completed(self, now):
        return self.done

    def stop(self):
        self.stops += 1

    def communication_status(self, now):
        return self.communication.copy()


class RecoveryTests(unittest.TestCase):
    def moving(self, *, timeout=500.):
        self.backend = Backend()
        self.adapter = HandAdapter(self.backend, command_timeout_s=timeout)
        self.adapter.tick(0.)
        self.future = Future()
        self.adapter.submit(command(), self.future)
        self.adapter.tick(.01)
        self.assertEqual(self.adapter.state, 'MOVING')

    def wait(self, *, start=.05, deadline=1.25):
        self.backend.communication = dict(active=True, started_at=start, deadline=deadline)

    def test_recovery_does_not_extend_deadline_on_repeated_bad_replies(self):
        tracker = CommunicationRecovery()
        tracker.missing(10.)
        tracker.missing(10.8)
        self.assertAlmostEqual(tracker.status(10.9)['deadline'], 11.2)
        tracker.reading(10.9)
        self.assertAlmostEqual(tracker.status(10.91)['read_deadline'], 11.1)
        tracker.read_finished()
        self.assertTrue(tracker.status(11.)['active'])
        tracker.validated()
        self.assertFalse(tracker.status(11.)['active'])

    def test_marked_wait_passes150ms_then_resumes_without_finishing_or_stopping(self):
        self.moving()
        self.wait()
        self.adapter.tick(.4)
        self.assertEqual(self.adapter.state, 'MOVING')
        self.assertFalse(self.future.done())
        self.assertEqual(self.backend.stops, 0)
        status = self.adapter.status(.4)
        self.assertTrue(status['communication_recovering'])
        self.assertFalse(status['healthy'])
        self.assertFalse(status['supporting'])
        self.assertIsNone(self.adapter.sample)
        self.assertEqual(self.backend.sample.acquired_at, 0.)
        self.backend.communication = dict(active=False, read_in_progress=False)
        self.backend.sample = state(.45)
        self.backend.done = True
        self.adapter.tick(.46)
        self.assertTrue(self.future.result()[0])
        self.assertEqual(self.adapter.state, 'HOLDING')
        self.assertEqual(self.adapter.sample.acquired_at, .45)
        self.assertTrue(self.adapter.status(.46)['supporting'])

    def test_unmarked_stale_snapshot_still_faults(self):
        self.moving()
        self.adapter.tick(.3)
        self.assertEqual(self.adapter.state, 'FAULT')
        self.assertEqual(self.future.result()[1], 'STALE_STATE')

    def test_inflight_read_only_gets_its_original200ms_window(self):
        self.moving()
        self.backend.communication = dict(active=False, read_in_progress=True,
            read_started_at=.1, read_deadline=.3)
        self.adapter.tick(.17)
        self.assertFalse(self.future.done())
        self.assertTrue(self.adapter.status(.17)['communication_recovering'])
        self.adapter.tick(.31)
        self.assertEqual(self.future.result()[1], 'COMMUNICATION_RECOVERY_TIMEOUT')

    def test_expired_or_unbounded_wait_faults_without_renewing_cached_sample(self):
        for end in (1.25, 1000.):
            with self.subTest(deadline=end):
                self.moving()
                self.wait(deadline=end)
                self.adapter.tick(1.3)
                self.assertEqual(self.adapter.state, 'FAULT')
                self.assertEqual(self.future.result()[1], 'COMMUNICATION_RECOVERY_TIMEOUT')
                self.assertEqual(self.backend.stops, 1)
                self.assertIsNone(self.adapter.sample)

    def test_cancel_takes_priority_over_stale_telemetry_during_recovery(self):
        self.moving()
        self.wait()
        self.adapter.tick(.3)
        self.adapter.cancel(self.future)
        self.adapter.tick(.31)
        self.assertEqual(self.future.result()[1], 'CANCELLED')
        self.assertEqual(self.backend.stops, 1)
        self.assertFalse(self.adapter.communication_recovering)

    def test_command_timeout_is_not_paused_by_communication_wait(self):
        self.moving(timeout=.2)
        self.wait()
        self.adapter.tick(.3)
        self.assertEqual(self.future.result()[1], 'HAND_TIMEOUT')

    def test_explicit_stop_clears_recovery_status_after_worker_shutdown(self):
        self.moving()
        self.wait()
        self.adapter.tick(.3)
        self.backend.stopped = True
        self.adapter.request_clear()
        self.adapter.tick(.31)
        self.assertEqual(self.adapter.state, 'STOPPED')
        self.assertFalse(self.adapter.status(.31)['communication_recovering'])
        self.assertEqual(self.future.result()[1], 'CANCELLED')

    def test_new_unsafe_snapshot_is_not_ignored_during_recovery(self):
        self.moving()
        self.wait()
        self.backend.sample = state(.3, current=600.)
        self.adapter.tick(.3)
        self.assertEqual(self.adapter.state, 'FAULT')
        self.assertIn('current', self.future.result()[2])

    def test_wait_during_G_hold_revokes_support_and_refuses_new_command(self):
        self.moving()
        self.backend.done = True
        self.adapter.tick(.02)
        self.assertTrue(self.future.result()[0])
        self.wait()
        self.adapter.tick(.3)
        self.assertFalse(self.adapter.status(.3)['supporting'])
        with self.assertRaises(AdapterError):
            self.adapter.submit(command(step_index=2), Future())
        self.assertEqual(self.backend.stops, 0)

    def test_real_backend_forwards_worker_wait_and_keeps_the_same_action_alive(self):
        class RecoveringRuntime(MemoryRuntime):
            def __init__(self):
                super().__init__(duration=.6)
                self.communication = CommunicationRecovery()

            def communication_status(self, now):
                return self.communication.status(now)

        runtime = RecoveringRuntime()
        backend = RecordedMotionBackend(armed=True, runtime_factory=lambda:runtime)
        self.addCleanup(backend.close)
        core = HandAdapter(backend)
        core.tick(time.monotonic())
        future = Future()
        core.submit(command(), future)
        core.tick(time.monotonic())
        runtime.communication.missing(time.monotonic())
        runtime.pause.set()
        time.sleep(.36)
        core.tick(time.monotonic())
        self.assertEqual(core.state, 'MOVING')
        self.assertFalse(future.done())
        self.assertTrue(core.status(time.monotonic())['communication_recovering'])
        self.assertNotIn('OFF', runtime.log)
        runtime.pause.clear()
        time.sleep(.01)  # Fresh worker sample before the validation notification.
        runtime.communication.validated()
        deadline = time.monotonic()+1.
        while not future.done() and time.monotonic() < deadline:
            core.tick(time.monotonic())
            time.sleep(.003)
        self.assertTrue(future.done())
        self.assertTrue(future.result()[0])
        self.assertTrue(core.status(time.monotonic())['supporting'])
        self.assertEqual(runtime.log.count('ON'), 1)
        self.assertNotIn('OFF', runtime.log)


if __name__ == '__main__':
    unittest.main()
