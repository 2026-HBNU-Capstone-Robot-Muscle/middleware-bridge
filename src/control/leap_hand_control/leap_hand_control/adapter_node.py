"""ROS state/primitive adapter; default mock, explicit hardware READ-only mode."""

import json
import time

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.task import Future
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from std_srvs.srv import Trigger

from leap_hand_control.dynamixel_reader import DynamixelReader
from leap_hand_control.hardware_adapter import (
    AdapterError, HandAdapter, JOINT_NAMES, MockBackend, sim_positions)
from leap_hand_control.primitive_server import LeapHandPrimitiveServer


class LeapHandAdapterNode(LeapHandPrimitiveServer):
    """The timer alone owns I/O; action completion does not terminate holding."""

    def __init__(self):
        super().__init__()
        self.declare_parameter('backend_mode', 'mock')
        self.declare_parameter('port', '')
        self.declare_parameter('recorded_source_root', '')
        self.declare_parameter('recorded_hardware_enabled', False)
        self.declare_parameter('recorded_results_dir', 'results/recorded_motion')
        mode = self.get_parameter('backend_mode').value
        if mode == 'mock':
            backend = MockBackend()
        elif mode == 'read_only':
            backend = DynamixelReader(self.get_parameter('port').value)
        elif mode == 'recorded':
            from leap_hand_control.recorded_backend import RecordedMotionBackend
            root = self.get_parameter('recorded_source_root').value.strip()
            armed = self.get_parameter('recorded_hardware_enabled').value
            if not root or not isinstance(armed, bool) or not armed:
                raise ValueError('recorded requires a source root and explicit recorded_hardware_enabled:=true.')
            backend = RecordedMotionBackend(root, armed=armed,
                expected_port=self.get_parameter('port').value,
                results_dir=self.get_parameter('recorded_results_dir').value)
        else:
            raise ValueError('backend_mode must be mock, read_only or recorded.')
        self._adapter = HandAdapter(backend, command_timeout_s=900. if mode == 'recorded' else 500.)
        self._waiting = None
        self._last_sample_time = None
        self._source_stamp = None
        self._state_pub = self.create_publisher(JointState, '/leap_hand/joint_states', 10)
        self._goal_pub = self.create_publisher(JointState, '/leap_hand/commanded_joint_states', 10)
        self._status_pub = self.create_publisher(String, '/leap_hand/support_status', 10)
        self._clear_service = self.create_service(
            Trigger, '/leap_hand/clear_mock_support', self._clear_mock_support)
        self._stop_service = self.create_service(
            Trigger, '/leap_hand/stop_recorded_motion', self._stop_recorded_motion)
        self._io_timer = self.create_timer(
            .075, self._io_tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.get_logger().info(
            f'LEAP adapter mode={mode}. mock means simulated states/support; '
            'read_only never writes; recorded requires an explicit physical action. '
            'Do not also run a robot CMD or another serial owner.')

    def _accepts_primitive(self, primitive_id):
        if getattr(self._adapter.backend, 'recorded_mode', False):
            from leap_hand_control.recorded_assets import PRIMITIVES
            return primitive_id in PRIMITIVES or super()._accepts_primitive(primitive_id)
        return super()._accepts_primitive(primitive_id)

    def _physical_request_error(self, goal):
        backend = self._adapter.backend
        if getattr(backend, 'recorded_mode', False) and backend.armed:
            try:
                backend.validate_command(dict(primitive_id=goal.primitive_id, dry_run=goal.dry_run,
                    policy_id=goal.policy_id, policy_action_values=list(goal.policy_action_values),
                    scan_id=goal.scan_id, execution_id=goal.execution_id, step_index=goal.step_index))
            except AdapterError as exc:
                return exc.code, str(exc)
            return None
        return super()._physical_request_error(goal)

    async def _execute_validated(self, goal_handle, result, feedback):
        goal = goal_handle.request
        future = Future()
        command = dict(scan_id=goal.scan_id, execution_id=goal.execution_id,
                       move_index=goal.move_index, target_face=goal.target_face,
                       dry_run=goal.dry_run, step_index=goal.step_index,
                       primitive_id=goal.primitive_id, cube_move=goal.cube_move,
                       face_direction_order=goal.face_direction_order,
                       target_face_direction_index=goal.target_face_direction_index,
                       policy_id=goal.policy_id, policy_action_values=list(goal.policy_action_values))
        try:
            self._adapter.submit(command, future)
        except AdapterError as exc:
            result.error_code, result.error_message = exc.code, str(exc)
            goal_handle.abort()
            return result
        self._waiting = (goal_handle, future)
        feedback.state = feedback.STATE_EXECUTING
        feedback.message = 'Adapter accepted; waiting for backend completion.'
        goal_handle.publish_feedback(feedback)
        try:
            success, code, message = await future
        finally:
            if self._waiting is not None and self._waiting[1] is future:
                self._waiting = None
        result.success, result.error_code, result.error_message = success, code, message
        if success:
            feedback.state = feedback.STATE_COMPLETED
            goal_handle.succeed()
        elif code == 'CANCELLED' and goal_handle.is_cancel_requested:
            feedback.state = feedback.STATE_CANCELLED
            goal_handle.canceled()
        else:
            feedback.state = feedback.STATE_FAILED
            goal_handle.abort()
        feedback.message = message
        goal_handle.publish_feedback(feedback)
        return result

    def _io_tick(self):
        before = time.monotonic()
        stamp = self.get_clock().now().to_msg()
        if self._waiting and self._waiting[0].is_cancel_requested:
            self._adapter.cancel(self._waiting[1])
        self._adapter.tick(before)
        status = self._adapter.status(time.monotonic())
        status['joint_names'] = list(JOINT_NAMES)
        status['motor_ids_in_sim_order'] = [8, 6, 7, 5, 12, 10, 11, 9, 16, 14, 15, 13, 4, 3, 2, 1]
        sample = self._adapter.sample
        if sample is not None and status['healthy']:
            if sample.acquired_at != self._last_sample_time:
                self._source_stamp = stamp
                self._last_sample_time = sample.acquired_at
            for values, publisher in ((sample.positions, self._state_pub), (sample.goals, self._goal_pub)):
                message = JointState()
                message.header.stamp = self._source_stamp
                message.header.frame_id = 'leap_hand_base'
                message.name = list(JOINT_NAMES)
                message.position = sim_positions(values)
                # Current is not torque; profile velocity is not measured speed.
                message.velocity, message.effort = [], []
                publisher.publish(message)
            status.update(current_ma=list(sample.current_ma), voltage_v=list(sample.voltage_v),
                          temperature_c=list(sample.temperature_c), torque=list(sample.torque))
        message = String()
        message.data = json.dumps(status, allow_nan=False)
        self._status_pub.publish(message)

    def _clear_mock_support(self, request, response):
        if not self._adapter.backend.simulated:
            response.success = False
            response.message = 'This service only clears simulated support; no motor stop is sent.'
        else:
            self._adapter.request_clear()
            response.success = True
            response.message = 'Mock support clear queued for the I/O timer.'
        return response

    def _stop_recorded_motion(self, request, response):
        if not getattr(self._adapter.backend, 'recorded_mode', False):
            response.success = False
            response.message = 'This service is for the explicit recorded backend only.'
        else:
            self._adapter.request_clear()
            response.success = True
            response.message = 'Stop queued; wait for status/recorded result to confirm OFF and restoration.'
        return response

    def destroy_node(self):
        if hasattr(self, '_io_timer'):
            self._io_timer.cancel()
            self._adapter.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = LeapHandAdapterNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
