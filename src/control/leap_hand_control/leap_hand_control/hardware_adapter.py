"""Single-owner LEAP backend contract, measured mapping and support lifecycle."""

from dataclasses import dataclass
import math
from threading import RLock, get_ident

import numpy as np

from leap_hand_control.joint_mapping import (
    JOINT_NAMES, MOTOR_IDS, TICK_RAD, sim_positions)


@dataclass(frozen=True)
class HandSample:
    """One complete acquisition, with source time retained on publication."""

    acquired_at: float
    positions: tuple
    goals: tuple
    current_ma: tuple
    voltage_v: tuple
    temperature_c: tuple
    torque: tuple
    errors: tuple

    def validate(self):
        if not math.isfinite(self.acquired_at):
            raise ValueError('Invalid acquisition timestamp.')
        for field in ('positions', 'goals', 'current_ma', 'voltage_v',
                      'temperature_c', 'torque', 'errors'):
            values = np.asarray(getattr(self, field), dtype=float)
            if values.shape != (16,) or not np.isfinite(values).all():
                raise ValueError(f'Incomplete/invalid16-motor snapshot: {field}')
        sim_positions(self.positions)
        sim_positions(self.goals)
        if any(self.errors) or any(v < 3.8 or v > 6.5 for v in self.voltage_v):
            raise ValueError('Motor error or voltage out of range.')
        if any(t > 45 for t in self.temperature_c):
            raise ValueError('Motor temperature out of range.')
        if any(abs(v) > 550 for v in self.current_ma):
            raise ValueError('Measured current exceeded the existing550mA trip level.')
        if any(v not in (0, 1) for v in self.torque):
            raise ValueError('Invalid torque telemetry.')
        return self


class AdapterError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class MockBackend:
    """No serial imports or motor writes; exercise the action/holding contract."""

    simulated = True
    motion_capable = True

    def __init__(self, duration_s=.225):
        self.duration_s = duration_s
        self.deadline = None

    def open(self):
        pass

    def read(self, now):
        return HandSample(now, (2048,)*16, (2048,)*16, (0.,)*16,
                          (5.,)*16, (20.,)*16, (0,)*16, (0,)*16)

    def begin(self, command, now):
        if not command['dry_run']:
            raise AdapterError('HARDWARE_DISABLED', 'Mock backend cannot execute physical requests.')
        self.deadline = now+self.duration_s

    def completed(self, now):
        return self.deadline is not None and now >= self.deadline

    def stop(self):
        self.deadline = None

    def close(self):
        self.stop()


class HandAdapter:
    """Only tick/close touch the backend; ROS callbacks only queue requests."""

    def __init__(self, backend, *, max_sample_age_s=.15, command_timeout_s=500.):
        self.backend = backend
        self.max_age = max_sample_age_s
        self.command_timeout = command_timeout_s
        self.lock = RLock()
        self.owner = None
        self.opened = False
        self.sample = None
        self.state = 'STARTING'
        self.identity = None
        self.job = None
        self.error = ''
        self.stop_requested = False
        self.communication_recovering = False

    def submit(self, command, future):
        """Queue one orientation operation; refuse overwriting a live support lease."""
        with self.lock:
            if self.state in ('STARTING', 'FAULT', 'CLOSED', 'STOPPED') or self.communication_recovering:
                raise AdapterError('HAND_NOT_READY', self.state)
            if self.job is not None:
                raise AdapterError('HAND_BUSY', 'A primitive is already active.')
            identity = (command['scan_id'], command['execution_id'])
            if self.identity is not None and self.identity[:2] != identity:
                raise AdapterError('SUPPORT_OWNED', 'Previous execution still owns support.')
            if not self.backend.motion_capable:
                raise AdapterError('READ_ONLY', 'State reader cannot execute motor commands.')
            if self.backend.simulated and not command['dry_run']:
                raise AdapterError('HARDWARE_DISABLED', 'Simulated backend only accepts dry-run.')
            validator = getattr(self.backend, 'validate_command', None)
            if validator is not None:
                validator(command)
            timeout = self.command_timeout
            if hasattr(self.backend, 'timeout_for_command'):
                timeout = self.backend.timeout_for_command(command)
            if not math.isfinite(timeout) or timeout <= 0:
                raise AdapterError('INVALID_TIMEOUT', 'Physical request timeout must be finite and positive.')
            self.job = dict(command=command.copy(), future=future,
                            started=None, cancel=False, timeout=timeout)

    def cancel(self, future):
        with self.lock:
            if self.job and self.job['future'] is future:
                self.job['cancel'] = True

    def request_clear(self):
        """Queue stop/clear; backend access stays on the I/O owner."""
        with self.lock:
            self.stop_requested = True

    def _owner(self):
        if self.owner is None:
            self.owner = get_ident()
        if self.owner != get_ident():
            raise RuntimeError('Only the I/O owner may access the motor backend.')

    def _finish(self, success, code='', message=''):
        job, self.job = self.job, None
        if job is not None and not job['future'].done():
            job['future'].set_result((success, code, message))

    def _communication_wait(self, now, stale):
        getter = getattr(self.backend, 'communication_status', None)
        status = getter(now) if getter is not None else {}
        pending = bool(status.get('active'))
        inflight = stale and bool(status.get('read_in_progress'))
        if not pending and not inflight:
            self.communication_recovering = False
            return False
        # A fresh heartbeat from the ROS timer cannot renew a worker's wait.
        # Only the source worker reports the original fixed READ deadlines.
        from leap_hand_control.recorded_recovery import MAXIMUM_COMMUNICATION_WAIT_S
        start = status.get('started_at' if pending else 'read_started_at')
        end = status.get('deadline' if pending else 'read_deadline')
        if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 < end-start <= MAXIMUM_COMMUNICATION_WAIT_S+1e-9
                or not start <= now < end):
            raise AdapterError('COMMUNICATION_RECOVERY_TIMEOUT', 'Bounded motor READ wait expired or invalid.')
        job = self.job
        if job is not None and job['started'] is not None and now-job['started'] > job['timeout']:
            raise AdapterError('HAND_TIMEOUT', 'Primitive exceeded its time budget during READ recovery.')
        self.communication_recovering = True
        self.sample = None  # Unknown support; never freshen cached telemetry.
        return True

    def tick(self, now):
        with self.lock:
            self._owner()
            if self.state == 'CLOSED':
                return
            if self.state == 'FAULT' and not self.stop_requested:
                return
            try:
                if not self.opened:
                    self.backend.open()
                    self.opened = True
                if getattr(self.backend, 'asynchronous', False):
                    now = self.backend.clock()
                if self.stop_requested:
                    self.backend.stop()
                    self.communication_recovering = False
                    self._finish(False, 'CANCELLED', 'Stop requested.')
                    self.identity = None
                    self.error = ''
                    self.state = 'IDLE'
                    self.stop_requested = False
                    if getattr(self.backend, 'stopped', False):
                        self.state, self.sample = 'STOPPED', None
                        return
                job = self.job
                if job is not None and job['cancel']:
                    self.backend.stop()
                    self.identity = None
                    self.state = 'IDLE'
                    self.communication_recovering = False
                    if getattr(self.backend, 'stopped', False):
                        self.state, self.sample = 'STOPPED', None
                    self._finish(False, 'CANCELLED', 'Backend stop confirmed.')
                    return
                sample = self.backend.read(now).validate()
                if getattr(self.backend, 'asynchronous', False):
                    now = self.backend.clock()
                age = now-sample.acquired_at
                if age < 0:
                    raise AdapterError('STALE_STATE', 'Motor snapshot is future-dated.')
                if self._communication_wait(now, age > self.max_age):
                    return
                if age > self.max_age:
                    raise AdapterError('STALE_STATE', 'Motor snapshot is stale or future-dated.')
                self.sample = sample
                if self.state == 'FAULT':
                    return  # No automatic restart after a driver fault.
                if self.state == 'STARTING':
                    self.state = 'IDLE'
                job = self.job
                if job is None:
                    return  # HOLDING keeps sampling; no automatic OPEN/OFF.
                if job['started'] is None:
                    self.backend.begin(job['command'], now)
                    job['started'] = now
                    self.state = 'MOVING'
                    self.identity = (job['command']['scan_id'], job['command']['execution_id'],
                                     job['command']['move_index'])
                if now-job['started'] > job['timeout']:
                    raise AdapterError('HAND_TIMEOUT', 'Primitive exceeded its time budget.')
                if self.backend.completed(now):
                    self.state = 'HOLDING'
                    self._finish(True, '', 'Orientation complete; support monitoring remains active.')
            except Exception as exc:
                self.error = str(exc)
                self.state = 'FAULT'
                self.communication_recovering = False
                # A failed read is not replaced by stale positions or fresh stamps.
                self.sample = None
                try:
                    self.backend.stop()
                except Exception as stop_error:
                    self.error += '; stop unconfirmed: '+str(stop_error)
                self._finish(False, getattr(exc, 'code', 'HAND_FAULT'), self.error)

    def status(self, now):
        with self.lock:
            sample = self.sample
            age = None if sample is None else now-sample.acquired_at
            healthy = (age is not None and 0 <= age <= self.max_age
                       and self.state != 'FAULT' and not self.communication_recovering)
            supported = healthy and self.state == 'HOLDING'
            if supported and hasattr(self.backend, 'supporting'):
                supported = self.backend.supporting(sample)
            status = dict(state=self.state, simulated=self.backend.simulated,
                        healthy=healthy, supporting=supported,
                        communication_recovering=self.communication_recovering,
                        support_basis=getattr(self.backend, 'support_basis', 'simulated'),
                        worker_shutdown_confirmed=getattr(self.backend, 'shutdown_confirmed', False),
                        all_torque_off_verified=getattr(self.backend, 'all_torque_off_verified', False),
                        settings_restored=getattr(self.backend, 'settings_restored', False),
                        scan_id=self.identity[0] if self.identity else '',
                        execution_id=self.identity[1] if self.identity else '',
                        move_index=self.identity[2] if self.identity else 0,
                        sample_age_s=age, error=self.error)
            if hasattr(self.backend, 'orientation_status'):
                status.update(self.backend.orientation_status())
            return status

    def close(self):
        with self.lock:
            self._owner()
            try:
                if self.opened:
                    self.backend.stop()
            finally:
                self.backend.close()
                self._finish(False, 'HAND_CLOSED', 'Adapter closed.')
                self.sample = None
                self.communication_recovering = False
                self.state = 'CLOSED'
