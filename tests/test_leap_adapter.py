"""State conversion, ownership, support lifetime and READ-only SDK tests."""

from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from threading import Thread
from types import SimpleNamespace as NS
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/control/leap_hand_control'))
from leap_hand_control.hardware_adapter import (
    AdapterError, HandAdapter, MockBackend, MOTOR_IDS, TICK_RAD, sim_positions)
from leap_hand_control.dynamixel_reader import DynamixelReader


def command(execution='execution', move=1, dry_run=True):
    return dict(scan_id='scan', execution_id=execution, move_index=move,
                target_face='R', dry_run=dry_run)


class AdapterTests(unittest.TestCase):
    def ready(self, backend=None):
        core = HandAdapter(backend or MockBackend())
        core.tick(0.)
        return core

    def test_mapping_is_current_and_does_not_wrap_or_clip(self):
        raw = [2048+i for i in range(16)]
        values = sim_positions(raw)
        self.assertEqual(MOTOR_IDS, (8, 6, 7, 5, 12, 10, 11, 9, 16, 14, 15, 13, 4, 3, 2, 1))
        for index, motor in enumerate(MOTOR_IDS):
            self.assertAlmostEqual(values[index], (motor-1)*TICK_RAD)
        raw[0] = -1
        self.assertAlmostEqual(sim_positions(raw)[15], -2049*TICK_RAD)

    def test_invalid_state_never_converts_to_valid_joints(self):
        for raw in ([2048]*15, [float('nan')]*16, [2048.5]*16):
            with self.assertRaises(ValueError):
                sim_positions(raw)

    def test_completion_latches_support_and_keeps_fresh_reads(self):
        core = self.ready()
        result = Future()
        core.submit(command(), result)
        core.tick(.075)
        self.assertFalse(result.done())
        core.tick(.301)
        self.assertTrue(result.result()[0])
        self.assertTrue(core.status(.301)['supporting'])
        core.tick(.376)
        self.assertEqual(core.sample.acquired_at, .376)
        self.assertTrue(core.status(.376)['supporting'])
        self.assertTrue(core.status(.376)['simulated'])

    def test_same_execution_can_rotate_again_without_clear(self):
        core = self.ready()
        one, two = Future(), Future()
        core.submit(command(), one); core.tick(.075); core.tick(.301)
        core.submit(command(move=2), two); core.tick(.376); core.tick(.602)
        self.assertTrue(two.result()[0])
        self.assertEqual(core.status(.602)['move_index'], 2)

    def test_other_execution_cannot_take_support(self):
        core = self.ready()
        core.submit(command(), Future()); core.tick(.075); core.tick(.301)
        with self.assertRaises(AdapterError) as caught:
            core.submit(command(execution='other'), Future())
        self.assertEqual(caught.exception.code, 'SUPPORT_OWNED')

    def test_concurrent_goal_cannot_replace_pending_motion(self):
        core = self.ready()
        core.submit(command(), Future())
        with self.assertRaises(AdapterError) as caught:
            core.submit(command(move=2), Future())
        self.assertEqual(caught.exception.code, 'HAND_BUSY')

    def test_cancel_does_not_report_success(self):
        core = self.ready(); result = Future()
        core.submit(command(), result); core.tick(.075)
        core.cancel(result); core.tick(.15)
        self.assertEqual(result.result()[1], 'CANCELLED')
        self.assertFalse(core.status(.15)['supporting'])

    def test_failed_read_during_hold_invalidates_support_and_stale_sample(self):
        backend = MockBackend(); core = self.ready(backend)
        core.submit(command(), Future()); core.tick(.075); core.tick(.301)
        def fail(_): raise RuntimeError('communication lost')
        backend.read = fail; core.tick(.376)
        self.assertEqual(core.state, 'FAULT')
        self.assertIsNone(core.sample)
        self.assertFalse(core.status(.376)['supporting'])
        with self.assertRaises(AdapterError): core.submit(command(), Future())

    def test_stale_snapshot_faults_instead_of_refreshing_its_timestamp(self):
        backend = MockBackend(); sample = backend.read(0.)
        backend.read = lambda now: sample
        core = self.ready(backend); core.tick(.2)
        self.assertEqual(core.state, 'FAULT')
        self.assertIsNone(core.sample)

    def test_motor_error_and_low_voltage_fault(self):
        for bad in (dict(errors=(1,)+(0,)*15), dict(voltage_v=(3.7,)*16)):
            backend = MockBackend(); sample = replace(backend.read(0.), **bad)
            backend.read = lambda now: sample
            core = self.ready(backend)
            self.assertEqual(core.state, 'FAULT')

    def test_mock_never_accepts_physical_goal(self):
        core = self.ready()
        with self.assertRaises(AdapterError): core.submit(command(dry_run=False), Future())

    def test_only_io_owner_may_touch_backend(self):
        core = self.ready(); errors = []
        def other():
            try: core.tick(.1)
            except RuntimeError as exc: errors.append(str(exc))
        thread = Thread(target=other); thread.start(); thread.join()
        self.assertEqual(len(errors), 1)

    def test_snapshot_age_alone_can_invalidate_support(self):
        core = self.ready()
        core.submit(command(), Future()); core.tick(.075); core.tick(.301)
        self.assertFalse(core.status(.6)['supporting'])


class ReaderTests(unittest.TestCase):
    def sdk(self, *, partial=False, comm=0):
        history = []
        port = NS(openPort=lambda: history.append('open') or True,
                  setBaudRate=lambda b: history.append(('baud', b)) or True,
                  closePort=lambda: history.append('close'))
        packet = NS(ping=lambda p, i: (1240, 0, 0))
        def get(motor, address, size):
            return {132:2048+motor, 116:2048+motor, 126:65535, 144:50,
                    146:20, 64:0, 70:0}[address]
        group = NS(addParam=lambda i: True, txRxPacket=lambda: comm,
                   isAvailable=lambda i, a, n: not (partial and i == 16), getData=get)
        sdk = NS(COMM_SUCCESS=0, PortHandler=lambda p: port,
                 PacketHandler=lambda p: packet, GroupSyncRead=lambda *a: group)
        return sdk, history

    def test_reader_uses_recorded_link_and_signed_current_with_no_write_api(self):
        sdk, history = self.sdk()
        reader = DynamixelReader('COM_TEST', sdk=sdk, now=lambda: 1.)
        reader.open(); sample = reader.read(1.).validate(); reader.close()
        self.assertEqual(sample.positions[0], 2049)
        self.assertEqual(sample.current_ma, (-1.,)*16)
        self.assertEqual(sample.voltage_v, (5.,)*16)
        self.assertEqual(history, ['open', ('baud', 1_000_000), 'close'])
        self.assertEqual(len(reader.inventory), 16)

    def test_partial_reply_discards_whole_snapshot(self):
        sdk, _ = self.sdk(partial=True)
        reader = DynamixelReader('COM_TEST', sdk=sdk, now=lambda: 1.); reader.open()
        with self.assertRaises(RuntimeError): reader.read(1.)
        reader.close()

    def test_communication_error_does_not_emit_state(self):
        sdk, _ = self.sdk(comm=-3002)
        reader = DynamixelReader('COM_TEST', sdk=sdk, now=lambda: 1.); reader.open()
        with self.assertRaises(RuntimeError): reader.read(1.)
        reader.close()

    def test_read_only_backend_rejects_motion_without_writes(self):
        sdk, history = self.sdk(); reader = DynamixelReader('COM_TEST', sdk=sdk, now=lambda: 0.)
        core = HandAdapter(reader); core.tick(0.)
        with self.assertRaises(AdapterError) as caught: core.submit(command(), Future())
        self.assertEqual(caught.exception.code, 'READ_ONLY')
        core.close()
        self.assertEqual(history[-1], 'close')


if __name__ == '__main__':
    unittest.main()
