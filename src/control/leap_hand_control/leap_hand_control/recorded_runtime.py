"""Run the unchanged source controller in one worker and one torque session."""
from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Empty
import time

import numpy as np

from leap_hand_control.hardware_adapter import HandSample, TICK_RAD
from leap_hand_control.recorded_assets import RecordedAssets
from leap_hand_control.recorded_recovery import CommunicationRecovery, recovery_sampling


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
        self.speed = assets.speed_controller()
        self.bus = None
        self.rows_list, self.labels, self.legs = [], [], []
        self.original_rows, self.indices, self.row_limits = [], [], []
        self.actual_rows = self.rows_list
        self.index, self.moving = 0, False
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
                with self.speed.VerticalSpeedTrial.runtime_scope(self):
                    yield
            finally:
                self.pose.bounds = old
        return scoped()

    def _constant(self, label):
        self.indices.append(len(self.original_rows))
        self.original_rows.append(self.assets.grip.copy())
        self.rows_list.append(self.assets.grip.copy())
        self.labels.append(label)
        self.legs.append('entry')
        self.row_limits.append(2)

    def _limit(self):
        return int(self.row_limits[self.index]) if self.moving else 2

    def validate_packet(self, value, previous, entry):
        # The same exact-next-packet and dense2tick proof used by the checked
        # standalone speed trials. Arbitrary6tick targets are not admitted.
        return self.speed.VerticalSpeedTrial.validate_packet(self, value, previous, entry)

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
                for _ in range(4):
                    self._constant(f'ros_{token}_join_G_{leg}')
            goals = self.assets.goals[kind]
            dense = self.assets.dense_goals[kind]
            bounds = self.reference.horizontal_bounds if kind=='horizontal' else self.plan.ORIGINAL_BOUNDS
            if len(dense):
                self.reference.check_rows(self.assets.grip,dense,bounds)
            offset = len(self.original_rows)
            self.original_rows.extend(q.copy() for q in dense)
            self.indices.extend(int(i)+offset for i in self.assets.source_indices[kind])
            self.row_limits.extend(int(i) for i in self.assets.step_limits[kind])
            prefix = f'ros_{token}_' if len(kinds) == 1 else f'ros_{token}_leg_{leg}_'
            self.rows_list.extend(q.copy() for q in goals)
            self.labels.extend(prefix+str(p) for p in self.assets.phases[kind])
            self.legs.extend([kind]*len(goals))
            self._constant(prefix+'final_G_check')
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
        self.actual_rows = self.rows_list
        self.original_rows = [q.copy() for q in self.rows_list]
        self.indices = list(range(len(self.rows_list)))
        self.row_limits = [2]*len(self.rows_list)
        self.entry = np.asarray(current).copy()
        self.index, self.moving = 0, False
        self.labels = ['ros_entry_'+p for p in labels]+['ros_entry_settle_G']*40
        self.legs = ['entry']*len(self.rows_list)
        self._append(self.first)
        return self.rows_list

    def metadata(self):
        return dict(workflow='middleware_recorded_G_command_G',
                    source_candidate_sha256=self.assets.manifest['candidate_sha256'],
                    automatic_stage_transitions_enabled=True, phase_gate_indices={},
                    intermediate_OFF_included=False, period_seconds=.075,
                    maximum_step_ticks=6, entry_maximum_step_ticks=2,
                    original_dense_source_maximum_step_ticks=2,
                    speed_scope='exact_next_selected_source_target_only', current_cap_ma=450,
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
        self.index, self.moving = index, moving
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
        self.communication = CommunicationRecovery()

    def communication_status(self, now):
        return self.communication.status(now)

    def run(self, stop, requests, sample, completed, ready):
        pose, plan = self.assets.import_controller()
        recovery = self.assets.recovery_controller()
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

        tracker = self.communication

        class ObservedBus(recovery.PauseBus):
            _last_full_read = None

            def _motion_operation(self):
                began = time.monotonic()
                admitted = ('accepted_start_goal' in report and not self._shutdown_started)
                if admitted:
                    tracker.reading(began)
                try:
                    result = super()._motion_operation()
                    state, comm, error, _ = result
                    if admitted and comm in (-3001, -3002) and not error:
                        tracker.missing(began)
                    if not comm and not error:
                        self._last_full_read = state, began
                    return result
                finally:
                    if admitted:
                        tracker.read_finished()

            def snapshot(self):
                began = time.monotonic()
                state = super().snapshot()
                latest = self._last_full_read
                acquired = latest[1] if latest is not None and latest[0] is state else began
                self._last_full_read = state, acquired
                sample(motor_sample(state, acquired))
                return state

        def validated(bus, state):
            latest = bus._last_full_read
            if latest is None or latest[0] is not state:
                raise RuntimeError('No acquisition timestamp for recovered full motor state.')
            # Pause probes bypass snapshot(); publish their newly measured
            # final state with the actual acquisition time, never "now".
            sample(motor_sample(state, latest[1]))

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
                with sequence.runtime_limits(), recovery_sampling(recovery, tracker, validated):
                    pose.run_pose(bus, initial, start, sequence.rows(start), report, cancel,
                                  sequence=sequence, limit=float('inf'))
        except pose.OperatorStop:
            report['status'] = 'stopped_by_request'
        except BaseException as exc:
            failure = exc
            report.update(status='fault', error=str(exc))
        finally:
            tracker.finish()
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
