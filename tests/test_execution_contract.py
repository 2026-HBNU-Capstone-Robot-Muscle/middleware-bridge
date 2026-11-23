"""Run the real executor control flow with ROS transport/message stand-ins."""

import asyncio
import importlib.util
from pathlib import Path
import sys
from threading import Lock
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for relative in ('src/control/cube_execution', 'src/control/leap_hand_control'):
    sys.path.insert(0, str(ROOT / relative))


class Result:
    def __init__(self):
        self.success = False
        self.error_code = ''
        self.error_message = ''
        self.completed_steps = 0
        self.completed_moves = 0
        for name in ('policy_ids', 'policy_step_indices', 'policy_observation_sizes',
                     'policy_observations', 'policy_action_sizes', 'policy_action_values',
                     'face_direction_orders_before', 'face_direction_orders_after',
                     'target_face_direction_indices_before', 'target_face_direction_indices_after'):
            setattr(self, name, [])


def load_executor():
    """Only ROS bindings are substituted; the production executor is imported."""
    names = ('rclpy', 'rclpy.action', 'rclpy.callback_groups', 'rclpy.node',
             'rclpy.qos', 'system_interfaces', 'system_interfaces.action',
             'system_interfaces.msg')
    modules = {name: ModuleType(name) for name in names}
    for name in ('ActionClient', 'ActionServer'):
        setattr(modules['rclpy.action'], name, object)
    for name in ('GoalResponse', 'CancelResponse'):
        setattr(modules['rclpy.action'], name, NS(ACCEPT=1, REJECT=2))
    modules['rclpy.callback_groups'].ReentrantCallbackGroup = object
    modules['rclpy.node'].Node = object
    for name in ('DurabilityPolicy', 'QoSProfile', 'ReliabilityPolicy'):
        setattr(modules['rclpy.qos'], name, object)
    for name in ('ExecuteCubeSolution', 'ExecuteHandPrimitive', 'InferHandPolicy'):
        setattr(modules['system_interfaces.action'], name, NS(Result=Result, Goal=NS))
    status = type('Status', (), {})
    for value, name in enumerate(('RECEIVED', 'WAITING_FOR_EXECUTION', 'VALIDATING',
                                  'FAILED', 'CANCELLED', 'HANDOFF', 'EXECUTING', 'COMPLETED')):
        setattr(status, 'STATE_'+name, value)
    modules['system_interfaces.msg'].CubeExecutionStatus = status
    modules['system_interfaces.msg'].CubeSolution = NS
    modules['system_interfaces.msg'].OpenLoopPolicyState = NS
    path = ROOT / 'src/control/cube_execution/cube_execution/executor_node.py'
    spec = importlib.util.spec_from_file_location('executor_contract_under_test', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


MODULE = load_executor()


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setup_executor(self, *, fail_step=None, cancel_step=None, error_code='HAND_FAULT'):
        node = object.__new__(MODULE.CubeSequenceExecutor)
        node._solutions_lock = Lock()
        node._execution_busy_lock = Lock()
        node._execution_busy = False
        node._execution_faulted = False
        node._solutions = {'scan': NS(scan_id='scan', facelets=''.join(f*9 for f in 'URFDLB'), moves=['R'])}
        state = NS(order='URFDLB', cube_orientation=NS(w=1., x=0., y=0., z=0.))
        node._copy_solution = lambda value: value
        node._copy_open_loop_state = lambda value: value
        node._validate_open_loop_state = lambda _: None
        node._policy_client = NS(wait_for_server=lambda **kwargs: True)
        node._face_direction_order = lambda current, _: current.order
        node._build_open_loop_observation = lambda *args: (np.zeros(108), np.array([1., 0., 0., 0.]))
        changes = []

        def advance(current, builder, step, actions, quaternion):
            changes.append(step['primitive_id'])
            if step['hand_id'] == 'leap_hand':
                current.order = 'RUFBLD'  # A permutation with R now in the up slot.
        node._advance_open_loop_state = advance
        node._publish_status = lambda *args, **kwargs: NS()
        node._publish_feedback = lambda *args: None
        terminal = []
        goal = NS(scan_id='scan', workflow_id='', dry_run=True,
                  run_pretrained_policies=True, initial_open_loop_state=state)
        handle = NS(request=goal, is_cancel_requested=False,
                    abort=lambda: terminal.append('abort'),
                    canceled=lambda: terminal.append('cancel'),
                    succeed=lambda: terminal.append('success'))

        async def infer(*args):
            return NS(success=True, action_values=[0.]*16), ''
        node._infer_policy = infer
        dispatched = []

        async def dispatch(parent, parent_goal, result, index, step):
            # These assertions run inside the actual production workflow loop.
            self.assertEqual(len(changes), index-1)
            self.assertEqual(step['face_direction_order'], state.order)
            self.assertEqual(step['target_face_direction_index'], state.order.index('R'))
            dispatched.append(index)
            await asyncio.sleep(0)
            self.assertEqual(len(changes), index-1)
            if index == cancel_step:
                parent.is_cancel_requested = True
            if index == fail_step:
                return NS(success=False, error_code=error_code, error_message='test failure'), ''
            return NS(success=True), ''
        node._dispatch_step = dispatch
        return node, handle, state, changes, dispatched, terminal

    async def test_state_and_frame_advance_only_after_successful_child(self):
        node, goal, state, changes, dispatched, terminal = self.setup_executor()
        result = await node._execute_goal(goal)
        self.assertTrue(result.success)
        self.assertEqual(dispatched, [1, 2, 3, 4])
        self.assertEqual(len(changes), 4)
        self.assertEqual(result.face_direction_orders_before[0], 'URFDLB')
        self.assertEqual(result.face_direction_orders_after[0], 'RUFBLD')
        self.assertEqual(terminal, ['success'])

    async def test_failed_first_right_hand_does_not_rotate_logical_frame(self):
        node, goal, state, changes, dispatched, terminal = self.setup_executor(fail_step=1)
        result = await node._execute_goal(goal)
        self.assertFalse(result.success)
        self.assertEqual(state.order, 'URFDLB')
        self.assertEqual(changes, [])
        self.assertEqual(result.face_direction_orders_after, [])
        self.assertEqual(dispatched, [1])
        self.assertEqual(terminal, ['abort'])

    async def test_failed_left_rotation_does_not_advance_or_release(self):
        node, goal, state, changes, dispatched, terminal = self.setup_executor(fail_step=3)
        result = await node._execute_goal(goal)
        self.assertFalse(result.success)
        self.assertEqual(len(changes), 2)
        self.assertEqual(dispatched, [1, 2, 3])
        self.assertEqual(result.completed_moves, 0)

    async def test_unconfirmed_child_cancel_aborts_instead_of_claiming_cancelled(self):
        node, goal, state, changes, dispatched, terminal = self.setup_executor(
            fail_step=1, cancel_step=1, error_code='HAND_CANCEL_UNCONFIRMED')
        result = await node._execute_goal(goal)
        self.assertEqual(result.error_code, 'HAND_CANCEL_UNCONFIRMED')
        self.assertEqual(terminal, ['abort'])
        self.assertFalse(changes)

    async def test_confirmed_cancel_stops_workflow(self):
        node, goal, state, changes, dispatched, terminal = self.setup_executor(
            fail_step=1, cancel_step=1, error_code='CANCELLED')
        result = await node._execute_goal(goal)
        self.assertEqual(result.error_code, 'CANCELLED')
        self.assertEqual(terminal, ['cancel'])
        self.assertFalse(changes)

    async def test_cancel_on_last_child_is_not_reported_as_success(self):
        node, goal, state, changes, dispatched, terminal = self.setup_executor(cancel_step=4)
        result = await node._execute_goal(goal)
        self.assertFalse(result.success)
        self.assertEqual(result.completed_steps, 4)
        self.assertEqual(terminal, ['cancel'])

    async def test_uncertain_transport_fault_blocks_next_execution(self):
        from cube_execution.action_call import ActionOutcome
        node, goal, *_ = self.setup_executor()
        node._callback_group = None
        node._cancel_timeout_s = 2
        node.get_logger = lambda: NS(error=lambda _: None)

        async def failed_transport(*args, **kwargs):
            return ActionOutcome(error_code='HAND_TIMEOUT', uncertain=True)
        with patch.object(MODULE, 'call_action', failed_transport):
            result, _ = await node._call_child(None, None, goal, 'HAND', 5, Result)
        self.assertEqual(result.error_code, 'HAND_TIMEOUT')
        self.assertTrue(node._execution_faulted)
        self.assertEqual(node._goal_request(None), MODULE.GoalResponse.REJECT)


if __name__ == '__main__':
    unittest.main()
