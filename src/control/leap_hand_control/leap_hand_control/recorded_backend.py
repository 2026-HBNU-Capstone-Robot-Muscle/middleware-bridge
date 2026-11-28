"""Opt-in recorded motor backend with one I/O worker and persistent G hold."""
from collections import deque
from queue import Queue
from threading import Event, RLock, Thread
import time

from leap_hand_control.hardware_adapter import AdapterError, TICK_RAD
from leap_hand_control.recorded_assets import PRIMITIVES
from leap_hand_control.recorded_orientation import (
    FACE_UP_PRIMITIVE, NOMINAL_SECONDS, apply, checked_order, route_to_up)


class RecordedMotionBackend:
    simulated = False
    motion_capable = True
    asynchronous = True
    recorded_mode = True
    support_basis = 'checked_joint_G_not_measured_cube_contact'

    def __init__(self, source_root='', *, armed=False, expected_port='', results_dir=None,
                 runtime_factory=None, clock=time.monotonic, startup_timeout=10., stop_timeout=3.):
        self.armed, self.clock = bool(armed), clock
        self.source_root, self.expected_port, self.results_dir = source_root, expected_port, results_dir
        self.factory = runtime_factory
        self.startup_timeout, self.stop_timeout = startup_timeout, stop_timeout
        self.lock = RLock()
        self.requests, self.samples = Queue(), deque(maxlen=8)
        self.stop_event, self.ready_event = Event(), Event()
        self.thread = None
        self.runtime = None
        self.error = None
        self.grip = None
        self.token = 0
        self.completed_token = 0
        self.stopped = False
        self.shutdown_confirmed = False
        self.last_request = None
        self.all_torque_off_verified = False
        self.settings_restored = False
        self.face_order = None
        self.pending_order = None
        self.pending_route = ()

    def _sample(self, value):
        with self.lock:
            self.samples.append(value)

    def _completed(self, token):
        with self.lock:
            if token != self.token:
                raise RuntimeError('Recorded completion token differs from the active request.')
            self.face_order = self.pending_order
            self.completed_token = token

    def _ready(self, grip):
        self.grip = grip
        self.ready_event.set()

    def _worker(self):
        runtime = None
        try:
            if self.factory is None:
                from leap_hand_control.recorded_runtime import SourceRuntime
                runtime = SourceRuntime(self.source_root, expected_port=self.expected_port,
                                        results_dir=self.results_dir)
            else:
                runtime = self.factory()
            with self.lock:
                self.runtime = runtime
            runtime.run(self.stop_event, self.requests, self._sample, self._completed, self._ready)
            if not self.stop_event.is_set():
                raise RuntimeError('Recorded controller exited unexpectedly.')
        except BaseException as exc:
            with self.lock:
                self.error = exc
        finally:
            self.shutdown_confirmed = runtime is None or bool(getattr(runtime, 'shutdown_confirmed', False))
            self.all_torque_off_verified = bool(getattr(runtime, 'all_torque_off_verified', False))
            self.settings_restored = bool(getattr(runtime, 'settings_restored', False))
            self.ready_event.set()

    def open(self):
        if not self.armed:
            raise AdapterError('HARDWARE_DISABLED', 'recorded_hardware_enabled must be explicitly true.')
        if self.stopped:
            raise AdapterError('HAND_RESTART_REQUIRED', 'Restart the node after a confirmed stop.')
        if self.thread is not None:
            return
        self.thread = Thread(target=self._worker, name='leap-recorded-io', daemon=True)
        self.thread.start()
        if not self.ready_event.wait(self.startup_timeout):
            self.stop_event.set()
            raise AdapterError('HAND_NOT_READY', 'Recorded startup did not complete in time.')
        if self.error is not None:
            raise AdapterError('HAND_NOT_READY', str(self.error))

    def validate_command(self, command):
        if command.get('primitive_id') not in (*PRIMITIVES, FACE_UP_PRIMITIVE):
            raise AdapterError('INVALID_PRIMITIVE', 'Unknown recorded primitive.')
        if command.get('dry_run', True):
            raise AdapterError('DRY_RUN_MISMATCH', 'Use mock mode for dry-run; recorded mode accepts explicit physical requests only.')
        if command.get('policy_id') or command.get('policy_action_values'):
            raise AdapterError('RECORDED_POLICY_MISMATCH', 'Recorded paths do not apply SAC/shadow policy outputs.')
        if (not str(command.get('scan_id', '')).strip()
                or not str(command.get('execution_id', '')).strip()
                or type(command.get('step_index')) is not int or command['step_index'] < 1):
            raise AdapterError('INVALID_PRIMITIVE', 'Recorded requests require scan/execution IDs and a positive step_index.')
        key = (command['scan_id'], command['execution_id'], command['step_index'])
        if self.last_request is not None and key[:2] == self.last_request[:2] and key[2] <= self.last_request[2]:
            raise AdapterError('REPLAYED_COMMAND', 'A duplicate or older physical request is not executed again.')
        self._plan(command)

    def _plan(self, command):
        if command['primitive_id'] == FACE_UP_PRIMITIVE:
            order = command.get('face_direction_order', '')
            if not order:
                raise AdapterError('ORIENTATION_STATE_REQUIRED', 'Supply current URFDLB slots in the fixed-G hand frame.')
            try:
                checked_order(order)
                target = command.get('target_face', '')
                index = command.get('target_face_direction_index')
                if type(index) is not int or not 0 <= index < 6 or order[index] != target:
                    raise ValueError('Target index does not match the current direction order.')
                if self.face_order is not None and self.face_order != order:
                    raise ValueError('Incoming direction order disagrees with the last completed recorded motion.')
                route, after = route_to_up(order, target)
                return route, after
            except ValueError as exc:
                raise AdapterError('INVALID_FACE_DIRECTION_STATE', str(exc)) from exc
        kind = PRIMITIVES[command['primitive_id']]
        # Legacy direct-action face fields remain metadata, never an implicit
        # initial orientation. Once seeded by a face-up request, track all moves.
        after = None if self.face_order is None else apply(self.face_order, kind)
        return (kind,), after

    def timeout_for_command(self, command):
        route, _ = self._plan(command)
        return max(900., sum(NOMINAL_SECONDS[k] for k in route)+300.+.3*len(route))

    def begin(self, command, now):
        self.validate_command(command)
        if self.thread is None or not self.thread.is_alive() or self.stopped or self.error:
            raise AdapterError('HAND_RESTART_REQUIRED', 'Recorded controller is not running.')
        self.token += 1
        self.last_request = (command['scan_id'], command['execution_id'], command['step_index'])
        route, self.pending_order = self._plan(command)
        self.pending_route = route
        self.face_order = None  # A partially completed rotation has unknown state.
        payload = route if command['primitive_id'] == FACE_UP_PRIMITIVE else route[0]
        context = {key: command.get(key) for key in (
            'scan_id', 'execution_id', 'step_index', 'move_index', 'primitive_id',
            'target_face', 'face_direction_order', 'target_face_direction_index')}
        context.update(predicted_face_direction_order=self.pending_order,
                       route=list(route), orientation_is_sensor_measured=False)
        self.requests.put((self.token, payload, context))

    def read(self, now):
        with self.lock:
            if self.error is not None:
                raise AdapterError('HAND_FAULT', str(self.error))
            values = [s for s in self.samples if s.acquired_at <= now]
            if not values:
                raise AdapterError('HAND_NOT_READY', 'No complete recorded motor snapshot yet.')
            return values[-1]

    def completed(self, now):
        with self.lock:
            if self.error is not None:
                raise AdapterError('HAND_FAULT', str(self.error))
            return self.token > 0 and self.completed_token == self.token

    def communication_status(self, now):
        with self.lock:
            if self.error is not None:
                raise AdapterError('HAND_FAULT', str(self.error))
            runtime = self.runtime
        getter = getattr(runtime, 'communication_status', None)
        status = getter(now) if getter is not None else dict(active=False, read_in_progress=False)
        if status.get('error'):
            raise AdapterError('HAND_FAULT', status['error'])
        return status

    def supporting(self, sample):
        return (self.grip is not None and all(sample.torque)
                and tuple(sample.goals) == self.grip
                and max(abs(a-b)*TICK_RAD for a, b in zip(sample.positions, self.grip)) <= .12)

    def orientation_status(self):
        with self.lock:
            known = self.face_order is not None and self.error is None and not self.stopped
            return dict(face_direction_order=self.face_order if known else '',
                        orientation_state_known=known,
                        orientation_basis='user_reported_quarter_turns_and_completed_joint_paths',
                        cube_orientation_sensor_verified=False,
                        planned_recorded_route=list(self.pending_route),
                        predicted_face_direction_order=self.pending_order or '')

    def stop(self):
        self.stop_event.set()
        self.stopped = True
        if self.thread is not None:
            self.thread.join(self.stop_timeout)
            if self.thread.is_alive():
                raise AdapterError('STOP_UNCONFIRMED', 'Recorded I/O worker has not confirmed shutdown; do not assume torque OFF.')
        if self.thread is not None and not self.shutdown_confirmed:
            raise AdapterError('STOP_UNCONFIRMED', str(self.error or 'OFF/restoration not confirmed.'))

    def close(self):
        self.stop()
