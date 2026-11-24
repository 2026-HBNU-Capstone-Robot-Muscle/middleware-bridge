"""Replay both pinned real trajectories through the unchanged guarded loop."""
import contextlib
import io
import json
import os
from pathlib import Path
from queue import Queue
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/control/leap_hand_control'))
from leap_hand_control.recorded_assets import RecordedAssets, MANIFEST_PATH


class AssetRejectionTests(unittest.TestCase):
    def test_edited_manifest_rejected_before_external_code_import(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/MANIFEST_PATH
            target.parent.mkdir(parents=True)
            target.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'pinned'):
                RecordedAssets(folder)


class SourceReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ.get('RIGHT_HAND_SOURCE_ROOT',
            ROOT.parent/'right_rl_with_mujoco/hardware/right_hand'))
        if not root.is_dir():
            raise unittest.SkipTest('Set RIGHT_HAND_SOURCE_ROOT to the pinned right-hand package.')
        cls.assets = RecordedAssets(root)
        cls.pose, cls.plan = cls.assets.import_controller()
        from test_measured_grip_hold_20261117 import FakeBus, Clock, state
        cls.FakeBus, cls.Clock, cls.make_state = FakeBus, Clock, staticmethod(state)

    def test_actual_H_then_V_arrays_one_enable_no_OFF_at_completion(self):
        from leap_hand_control.recorded_runtime import CommandSequence
        initial = self.make_state(0)
        initial['position'] = self.assets.grip.copy()
        initial['goal'] = self.assets.grip.copy()
        pose, assets = self.pose, self.assets
        goals, phase_bounds, completion_samples = [], [], []

        class Bus(self.FakeBus):
            def write(bus, address, size, values):
                if address == 116:
                    goals.append((bus.report.get('phase', ''), np.asarray(values).copy()))
                    phase_bounds.append((bus.report.get('phase', ''), pose.bounds()[1].copy()))
                super().write(address, size, values)

        bus = Bus(initial)
        pending, done = Queue(), []
        clock = self.Clock()

        def completed(token):
            done.append(token)
            completion_samples.append(bus.report['samples'][-3:])
            # Completion is observed while the same controller still has torque.
            self.assertTrue(np.all(bus.state['torque']))
            self.assertFalse(bus.report.get('all_torque_off_verified', False))
            if token == 1:
                pending.put((2, 'vertical'))

        sequence = CommandSequence(assets, pose, self.plan, (1, 'horizontal'),
                                   pending, bus.report, completed)
        sequence.bus = bus

        def cancel():
            if done == [1, 2]:
                raise pose.OperatorStop()

        with sequence.runtime_limits(), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(pose.OperatorStop):
                pose.run_pose(bus, initial, initial['position'], sequence.rows(initial['position']),
                    bus.report, cancel, sequence=sequence, limit=float('inf'),
                    now=clock.now, sleep=clock.sleep)
        h = np.array([q for phase, q in goals if phase.startswith('ros_1_h_')])
        v = np.array([q for phase, q in goals if phase.startswith('ros_2_v_')])
        np.testing.assert_array_equal(h, assets.goals['horizontal'])
        np.testing.assert_array_equal(v, assets.goals['vertical'])
        self.assertEqual(done, [1, 2])
        self.assertEqual(bus.report['planned_goals'], len(sequence.rows_list))
        self.assertGreater(clock.t, 800.)
        self.assertEqual(sum(a == 64 and np.all(q) for a, q in bus.writes), 1)
        last_goal = max(i for i, (a, _) in enumerate(bus.writes) if a == 116)
        self.assertTrue(all(i > last_goal for i, (a, q) in enumerate(bus.writes)
                            if a == 64 and not np.any(q)))
        self.assertTrue(bus.report['all_torque_off_verified'])
        self.assertTrue(bus.report['settings_restored'])
        native = self.plan.ORIGINAL_BOUNDS()[1]
        self.assertTrue(all(np.array_equal(high, native) for phase, high in phase_bounds
                            if phase.startswith('ros_2_v_')))
        self.assertTrue(any(high[13] > native[13] for phase, high in phase_bounds
                            if phase.startswith('ros_1_h_')))
        self.assertIs(pose.bounds, self.plan.ORIGINAL_BOUNDS)
        self.assertLessEqual(np.max(abs(np.diff(np.array([q for _, q in goals]), axis=0))), 2)
        for token, samples in zip((1, 2), completion_samples):
            self.assertEqual(len(samples), 3)
            self.assertTrue(all(s['phase'] == f'ros_{token}_G_hold' for s in samples))

    def test_final_G_health_failure_does_not_complete_the_request(self):
        from leap_hand_control.recorded_runtime import CommandSequence
        initial = self.make_state(1)
        initial['position'] = self.assets.grip.copy()
        initial['goal'] = self.assets.grip.copy()

        class Bus(self.FakeBus):
            def snapshot(bus):
                result = super().snapshot()
                if bus.report.get('phase') == 'ros_1_G_hold' and np.any(result['torque']):
                    result['current'][0] = 600
                return result

        bus, done, clock = Bus(initial), [], self.Clock()
        sequence = CommandSequence(self.assets, self.pose, self.plan, (1, 'grip'),
                                   Queue(), bus.report, done.append)
        sequence.bus = bus
        with sequence.runtime_limits(), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'measured current'):
                self.pose.run_pose(bus, initial, initial['goal'], sequence.rows(initial['goal']),
                    bus.report, lambda: None, sequence=sequence, limit=float('inf'),
                    now=clock.now, sleep=clock.sleep)
        self.assertEqual(done, [])
        self.assertTrue(bus.report['all_torque_off_verified'])
        self.assertTrue(bus.report['settings_restored'])

    def test_motor_snapshot_preserves_source_current_units_and_json_types(self):
        from dataclasses import asdict
        from leap_hand_control.recorded_runtime import motor_sample
        from sequence_flip_checked import signed_current
        state = self.make_state(1)
        state['current'][0] = 65535
        result = motor_sample(state, 1.)
        self.assertEqual(result.current_ma[0], signed_current(state['current'])[0])
        json.dumps(asdict(result), allow_nan=False)

    def runtime_bus_class(self):
        initial = self.make_state(0)
        initial['position'] = self.assets.grip.copy()
        initial['goal'] = self.assets.grip.copy()
        made = []
        class Bus(self.FakeBus):
            def __init__(bus, report, cancel):
                super().__init__(initial)
                bus.report, bus.cancel_callback = report, cancel
                bus.controlled = False
                bus.closed = False
                bus.packet = NS(ping=lambda port, motor: (1240, 0, 0))
                bus.port = object()
                report['port'] = 'VIRTUAL'
                made.append(bus)
            def read(bus, motor, address, size=1):
                return {10: 0, 11: 5, 20: 0, 6: 53, 8: 3, 38: 500}[address]
            def close(bus):
                bus.closed = True
        return Bus, made

    def test_source_runtime_preflight_is_read_only_then_request_stops_cleanly(self):
        from leap_hand_control.recorded_runtime import SourceRuntime
        from final_grip_single_instance_20261116 import SingleInstance
        Bus, made = self.runtime_bus_class()
        pending, stop, samples, completed = Queue(), Event(), [], []
        pending.put((1, 'grip'))
        clock, original_loop = self.Clock(), self.pose.run_pose
        runtime = SourceRuntime(self.assets.root, expected_port='VIRTUAL')
        def ready(grip):
            self.assertEqual(made[0].writes, [])
            self.assertEqual(tuple(grip), tuple(self.assets.grip))
        def done(token):
            completed.append(token)
            self.assertTrue(np.all(made[0].state['torque']))
            stop.set()
        def loop(*args, **kwargs):
            return original_loop(*args, **kwargs, now=clock.now, sleep=clock.sleep)
        with patch.object(self.pose, 'PoseBus', Bus), patch.object(self.pose, 'run_pose', loop), \
                patch('final_grip_single_instance_20261116.SingleInstance', return_value=contextlib.nullcontext()), \
                contextlib.redirect_stdout(io.StringIO()):
            runtime.run(stop, pending, samples.append, done, ready)
        self.assertEqual(completed, [1])
        self.assertTrue(runtime.shutdown_confirmed)
        self.assertTrue(made[0].closed)
        self.assertTrue(samples)
        self.assertEqual(sum(a == 64 and np.all(v) for a, v in made[0].writes), 1)

    def test_source_runtime_port_mismatch_closes_without_any_write(self):
        from leap_hand_control.recorded_runtime import SourceRuntime
        Bus, made = self.runtime_bus_class()
        runtime = SourceRuntime(self.assets.root, expected_port='OTHER_PORT')
        with patch.object(self.pose, 'PoseBus', Bus), \
                patch('final_grip_single_instance_20261116.SingleInstance', return_value=contextlib.nullcontext()):
            with self.assertRaisesRegex(RuntimeError, 'port differs'):
                runtime.run(Event(), Queue(), lambda _: None, lambda _: None, lambda _: None)
        self.assertTrue(made[0].closed)
        self.assertEqual(made[0].writes, [])
        self.assertTrue(runtime.shutdown_confirmed)


if __name__ == '__main__':
    unittest.main()
