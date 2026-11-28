"""Exercise physical action gating and completion using production callbacks."""
import asyncio
from pathlib import Path
import sys
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/control/leap_hand_control'))
import test_leap_ros_wiring as wiring
from test_recorded_backend import MemoryRuntime
from leap_hand_control.hardware_adapter import HandAdapter
from leap_hand_control.recorded_backend import RecordedMotionBackend


class RecordedWiringTests(unittest.IsolatedAsyncioTestCase):
    def setup_node(self):
        node, goal, terminal = wiring.WiringTests().setup_node()
        runtime = MemoryRuntime()
        backend = RecordedMotionBackend(armed=True, runtime_factory=lambda: runtime)
        self.addCleanup(backend.close)
        node._adapter = HandAdapter(backend)
        node._adapter.tick(time.monotonic())
        node._policy_adapter = None  # Recorded requests do not depend on SAC weights/pose.
        node.get_clock = lambda: NS(now=lambda: NS(to_msg=lambda: NS(sec=0, nanosec=0)))
        goal.request.dry_run = False
        goal.request.primitive_id = 'rotate_horizontal_and_support'
        return node, goal, terminal, runtime

    async def drive(self, node, task):
        deadline = time.monotonic()+1.
        while not task.done() and time.monotonic() < deadline:
            node._io_tick()
            await asyncio.sleep(.003)
        self.assertTrue(task.done())
        return await task

    async def test_physical_action_returns_while_G_hold_and_worker_stay_alive(self):
        node, goal, terminal, runtime = self.setup_node()
        with patch.object(wiring.MODULE, 'Future', asyncio.get_running_loop().create_future):
            task = asyncio.create_task(node._execute(goal))
            result = await self.drive(node, task)
        self.assertTrue(result.success)
        self.assertEqual(terminal, ['success'])
        self.assertTrue(node._adapter.status(time.monotonic())['supporting'])
        self.assertNotIn('OFF', runtime.log)
        self.assertTrue(node._adapter.backend.thread.is_alive())

    async def test_face_up_without_direction_state_is_rejected_before_motion(self):
        node, goal, terminal, runtime = self.setup_node()
        goal.request.primitive_id = 'orient_face_up_and_support'
        goal.request.face_direction_order = ''
        result = await node._execute(goal)
        self.assertEqual(result.error_code, 'ORIENTATION_STATE_REQUIRED')
        self.assertEqual(runtime.log, ['open'])
        self.assertEqual(terminal, ['abort'])

    async def test_face_up_request_uses_observed_axis_mapping_and_reports_end_state(self):
        node, goal, terminal, runtime = self.setup_node()
        goal.request.primitive_id = 'orient_face_up_and_support'
        with patch.object(wiring.MODULE, 'Future', asyncio.get_running_loop().create_future):
            task = asyncio.create_task(node._execute(goal))
            result = await self.drive(node, task)
        self.assertTrue(result.success)
        self.assertEqual(terminal, ['success'])
        status = node._adapter.status(time.monotonic())
        self.assertEqual(status['face_direction_order'][0], 'R')
        self.assertEqual(status['planned_recorded_route'], ['horizontal', 'vertical'])
        self.assertNotIn('OFF', runtime.log)

    async def test_shadow_action_is_not_silently_treated_as_recorded_motion(self):
        node, goal, _, runtime = self.setup_node()
        goal.request.policy_id = 'leap_faceup_v1'
        goal.request.policy_action_values = [0.]*16
        result = await node._execute(goal)
        self.assertEqual(result.error_code, 'RECORDED_POLICY_MISMATCH')
        self.assertNotIn('ON', runtime.log)

    async def test_cancel_action_stops_worker_before_reporting_cancelled(self):
        node, goal, terminal, runtime = self.setup_node()
        runtime.duration = 10.
        with patch.object(wiring.MODULE, 'Future', asyncio.get_running_loop().create_future):
            task = asyncio.create_task(node._execute(goal))
            for _ in range(3):
                node._io_tick()
                await asyncio.sleep(.003)
            goal.is_cancel_requested = True
            result = await self.drive(node, task)
        self.assertFalse(result.success)
        self.assertEqual(terminal, ['cancel'])
        self.assertFalse(node._adapter.backend.thread.is_alive())

    async def test_stop_service_acknowledges_queue_then_IO_confirms_stop(self):
        node, goal, _, runtime = self.setup_node()
        with patch.object(wiring.MODULE, 'Future', asyncio.get_running_loop().create_future):
            task = asyncio.create_task(node._execute(goal))
            await self.drive(node, task)
        response = node._stop_recorded_motion(None, NS())
        self.assertTrue(response.success)
        self.assertNotIn('OFF', runtime.log)
        node._io_tick()
        self.assertEqual(node._adapter.state, 'STOPPED')
        self.assertIn('OFF', runtime.log)


if __name__ == '__main__':
    unittest.main()
