"""Deterministic action transport tests; no ROS or hardware installation needed."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/control/cube_execution'))
from cube_execution.action_call import call_action, positive_seconds


class Timer:
    def __init__(self, callback):
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class Node:
    def __init__(self):
        self.timers = []

    def create_timer(self, period, callback, **kwargs):
        timer = Timer(callback)
        self.timers.append(timer)
        return timer

    def destroy_timer(self, timer):
        self.timers.remove(timer)


class Child:
    accepted = True

    def __init__(self):
        self.future = asyncio.get_running_loop().create_future()
        self.cancel_count = 0

    def get_result_async(self):
        return self.future

    def cancel_goal_async(self):
        self.cancel_count += 1


class ActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.node = Node()
        self.clock = 0.0
        self.cancelled = False
        self.acceptance = asyncio.get_running_loop().create_future()
        self.calls = []
        self.client = SimpleNamespace(send_goal_async=self.send)

    def send(self, request):
        self.calls.append(request)
        return self.acceptance

    async def flush(self):
        for _ in range(4):
            await asyncio.sleep(0)

    async def start(self):
        task = asyncio.create_task(call_action(
            self.node, self.client, 'request', cancelled=lambda: self.cancelled,
            timeout_s=5, cancel_timeout_s=1, callback_group=None, label='HAND',
            now=lambda: self.clock, future_factory=asyncio.get_running_loop().create_future))
        await self.flush()
        return task

    def tick(self, at):
        self.clock = at
        for timer in list(self.node.timers):
            timer.callback()

    async def accept(self):
        child = Child()
        self.acceptance.set_result(child)
        await self.flush()
        return child

    async def test_success_requires_successful_terminal_status(self):
        task = await self.start()
        child = await self.accept()
        self.assertFalse(task.done())
        child.future.set_result(SimpleNamespace(
            status=4, result=SimpleNamespace(success=True)))
        outcome = await task
        self.assertTrue(outcome.result.success)
        self.assertFalse(outcome.error_code)
        self.assertFalse(self.node.timers)

    async def test_failed_child_and_aborted_success_flag_cannot_advance(self):
        task = await self.start()
        child = await self.accept()
        child.future.set_result(SimpleNamespace(status=6, result=SimpleNamespace(
            success=True, error_code='MOTOR_FAULT', error_message='stop')))
        outcome = await task
        self.assertEqual(outcome.error_code, 'MOTOR_FAULT')
        self.assertFalse(outcome.uncertain)

    async def test_lost_acceptance_times_out_and_late_acceptance_is_cancelled(self):
        task = await self.start()
        self.tick(5.1)
        outcome = await task
        self.assertEqual(outcome.error_code, 'HAND_TIMEOUT')
        self.assertTrue(outcome.uncertain)
        child = await self.accept()
        self.assertEqual(child.cancel_count, 1)
        self.assertFalse(self.node.timers)

    async def test_lost_result_times_out_without_new_goal(self):
        task = await self.start()
        child = await self.accept()
        self.tick(5.1)
        outcome = await task
        self.assertEqual(outcome.error_code, 'HAND_TIMEOUT')
        self.assertEqual(child.cancel_count, 1)
        self.assertEqual(self.calls, ['request'])

    async def test_cancel_waits_for_terminal_confirmation(self):
        task = await self.start()
        child = await self.accept()
        self.cancelled = True
        self.tick(.5)
        self.assertFalse(task.done())
        child.future.set_result(SimpleNamespace(status=5, result=SimpleNamespace(success=False)))
        outcome = await task
        self.assertEqual(outcome.error_code, 'CANCELLED')
        self.assertFalse(outcome.uncertain)
        self.assertEqual(child.cancel_count, 1)

    async def test_cancel_without_confirmation_does_not_claim_cancelled(self):
        task = await self.start()
        child = await self.accept()
        self.cancelled = True
        self.tick(.5)
        self.tick(1.6)
        outcome = await task
        self.assertEqual(outcome.error_code, 'HAND_CANCEL_UNCONFIRMED')
        self.assertTrue(outcome.uncertain)
        self.assertEqual(child.cancel_count, 1)

    async def test_cancel_before_dispatch_sends_nothing(self):
        self.cancelled = True
        outcome = await (await self.start())
        self.assertEqual(outcome.error_code, 'CANCELLED')
        self.assertFalse(self.calls)

    async def test_rejected_goal_does_not_enter_execution(self):
        task = await self.start()
        self.acceptance.set_result(SimpleNamespace(accepted=False))
        outcome = await task
        self.assertEqual(outcome.error_code, 'HAND_REJECTED')
        self.assertFalse(outcome.uncertain)

    async def test_result_after_deadline_is_rejected_even_before_timer_fires(self):
        task = await self.start()
        child = await self.accept()
        self.clock = 5.1
        child.future.set_result(SimpleNamespace(status=4, result=SimpleNamespace(success=True)))
        outcome = await task
        self.assertEqual(outcome.error_code, 'HAND_TIMEOUT')

    async def test_result_transport_error_latches_uncertainty(self):
        task = await self.start()
        child = await self.accept()
        child.future.set_exception(RuntimeError('connection lost'))
        outcome = await task
        self.assertEqual(outcome.error_code, 'HAND_TRANSPORT_ERROR')
        self.assertTrue(outcome.uncertain)

    def test_invalid_timeouts_rejected(self):
        for value in (0, -1, float('nan'), float('inf'), True, '5'):
            with self.assertRaises(ValueError):
                positive_seconds(value, 'test')


if __name__ == '__main__':
    unittest.main()
