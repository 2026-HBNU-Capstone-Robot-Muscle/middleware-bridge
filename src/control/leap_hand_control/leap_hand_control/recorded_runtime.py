"""Run the unchanged source controller in one worker and one torque session."""
from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Empty
import time

import numpy as np

from leap_hand_control.hardware_adapter import HandSample, TICK_RAD
from leap_hand_control.recorded_assets import RecordedAssets


def motor_sample(state, acquired_at):
    from sequence_flip_checked import signed_current
    current = signed_current(state['current'])
    integers = lambda values: tuple(int(v) for v in values)
    return HandSample(acquired_at, integers(state['position']), integers(state['goal']),
                      tuple(float(v) for v in current), tuple(float(v)/10 for v in state['voltage']),
                      integers(state['temperature']), integers(state['torque']), integers(state['error']))


class CommandSequence:
    """Append exact source trajectories only after a checked G boundary.

    The original run_pose loop owns configuration, guards, every write and
    cleanup. Its rows are a mutable list; extending it does not restart the loop.
    """

    def __init__(self, assets, pose, plan, first, requests, report, completed):
        self.assets, self.pose, self.plan = assets, pose, plan
        self.first, self.requests = first, requests
        self.report, self.completed = report, completed
        self.reference = plan.TwoAxisCycle()
        self.bus = None
        self.rows_list, self.labels, self.legs = [], [], []
        self.active = None
        self.active_leg = 'entry'
        self.confirmed = 0
        self.previous_state = None

    def current_bounds(self):
        return (self.reference.horizontal_bounds() if self.active_leg == 'horizontal'
                else self.plan.ORIGINAL_BOUNDS())

    def runtime_limits(self):
        from contextlib import contextmanager
        @contextmanager
        def scoped():
            if self.pose.bounds is not self.plan.ORIGINAL_BOUNDS:
                raise RuntimeError('Unexpected recorded bounds override.')
            old = self.pose.bounds
            self.pose.bounds = self.current_bounds
            try:
                yield
            finally:
                self.pose.bounds = old
        return scoped()

    def _append(self, job):
        token, payload = job[:2]
        history = self.report.setdefault('requested_commands', [])
        if not any(row['token'] == token for row in history):
            history.append(dict(token=token, **(job[2] if len(job) > 2 else {})))
        kinds = (payload,) if isinstance(payload, str) else tuple(payload)
        kinds = kinds or ('grip',)
        for leg, kind in enumerate(kinds):
            if leg:
                # At least three fresh guarded G samples between route legs.
                self.rows_list.extend(self.assets.grip.copy() for _ in range(4))
                self.labels.extend([f'ros_{token}_join_G_{leg}']*4)
                self.legs.extend(['entry']*4)
            goals = self.assets.goals[kind]
            prefix = f'ros_{token}_' if len(kinds) == 1 else f'ros_{token}_leg_{leg}_'
            self.rows_list.extend(q.copy() for q in goals)
            self.labels.extend(prefix+str(p) for p in self.assets.phases[kind])
            self.legs.extend([kind]*len(goals))
            self.rows_list.append(self.assets.grip.copy())
            self.labels.append(prefix+'final_G_check')
            self.legs.append('entry')
        self.active = job
        self.confirmed, self.previous_state = 0, None
        self.report['planned_goals'] = len(self.rows_list)
        self.report['holding'] = False

    def rows(self, current):
        self.active_leg = 'entry'
        # Reuse the source entry and its checked original joint bounds.
        from build_vertical_direct_grip_20261118 import grip_entry
        intro, labels = grip_entry(current, self.assets.grip)
        self.reference.check_rows(current, intro, self.plan.ORIGINAL_BOUNDS)
        self.rows_list = [q.copy() for q in intro]+[self.assets.grip.copy() for _ in range(40)]
        self.labels = ['ros_entry_'+p for p in labels]+['ros_entry_settle_G']*40
        self.legs = ['entry']*len(self.rows_list)
        self._append(self.first)
        return self.rows_list

    def metadata(self):
        return dict(workflow='middleware_recorded_G_command_G',
                    source_candidate_sha256=self.assets.manifest['candidate_sha256'],
                    automatic_stage_transitions_enabled=True, phase_gate_indices={},
                    intermediate_OFF_included=False, period_seconds=.075,
                    maximum_step_ticks=2, current_cap_ma=450,
                    physical_cube_orientation_verified=False,
                    completion_basis='joint_path_and_three_checked_G_samples')

    def _confirm_previous_hold(self):
        if self.active is None or self.bus is None:
            return
        phase = f'ros_{self.active[0]}_G_hold'
        state = getattr(self.bus, 'last_reviewed_state', None)
        if self.report.get('phase') != phase or state is None or state is self.previous_state:
            return
        self.previous_state = state
        valid = (np.array_equal(state['goal'], self.assets.grip)
                 and np.all(state['torque'] == 1)
                 and np.max(abs(state['position']-self.assets.grip))*TICK_RAD <= .12)
        if not valid:
            self.confirmed = 0
            return
        self.confirmed += 1
        if self.confirmed == 3:
            self.completed(self.active[0])
            self.report.setdefault('completed_commands', []).append(dict(
                token=self.active[0], kind=self.active[1], checked_G_samples=3))
            self.active = None

    def phase(self, index, moving):
        if moving:
            self.active_leg = self.legs[index]
            return self.labels[index]
        self.active_leg = 'entry'
        self._confirm_previous_hold()
        if self.active is None:
            try:
                job = self.requests.get_nowait()
            except Empty:
                return 'ros_G_hold'
            self._append(job)
            # This iteration still samples G. New goals start on the next one.
            return 'ros_next_command_G_boundary'
        return f'ros_{self.active[0]}_G_hold'

    @staticmethod
    def period(index, moving):
        return .075

    @staticmethod
    def ready(index):
        return True

    @staticmethod
    def message(phase):
        return phase


class SourceRuntime:
    """Only run() accesses serial; construction/asset checks never open a device."""

    def __init__(self, source_root, *, expected_port='', results_dir=None):
        self.assets = RecordedAssets(source_root)
        self.expected_port = expected_port
        self.results_dir = Path(results_dir) if results_dir else None
        self.shutdown_confirmed = False
        self.all_torque_off_verified = False
        self.settings_restored = False

    def run(self, stop, requests, sample, completed, ready):
        pose, plan = self.assets.import_controller()
        from final_grip_single_instance_20261116 import SingleInstance
        report = dict(status='starting', holding=False, all_torque_off_verified=False,
                      settings_restored=False, source_commit=self.assets.summary()['source_commit'])
        bus, folder = None, None
        if self.results_dir is not None:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            folder = self.results_dir / ('recorded_motion_'+stamp)
            folder.mkdir(parents=True, exist_ok=False)

        def cancel():
            if stop.is_set():
                raise pose.OperatorStop()

        class ObservedBus(pose.PoseBus):
            def snapshot(self):
                began = time.monotonic()
                state = super().snapshot()
                sample(motor_sample(state, began))
                return state

        failure = None
        try:
            with SingleInstance(self.assets.root / '.final_grip_pose.lock'):
                bus = ObservedBus(report, cancel)
                if self.expected_port and report['port'].casefold() != self.expected_port.casefold():
                    raise RuntimeError('Detected source USB port differs from explicitly selected port; no writes.')
                pose.preflight(bus, report, self.assets.grip)  # Read only.
                ready(tuple(int(x) for x in self.assets.grip))
                while not stop.is_set():
                    try:
                        first = requests.get(timeout=.025)
                        break
                    except Empty:
                        bus.snapshot()
                else:
                    return
                cancel()
                initial, start, _ = pose.preflight(bus, report, self.assets.grip)
                sequence = CommandSequence(self.assets, pose, plan, first, requests, report, completed)
                sequence.bus = bus
                with sequence.runtime_limits():
                    pose.run_pose(bus, initial, start, sequence.rows(start), report, cancel,
                                  sequence=sequence, limit=float('inf'))
        except pose.OperatorStop:
            report['status'] = 'stopped_by_request'
        except BaseException as exc:
            failure = exc
            report.update(status='fault', error=str(exc))
        finally:
            if bus is not None:
                bus.close()
            self.shutdown_confirmed = (bus is None or not bus.controlled or bool(
                report['all_torque_off_verified'] and report['settings_restored']))
            self.all_torque_off_verified = bool(report['all_torque_off_verified'])
            self.settings_restored = bool(report['settings_restored'])
            report['serial_port_closed'] = True
            if folder is not None:
                (folder/'result.json').write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        if report.get('cleanup_error'):
            raise RuntimeError('STOP_UNCONFIRMED: '+report['cleanup_error']) from failure
        if bus is not None and bus.controlled and not (
                report['all_torque_off_verified'] and report['settings_restored']):
            raise RuntimeError('STOP_UNCONFIRMED: OFF/restoration not verified.') from failure
        if failure is not None:
            raise failure
