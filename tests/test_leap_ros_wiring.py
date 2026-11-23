"""Exercise production ROS callbacks with message/clock stand-ins, no ROS I/O."""

import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/control/leap_hand_control'))
from leap_hand_control.hardware_adapter import HandAdapter, MockBackend


class Result:
    success = False
    error_code = ''
    error_message = ''


class Feedback:
    STATE_ACCEPTED, STATE_EXECUTING, STATE_COMPLETED, STATE_FAILED, STATE_CANCELLED = range(5)


class JointState:
    def __init__(self):
        self.header = NS(stamp=None, frame_id='')


def load_node():
    names = ('rclpy', 'rclpy.action', 'rclpy.callback_groups', 'rclpy.node',
             'rclpy.clock', 'rclpy.task', 'sensor_msgs', 'sensor_msgs.msg',
             'std_msgs', 'std_msgs.msg', 'std_srvs', 'std_srvs.srv',
             'ament_index_python', 'ament_index_python.packages',
             'system_interfaces', 'system_interfaces.action')
    modules = {name:ModuleType(name) for name in names}
    modules['rclpy.action'].ActionServer = object
    modules['rclpy.action'].CancelResponse = NS(ACCEPT=1)
    modules['rclpy.action'].GoalResponse = NS(ACCEPT=1)
    modules['rclpy.callback_groups'].ReentrantCallbackGroup = object
    modules['rclpy.node'].Node = object
    modules['rclpy.clock'].Clock = object
    modules['rclpy.clock'].ClockType = NS(STEADY_TIME=1)
    modules['rclpy.task'].Future = object
    modules['sensor_msgs.msg'].JointState = JointState
    modules['std_msgs.msg'].String = NS
    modules['std_srvs.srv'].Trigger = object
    modules['ament_index_python.packages'].get_package_share_directory = lambda _: ''
    modules['system_interfaces.action'].ExecuteHandPrimitive = NS(Result=Result, Feedback=Feedback)
    with patch.dict(sys.modules, modules):
        return importlib.import_module('leap_hand_control.adapter_node')


MODULE = load_node()


class WiringTests(unittest.IsolatedAsyncioTestCase):
    def setup_node(self):
        node = object.__new__(MODULE.LeapHandAdapterNode)
        node._adapter = HandAdapter(MockBackend())
        node._adapter.tick(0.)
        node._waiting = None
        node._last_sample_time = None
        node._source_stamp = None
        node._policy_adapter = object()
        node._policy_error = ''
        self.at = 0.
        self.measurements, self.commands, self.statuses = [], [], []
        node._state_pub = NS(publish=self.measurements.append)
        node._goal_pub = NS(publish=self.commands.append)
        node._status_pub = NS(publish=self.statuses.append)
        node.get_clock = lambda: NS(now=lambda: NS(to_msg=lambda: NS(sec=0, nanosec=int(self.at*1e9))))
        terminal = []
        goal = NS(scan_id='scan', execution_id='execution', move_index=1, step_index=1,
                  cube_move='R', target_face='R', face_direction_order='URFDLB',
                  target_face_direction_index=1, primitive_id='orient_face_up_and_support',
                  clockwise_quarter_turns=0, dry_run=True, policy_id='', policy_action_values=[])
        handle = NS(request=goal, is_cancel_requested=False, publish_feedback=lambda _:None,
                    succeed=lambda:terminal.append('success'), abort=lambda:terminal.append('abort'),
                    canceled=lambda:terminal.append('cancel'))
        return node, handle, terminal

    def tick(self, node, at):
        self.at = at
        with patch.object(MODULE.time, 'monotonic', return_value=at):
            node._io_tick()

    async def flush(self):
        for _ in range(3):await asyncio.sleep(0)

    async def test_real_validation_and_hook_wait_until_backend_completion(self):
        node, goal, terminal = self.setup_node()
        with patch.object(MODULE, 'Future', asyncio.get_running_loop().create_future):
            task = asyncio.create_task(node._execute(goal)); await self.flush()
            self.assertFalse(task.done())
            self.tick(node, .075); self.assertFalse(task.done())
            self.tick(node, .301); result = await task
        self.assertTrue(result.success)
        self.assertEqual(terminal, ['success'])
        self.tick(node, .376)
        self.assertTrue(node._adapter.status(.376)['supporting'])
        self.assertEqual(self.measurements[-1].effort, [])

    async def test_action_cancel_is_processed_by_io_owner(self):
        node, goal, terminal = self.setup_node()
        with patch.object(MODULE, 'Future', asyncio.get_running_loop().create_future):
            task = asyncio.create_task(node._execute(goal)); await self.flush()
            self.tick(node, .075); goal.is_cancel_requested = True
            self.tick(node, .15); result = await task
        self.assertFalse(result.success)
        self.assertEqual(terminal, ['cancel'])

    async def test_physical_request_is_still_blocked_before_backend(self):
        node, goal, terminal = self.setup_node(); goal.request.dry_run = False
        result = await node._execute(goal)
        self.assertFalse(result.success)
        self.assertIsNone(node._adapter.job)
        self.assertEqual(terminal, ['abort'])

    async def test_duplicate_timestamp_is_preserved_then_stale_data_stops_publication(self):
        node, _, _ = self.setup_node()
        self.tick(node, .1)
        first = self.measurements[-1].header.stamp
        sample = node._adapter.sample
        node._adapter.backend.read = lambda _: sample
        self.tick(node, .2)
        self.assertIs(self.measurements[-1].header.stamp, first)
        count = len(self.measurements)
        self.tick(node, .3)
        self.assertEqual(len(self.measurements), count)
        self.assertEqual(node._adapter.state, 'FAULT')


if __name__ == '__main__':
    unittest.main()
