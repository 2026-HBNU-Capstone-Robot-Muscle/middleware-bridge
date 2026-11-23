"""Infer LEAP policy outputs from timestamped ROS input without motor writes."""

from pathlib import Path
from copy import deepcopy

import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from rclpy.qos import QoSProfile
from system_interfaces.msg import HandPolicyAction, LeapPolicyInput

from leap_hand_control.observation_builder import (
    JOINT_NAMES,
    LeapObservationBuilder,
)
from leap_hand_control.policy_adapter import LeapPolicyAdapter
from leap_hand_control.joint_mapping import ordered_positions


def _stamp_ns(stamp):
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def _finite_vector(values, size, label):
    array = np.asarray(values, dtype=np.float64)
    if array.shape != (size,) or not np.all(np.isfinite(array)):
        raise ValueError(f'{label} must contain {size} finite values.')
    return array


def _unit_quaternion_xyzw(value, label):
    q = _finite_vector(
        [value.x, value.y, value.z, value.w], 4, label)
    norm = float(np.linalg.norm(q))
    if norm < 1e-9:
        raise ValueError(f'{label} quaternion has zero norm.')
    x, y, z, w = q / norm
    return np.array([w, x, y, z], dtype=np.float64)


class LeapPolicyShadowNode(Node):
    """Subscribe to the composite input contract and publish normalized actions."""

    def __init__(self):
        super().__init__('leap_policy_shadow_node')
        package_share = Path(get_package_share_directory('leap_hand_control'))
        self.declare_parameter(
            'policy_path', str(package_share / 'models' / 'policy_np.npz'))
        self.declare_parameter('world_frame', '')
        # Source deployment defaults to freezing policy commands past 150 ms.
        self.declare_parameter('max_input_age_ms', 150)
        policy_path = self.get_parameter('policy_path').value
        self._world_frame = self.get_parameter('world_frame').value.strip()
        self._max_age_ms = int(self.get_parameter('max_input_age_ms').value)
        if self._max_age_ms <= 0:
            raise ValueError('max_input_age_ms must be positive.')
        self._policy = LeapPolicyAdapter(policy_path)
        self._builder = LeapObservationBuilder()
        self._last_identity = None
        self._last_source_stamps = None
        self._last_goal = None
        self._last_accepted_at = None
        self._history_valid = False
        self._input_subscription = self.create_subscription(
            LeapPolicyInput, '/leap_hand/policy_input', self._on_input,
            QoSProfile(depth=1))
        self._action_publisher = self.create_publisher(
            HandPolicyAction, '/leap_hand/policy_action', QoSProfile(depth=1))
        self.get_logger().info(
            'Shadow inference ready: /leap_hand/policy_input → '
            '/leap_hand/policy_action; motor output is not connected. '
            'last_action stays zero: no applied-action acknowledgement is supplied.')

    def _validate_stamp(self, stamp, label, now_ns):
        value = _stamp_ns(stamp)
        if value <= 0:
            raise ValueError(f'{label} timestamp is missing.')
        age_ms = (now_ns - value) / 1_000_000.0
        if age_ms < 0 or age_ms > self._max_age_ms:
            raise ValueError(
                f'{label} timestamp is future-dated or stale ({age_ms:.1f} ms).')

    def _on_input(self, message):
        try:
            if not self._world_frame:
                raise ValueError('world_frame parameter must be set before inference.')
            if not message.scan_id or not message.execution_id:
                raise ValueError('scan_id and execution_id are required.')

            now_ns = self.get_clock().now().nanoseconds
            self._validate_stamp(message.header.stamp, 'input', now_ns)
            self._validate_stamp(message.cube_pose.header.stamp, 'cube pose', now_ns)
            self._validate_stamp(message.palm_pose.header.stamp, 'palm pose', now_ns)
            self._validate_stamp(
                message.leap_joint_state.header.stamp, 'LEAP joint state', now_ns)

            if (message.cube_pose.header.frame_id != self._world_frame
                    or message.palm_pose.header.frame_id != self._world_frame):
                raise ValueError(
                    'cube_pose and palm_pose must use the configured world_frame.')

            joint_state = message.leap_joint_state
            q_meas = ordered_positions(joint_state.name, joint_state.position)
            q_cmd = _finite_vector(
                message.commanded_joint_positions, 16,
                'commanded_joint_positions')

            cube_position = _finite_vector([
                message.cube_pose.pose.position.x,
                message.cube_pose.pose.position.y,
                message.cube_pose.pose.position.z,
            ], 3, 'cube position')
            palm_position = _finite_vector([
                message.palm_pose.pose.position.x,
                message.palm_pose.pose.position.y,
                message.palm_pose.pose.position.z,
            ], 3, 'palm position')
            cube_quat = _unit_quaternion_xyzw(
                message.cube_pose.pose.orientation, 'cube pose')
            goal_quat = _unit_quaternion_xyzw(
                message.goal_orientation, 'goal orientation')

            identity = (message.scan_id, message.execution_id)
            stamps = tuple(_stamp_ns(value.header.stamp) for value in (
                message.cube_pose, message.palm_pose, joint_state))
            if identity == self._last_identity and self._last_source_stamps is not None:
                if (any(a < b for a, b in zip(stamps, self._last_source_stamps))
                        or stamps[-1] == self._last_source_stamps[-1]):
                    self.get_logger().warning('LEAP duplicate/out-of-order source sample ignored.')
                    return

            # Build/infer on a candidate history. Failed inference/publication
            # cannot advance accepted source stamps or commit half a sample.
            builder = deepcopy(self._builder)
            new_history = (identity != self._last_identity or not self._history_valid
                           or self._last_accepted_at is None
                           or now_ns-self._last_accepted_at > self._max_age_ms*1_000_000)
            if new_history:
                builder.reset()  # Preserve the108-value policy's zero-padded reset.
            elif not np.isclose(abs(float(goal_quat @ self._last_goal)), 1., rtol=0., atol=1e-9):
                builder.fill_orientation_history(cube_quat, goal_quat)
            # A shadow proposal was never sent to hardware. The current input
            # contract has no applied-action acknowledgement; do not pretend
            # that the preceding proposal was the previous executed action.
            builder.set_last_action(np.zeros(16))
            observation = builder.build(
                q_meas, q_cmd, palm_position, cube_position,
                cube_quat, goal_quat)
            action = _finite_vector(self._policy.infer(observation), 16, 'Policy action')
            if np.any(np.abs(action) > 1.):
                raise ValueError('Policy action is outside the normalized range.')

            output = HandPolicyAction()
            output.header = message.header
            output.hand_id = 'leap_hand'
            output.scan_id = message.scan_id
            output.execution_id = message.execution_id
            output.element_names = list(JOINT_NAMES)
            output.values = [float(value) for value in action]
            output.shadow_only = True
            self._action_publisher.publish(output)
            self._builder = builder
            self._last_identity = identity
            self._last_source_stamps = stamps
            self._last_goal = goal_quat.copy()
            self._last_accepted_at = now_ns
            self._history_valid = True
        except (ValueError, KeyError, RuntimeError) as exc:
            self._builder.reset()
            self._history_valid = False
            self.get_logger().warning(f'LEAP policy input rejected: {exc}')


def main(args=None):
    rclpy.init(args=args)
    node = LeapPolicyShadowNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
