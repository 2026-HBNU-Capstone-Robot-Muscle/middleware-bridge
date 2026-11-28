"""Bound child action acceptance, completion and cancellation without hardware I/O."""

from dataclasses import dataclass
import math
from threading import RLock
import time


@dataclass(frozen=True)
class ActionOutcome:
    """Only a successful terminal child result permits the next step."""

    result: object = None
    error_code: str = ''
    message: str = ''
    uncertain: bool = False


def positive_seconds(value, label):
    """Reject invalid watchdog settings before accepting any action."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be a positive finite number.')
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'{label} must be a positive finite number.')
    return float(value)


async def call_action(node, client, request, *, cancelled, timeout_s,
                      cancel_timeout_s, callback_group, label,
                      now=time.monotonic, future_factory=None):
    """Wait for a terminal result, including late acceptance and lost replies.

    On an uncertain outcome the caller must latch an execution fault. Cancelling
    a transport future is never treated as proof that a hand stopped moving.
    """
    timeout_s = positive_seconds(timeout_s, 'timeout_s')
    cancel_timeout_s = positive_seconds(cancel_timeout_s, 'cancel_timeout_s')
    if cancelled():
        return ActionOutcome(error_code='CANCELLED', message='Cancelled before dispatch.')
    if future_factory is None:
        from rclpy.clock import Clock, ClockType
        from rclpy.task import Future
        future_factory = Future
        timer_clock = Clock(clock_type=ClockType.STEADY_TIME)
    else:
        timer_clock = None
    finished = future_factory()
    lock = RLock()
    started = now()
    state = {'child': None, 'cancel_sent': False, 'cancel_at': None}

    def finish(outcome):
        if not finished.done():
            finished.set_result(outcome)

    def cancel_child():
        child = state['child']
        if child is not None and not state['cancel_sent']:
            state['cancel_sent'] = True
            try:
                child.cancel_goal_async()
            except Exception:
                # Only a terminal result can confirm the stop. Keep waiting
                # within the cancellation budget, then report uncertainty.
                pass

    def watch():
        with lock:
            if finished.done():
                return
            at = now()
            if cancelled():
                if state['cancel_at'] is None:
                    state['cancel_at'] = at
                cancel_child()
                if at - state['cancel_at'] >= cancel_timeout_s:
                    finish(ActionOutcome(
                        error_code=f'{label}_CANCEL_UNCONFIRMED',
                        message='Child cancellation was not confirmed by a terminal result.',
                        uncertain=True))
                    return
            if at - started >= timeout_s:
                cancel_child()
                finish(ActionOutcome(
                    error_code=f'{label}_TIMEOUT',
                    message='Timed out waiting for child acceptance or completion.',
                    uncertain=True))

    def on_result(future):
        with lock:
            watch()
            if finished.done():
                return
            try:
                wrapped = future.result()
                result = wrapped.result
                # action_msgs/GoalStatus: SUCCEEDED=4, CANCELED=5, ABORTED=6.
                if wrapped.status == 5:
                    finish(ActionOutcome(result, 'CANCELLED', 'Child cancellation confirmed.'))
                elif wrapped.status == 4 and result.success:
                    finish(ActionOutcome(result))
                elif wrapped.status in (4, 6):
                    finish(ActionOutcome(
                        result, result.error_code or f'{label}_FAILED',
                        result.error_message or 'Child primitive failed.'))
                else:
                    cancel_child()
                    finish(ActionOutcome(
                        error_code=f'{label}_INVALID_RESULT',
                        message='Child returned a nonterminal/invalid result status.',
                        uncertain=True))
            except Exception as exc:
                cancel_child()
                finish(ActionOutcome(
                    error_code=f'{label}_TRANSPORT_ERROR', message=str(exc), uncertain=True))

    def on_accepted(future):
        with lock:
            try:
                child = future.result()
                if not child.accepted:
                    finish(ActionOutcome(
                        error_code=f'{label}_REJECTED', message='Child goal was rejected.'))
                    return
                state['child'] = child
                if finished.done():
                    # A timed-out request can still be accepted afterwards.
                    cancel_child()
                    return
                child.get_result_async().add_done_callback(on_result)
                watch()
            except Exception as exc:
                cancel_child()
                finish(ActionOutcome(
                    error_code=f'{label}_TRANSPORT_ERROR', message=str(exc), uncertain=True))

    timer = node.create_timer(
        0.05, watch, callback_group=callback_group, clock=timer_clock)
    try:
        try:
            client.send_goal_async(request).add_done_callback(on_accepted)
        except Exception as exc:
            finish(ActionOutcome(
                error_code=f'{label}_TRANSPORT_ERROR', message=str(exc), uncertain=True))
        watch()
        return await finished
    finally:
        with lock:
            if not finished.done():
                finished.cancel()
                cancel_child()
        timer.cancel()
        node.destroy_timer(timer)
