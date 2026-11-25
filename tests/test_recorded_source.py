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

    def test_changed_recovery_pin_is_rejected_before_controller_import(self):
        from leap_hand_control.recorded_assets import RECOVERY_SOURCE_HASHES
        first = next(iter(RECOVERY_SOURCE_HASHES))
        with patch.dict(RECOVERY_SOURCE_HASHES, {first:'0'*64}), \
                patch('leap_hand_control.recorded_assets.importlib.import_module') as loader:
            with self.assertRaisesRegex(ValueError, 'communication recovery source hash'):
                RecordedAssets(self.assets.root)
            loader.assert_not_called()

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

    def test_three_leg_face_route_preserves_all_source_rows_and_only_completes_at_end(self):
        from leap_hand_control.recorded_runtime import CommandSequence
        initial = self.make_state(1)
        initial['position'] = self.assets.grip.copy()
        initial['goal'] = self.assets.grip.copy()
        done, goals = [], []
        pose = self.pose
        class Bus(self.FakeBus):
            def write(bus, address, size, values):
                if address == 116:
                    self.assertFalse(done)
                    goals.append((bus.report.get('phase', ''), np.array(values).copy()))
                super().write(address, size, values)
        bus, clock = Bus(initial), self.Clock()
        kinds = ('horizontal', 'horizontal', 'vertical')
        sequence = CommandSequence(self.assets, pose, self.plan, (1, kinds), Queue(), bus.report, done.append)
        sequence.bus = bus
        def cancel():
            if done:
                raise pose.OperatorStop()
        with sequence.runtime_limits(), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(pose.OperatorStop):
                pose.run_pose(bus, initial, initial['goal'], sequence.rows(initial['goal']),
                    bus.report, cancel, sequence=sequence, limit=float('inf'),
                    now=clock.now, sleep=clock.sleep)
        for i, kind in enumerate(kinds):
            short = 'h' if kind == 'horizontal' else 'v'
            actual = np.array([q for phase, q in goals if phase.startswith(f'ros_1_leg_{i}_{short}_')])
            np.testing.assert_array_equal(actual, self.assets.goals[kind])
        self.assertEqual(done, [1])
        self.assertGreater(clock.t, 1200.)
        joins = [s for s in bus.report['samples'] if s['phase'].startswith('ros_1_join_G_')]
        self.assertEqual(len(joins), 8)
        self.assertTrue(all(s['goal'] == self.assets.grip.tolist() for s in joins))
        self.assertEqual(sum(a == 64 and not np.any(q) for a, q in bus.writes), 1)
        self.assertTrue(bus.report['all_torque_off_verified'])
        self.assertTrue(bus.report['settings_restored'])

    def test_intermediate_G_fault_blocks_the_next_route_leg(self):
        from leap_hand_control.recorded_runtime import CommandSequence
        initial = self.make_state(1)
        initial['position'] = self.assets.grip.copy()
        initial['goal'] = self.assets.grip.copy()
        goals, done = [], []
        class Bus(self.FakeBus):
            def snapshot(bus):
                state = super().snapshot()
                if bus.report.get('phase') == 'ros_1_join_G_1' and np.any(state['torque']):
                    state['current'][0] = 600
                return state
            def write(bus, address, size, values):
                if address == 116:
                    goals.append(bus.report.get('phase', ''))
                super().write(address, size, values)
        bus, clock = Bus(initial), self.Clock()
        sequence = CommandSequence(self.assets, self.pose, self.plan, (1, ('grip', 'vertical')),
                                   Queue(), bus.report, done.append)
        sequence.bus = bus
        with sequence.runtime_limits(), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'measured current'):
                self.pose.run_pose(bus, initial, initial['goal'], sequence.rows(initial['goal']),
                    bus.report, lambda: None, sequence=sequence, limit=float('inf'),
                    now=clock.now, sleep=clock.sleep)
        self.assertEqual(done, [])
        self.assertFalse(any(p.startswith('ros_1_leg_1_v_') for p in goals))
        self.assertTrue(bus.report['all_torque_off_verified'])

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
        # Requested face is already up: prepare G without rotation.
        pending.put((1, (), {'target_face': 'U', 'face_direction_order': 'URFDLB'}))
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
        import calibrated_two_full_health_20261028 as calibrated
        recovery = NS(PauseBus=Bus, FAST_SAMPLE=calibrated.sample, sample=calibrated.sample)
        with patch.object(runtime.assets, 'recovery_controller', return_value=recovery), \
                patch.object(self.pose, 'run_pose', loop), \
                patch('final_grip_single_instance_20261116.SingleInstance', return_value=contextlib.nullcontext()), \
                contextlib.redirect_stdout(io.StringIO()):
            runtime.run(stop, pending, samples.append, done, ready)
        self.assertEqual(completed, [1])
        self.assertTrue(runtime.shutdown_confirmed)
        self.assertTrue(made[0].closed)
        self.assertTrue(samples)
        self.assertEqual(made[0].report['requested_commands'][0]['target_face'], 'U')
        self.assertEqual(sum(a == 64 and np.all(v) for a, v in made[0].writes), 1)

    def test_source_runtime_port_mismatch_closes_without_any_write(self):
        from leap_hand_control.recorded_runtime import SourceRuntime
        Bus, made = self.runtime_bus_class()
        runtime = SourceRuntime(self.assets.root, expected_port='OTHER_PORT')
        import calibrated_two_full_health_20261028 as calibrated
        recovery = NS(PauseBus=Bus, FAST_SAMPLE=calibrated.sample, sample=calibrated.sample)
        with patch.object(runtime.assets, 'recovery_controller', return_value=recovery), \
                patch('final_grip_single_instance_20261116.SingleInstance', return_value=contextlib.nullcontext()):
            with self.assertRaisesRegex(RuntimeError, 'port differs'):
                runtime.run(Event(), Queue(), lambda _: None, lambda _: None, lambda _: None)
        self.assertTrue(made[0].closed)
        self.assertEqual(made[0].writes, [])
        self.assertTrue(runtime.shutdown_confirmed)

    def test_all_recorded_commands_use_same_goal_recovery_without_replaying_rows(self):
        from leap_hand_control.recorded_runtime import SourceRuntime
        import time
        controller = self.assets.recovery_controller()
        initial = self.make_state(0)
        initial['position'] = self.assets.grip.copy()
        initial['goal'] = self.assets.grip.copy()
        runtime = SourceRuntime(self.assets.root, expected_port='VIRTUAL')
        native = controller.PauseBus
        made, goals, injected = [], [], set()
        fake = self.FakeBus

        class Bus(native):
            def __init__(bus, report, cancel):
                bus.__dict__.update(fake(initial).__dict__)
                bus.report, bus.cancel_callback = report, cancel
                bus.controlled = bus._motion_paused = bus._shutdown_started = False
                bus._using_unicast = bus.read_only = False
                bus.closed = False
                bus.packet = NS(ping=lambda port, motor:(1240, 0, 0))
                bus.port = object()
                report['port'] = 'VIRTUAL'
                made.append(bus)

            def read(bus, motor, address, size=1):
                return {10:0, 11:5, 20:0, 6:53, 8:3, 38:500}[address]

            def snapshot(bus):
                phase = bus.report.get('phase', '')
                key = next((key for prefix, key in (
                    ('ros_entry_', 'entry'), ('ros_1_G_hold', 'G_hold'),
                    ('ros_2_h_', 'horizontal'), ('ros_3_v_', 'vertical'),
                    ('ros_4_leg_1_v_', 'face_route')) if phase.startswith(prefix)), None)
                if ('accepted_start_goal' in bus.report and np.any(bus.state['torque'])
                        and key is not None and key not in injected):
                    injected.add(key)
                    runtime.communication.missing(time.monotonic())
                    raise controller.LinkReadFailure('Injected READ failure in '+key)
                return fake.snapshot(bus)

            def _motion_operation(bus):
                return fake.snapshot(bus), 0, 0, {}

            def write(bus, address, size, values):
                if bus._motion_paused:
                    raise AssertionError('Write occurred during READ-only recovery pause')
                if address == 116:
                    goals.append((bus.report.get('phase', ''), np.asarray(values).copy()))
                return fake.write(bus, address, size, values)

            def off(bus):
                return fake.off(bus)

            def close(bus):
                bus.closed = True

        pending, stop, done, samples = Queue(), Event(), [], []
        jobs = [(1, 'grip'), (2, 'horizontal'), (3, 'vertical'),
                (4, ('horizontal', 'vertical'), {'primitive_id':'orient_face_up_and_support'})]
        pending.put(jobs[0])

        def completed(token):
            done.append(token)
            if token < len(jobs):
                pending.put(jobs[token])
            else:
                stop.set()

        clock, original_loop = self.Clock(), self.pose.run_pose

        def loop(*args, **kwargs):
            return original_loop(*args, **kwargs, now=clock.now, sleep=clock.sleep)

        with patch.object(controller, 'PauseBus', Bus), \
                patch.object(self.pose, 'run_pose', loop), \
                patch('combined_quiet_reserve_20261029.quiet'), \
                patch('final_grip_single_instance_20261116.SingleInstance', return_value=contextlib.nullcontext()), \
                contextlib.redirect_stdout(io.StringIO()):
            runtime.run(stop, pending, samples.append, completed, lambda grip:None)
        self.assertEqual(done, [1, 2, 3, 4])
        self.assertEqual(injected, {'entry', 'G_hold', 'horizontal', 'vertical', 'face_route'})
        events = made[0].report['communication_pause_events']
        self.assertEqual(len(events), 5)
        self.assertTrue(all(e['status']=='resumed' and e['clean_reads']==2 for e in events))
        self.assertTrue(all(e['completed_goals_before']==e['completed_goals_after'] for e in events))
        for prefix, kind in (('ros_2_h_', 'horizontal'), ('ros_3_v_', 'vertical'),
                             ('ros_4_leg_0_h_', 'horizontal'), ('ros_4_leg_1_v_', 'vertical')):
            actual = np.array([q for phase, q in goals if phase.startswith(prefix)])
            np.testing.assert_array_equal(actual, self.assets.goals[kind])
        self.assertTrue(runtime.shutdown_confirmed)
        self.assertTrue(made[0].closed)
        self.assertEqual(sum(a==64 and np.all(v) for a, v in made[0].writes), 1)
        self.assertTrue(all(s.acquired_at <= time.monotonic() for s in samples))


if __name__ == '__main__':
    unittest.main()
