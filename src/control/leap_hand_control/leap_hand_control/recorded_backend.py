"""Opt-in recorded motor backend with one I/O worker and persistent G hold."""
from collections import deque
from queue import Queue
from threading import Event, RLock, Thread
import time

from leap_hand_control.hardware_adapter import AdapterError, TICK_RAD
from leap_hand_control.recorded_assets import PRIMITIVES


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
        self.error = None
        self.grip = None
        self.token = 0
        self.completed_token = 0
        self.stopped = False
        self.shutdown_confirmed = False
        self.last_request = None
        self.all_torque_off_verified = False
        self.settings_restored = False

    def _sample(self, value):
        with self.lock:
            self.samples.append(value)

    def _completed(self, token):
        with self.lock:
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
        if command.get('primitive_id') not in PRIMITIVES:
            raise AdapterError('ORIENTATION_ROUTE_UNCONFIGURED',
                               'Use an explicit recorded grip/horizontal/vertical primitive; face-up routes are not calibrated.')
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

    def begin(self, command, now):
        self.validate_command(command)
        if self.thread is None or not self.thread.is_alive() or self.stopped or self.error:
            raise AdapterError('HAND_RESTART_REQUIRED', 'Recorded controller is not running.')
        self.token += 1
        self.last_request = (command['scan_id'], command['execution_id'], command['step_index'])
        self.requests.put((self.token, PRIMITIVES[command['primitive_id']]))

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

    def supporting(self, sample):
        return (self.grip is not None and all(sample.torque)
                and tuple(sample.goals) == self.grip
                and max(abs(a-b)*TICK_RAD for a, b in zip(sample.positions, self.grip)) <= .12)

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
