"""The real threaded backend/adapter lifecycle with an in-memory I/O runtime."""
from concurrent.futures import Future
from pathlib import Path
from queue import Empty
import sys
from threading import Event, get_ident
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/control/leap_hand_control'))
from leap_hand_control.hardware_adapter import AdapterError, HandAdapter, HandSample
from leap_hand_control.recorded_backend import RecordedMotionBackend

G = (2048,)*16


def command(kind='horizontal', **extra):
    value = dict(scan_id='scan', execution_id='execution', move_index=1,
                 step_index=1,
                 primitive_id='rotate_'+kind+'_and_support', dry_run=False,
                 policy_id='', policy_action_values=[])
    value.update(extra)
    return value


class MemoryRuntime:
    def __init__(self, *, duration=.015, confirm_stop=True):
        self.duration, self.confirm_stop = duration, confirm_stop
        self.shutdown_confirmed = False
        self.log, self.thread_ids = [], set()
        self.fail, self.pause = Event(), Event()

    def run(self, stop, requests, sample, completed, ready):
        self.thread_ids.add(get_ident())
        self.log.append('open')
        active = None
        torque = 0
        sample(HandSample(time.monotonic(), G, G, (0.,)*16,
                          (5.,)*16, (25,)*16, (0,)*16, (0,)*16))
        ready(G)
        try:
            while not stop.is_set():
                if self.fail.is_set():
                    raise RuntimeError('injected complete-state read failure')
                if active is None:
                    try:
                        active = (requests.get_nowait(), time.monotonic()+self.duration)
                        if not torque:
                            self.log.append('ON')
                        torque = 1
                        self.log.append(active[0][1])
                    except Empty:
                        pass
                if not self.pause.is_set():
                    sample(HandSample(time.monotonic(), G, G, (0.,)*16,
                                      (5.,)*16, (25,)*16, (torque,)*16, (0,)*16))
                if active and time.monotonic() >= active[1]:
                    completed(active[0][0])
                    active = None
                stop.wait(.002)
        finally:
            if torque:
                self.log.append('OFF')
            self.log.append('close')
            self.shutdown_confirmed = self.confirm_stop


class BackendTests(unittest.TestCase):
    def ready(self, runtime=None):
        self.runtime = runtime or MemoryRuntime()
        self.backend = RecordedMotionBackend(armed=True, runtime_factory=lambda: self.runtime)
        self.core = HandAdapter(self.backend)
        self.addCleanup(self.backend.close)
        self.core.tick(time.monotonic())
        self.assertEqual(self.core.state, 'IDLE')
        return self.core

    def until(self, predicate, timeout=1.):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            self.core.tick(time.monotonic())
            if predicate():
                return
            time.sleep(.003)
        self.fail('Timed out waiting for memory runtime')

    def test_unarmed_never_starts_io_worker(self):
        calls = []
        backend = RecordedMotionBackend(runtime_factory=lambda: calls.append(1))
        with self.assertRaisesRegex(AdapterError, 'explicitly true'):
            backend.open()
        self.assertEqual(calls, [])
        self.assertIsNone(backend.thread)

    def test_open_only_reads_until_an_explicit_physical_request(self):
        core = self.ready()
        self.assertEqual(self.runtime.log, ['open'])
        self.assertFalse(core.status(time.monotonic())['supporting'])
        self.assertEqual(self.runtime.thread_ids, {self.backend.thread.ident})
        self.assertNotIn(get_ident(), self.runtime.thread_ids)

    def test_completion_keeps_hold_and_next_command_reuses_one_session(self):
        core = self.ready()
        for step, kind in enumerate(('horizontal', 'vertical'), 1):
            future = Future()
            core.submit(command(kind, step_index=step), future)
            self.until(future.done)
            self.assertTrue(future.result()[0])
            self.assertTrue(core.status(time.monotonic())['supporting'])
            self.assertNotIn('OFF', self.runtime.log)
        self.assertEqual(self.runtime.log.count('open'), 1)
        self.assertEqual(self.runtime.log.count('ON'), 1)
        core.request_clear()
        core.tick(time.monotonic())
        self.assertEqual(core.state, 'STOPPED')
        self.assertFalse(core.status(time.monotonic())['supporting'])
        self.assertEqual(self.runtime.log.count('OFF'), 1)
        with self.assertRaises(AdapterError):
            core.submit(command(), Future())

    def test_cancel_waits_for_confirmed_worker_stop(self):
        core = self.ready(MemoryRuntime(duration=10.))
        future = Future()
        core.submit(command(), future)
        core.tick(time.monotonic())
        time.sleep(.01)
        core.cancel(future)
        core.tick(time.monotonic())
        self.assertEqual(future.result()[1], 'CANCELLED')
        self.assertEqual(core.state, 'STOPPED')
        self.assertFalse(self.backend.thread.is_alive())
        self.assertTrue(self.backend.shutdown_confirmed)

    def test_uncalibrated_face_up_shadow_and_dryrun_are_rejected_before_job(self):
        core = self.ready()
        for changes in ({'primitive_id': 'orient_face_up_and_support'},
                        {'policy_id': 'leap_faceup_v1', 'policy_action_values': [0.]*16},
                        {'dry_run': True}):
            with self.assertRaises(AdapterError):
                core.submit(command(**changes), Future())
            self.assertIsNone(core.job)
        self.assertNotIn('ON', self.runtime.log)

    def test_fault_after_completed_action_revokes_support_without_new_motion(self):
        core = self.ready()
        future = Future()
        core.submit(command(), future)
        self.until(future.done)
        self.runtime.fail.set()
        self.until(lambda: core.state == 'FAULT')
        self.assertFalse(core.status(time.monotonic())['supporting'])
        self.assertTrue(self.backend.shutdown_confirmed)

    def test_stale_cached_snapshot_is_not_retimestamped(self):
        core = self.ready()
        first = core.sample.acquired_at
        self.runtime.pause.set()
        time.sleep(.17)
        core.tick(time.monotonic())
        self.assertEqual(core.state, 'FAULT')
        self.assertIsNone(core.sample)
        self.assertLess(first, time.monotonic()-.15)

    def test_stop_without_confirmation_is_not_cancelled_success(self):
        core = self.ready(MemoryRuntime(duration=10., confirm_stop=False))
        # This test intentionally leaves an unconfirmed outcome for review.
        self._cleanups.pop()
        future = Future()
        core.submit(command(), future)
        core.tick(time.monotonic())
        core.cancel(future)
        core.tick(time.monotonic())
        self.assertEqual(core.state, 'FAULT')
        self.assertNotEqual(future.result()[1], 'CANCELLED')
        self.assertIn('stop unconfirmed', core.error)

    def test_joint_pose_with_torque_off_is_not_claimed_as_support(self):
        core = self.ready()
        self.assertFalse(self.backend.supporting(core.sample))

    def test_duplicate_physical_request_is_not_executed_twice(self):
        core = self.ready()
        future = Future()
        core.submit(command(), future)
        self.until(future.done)
        with self.assertRaisesRegex(AdapterError, 'duplicate or older'):
            core.submit(command(), Future())
        self.assertEqual(self.runtime.log.count('horizontal'), 1)
        self.assertIsNone(core.job)


if __name__ == '__main__':
    unittest.main()
