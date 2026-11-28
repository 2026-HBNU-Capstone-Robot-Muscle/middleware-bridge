"""Bounded READ wait visibility; never replace telemetry with fresh timestamps."""
from contextlib import contextmanager
from threading import RLock
import time


MAXIMUM_COMMUNICATION_WAIT_S = 10.2  # Original200ms plus the separate10s pause.


class CommunicationRecovery:
    def __init__(self):
        self.lock = RLock()
        self.pending_since = None
        self.read_since = None
        self.error = ''

    def reading(self, began):
        with self.lock:
            self.read_since = began

    def read_finished(self):
        with self.lock:
            self.read_since = None

    def missing(self, began):
        with self.lock:
            if self.pending_since is None:
                self.pending_since = began

    def validated(self):
        with self.lock:
            self.pending_since = None

    def failed(self, error):
        with self.lock:
            self.error = str(error)

    def finish(self):
        with self.lock:
            self.pending_since = self.read_since = None

    def status(self, now):
        with self.lock:
            pending, reading = self.pending_since, self.read_since
            return dict(active=pending is not None,
                started_at=pending,
                deadline=None if pending is None else pending+MAXIMUM_COMMUNICATION_WAIT_S,
                read_in_progress=reading is not None,
                read_started_at=reading,
                read_deadline=None if reading is None else reading+.2,
                error=self.error)


@contextmanager
def recovery_sampling(controller, tracker, validated):
    """The one serial owner installs/restores the source sampler under its lock."""
    import calibrated_two_full_health_20261028 as calibrated
    import leap_measured_grip_hold_20261117 as pose
    original = calibrated.sample
    if original is not controller.FAST_SAMPLE:
        raise RuntimeError('Unexpected recorded sampler override; no motion.')
    original_resume = getattr(controller, 'resume_health', None)

    def resume(*args, **kwargs):
        # A complete-but-late read may have no failed packet. Explicitly mark
        # its bounded pause without replacing any telemetry timestamp.
        tracker.missing(time.monotonic())
        return original_resume(*args, **kwargs)

    def sample(bus, command, report, phase, **kwargs):
        try:
            result = controller.sample(bus, command, report, phase, **kwargs)
            validated(bus, result[0])
            tracker.validated()
            return result
        except pose.OperatorStop:
            raise
        except BaseException as exc:
            tracker.failed(exc)
            raise

    calibrated.sample = sample
    if original_resume is not None:
        controller.resume_health = resume
    try:
        yield
    finally:
        calibrated.sample = original
        if original_resume is not None:
            controller.resume_health = original_resume
