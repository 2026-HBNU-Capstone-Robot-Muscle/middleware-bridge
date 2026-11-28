"""Build the reference LEAP policy's 108-value observation from ROS inputs."""

import numpy as np


from leap_hand_control.joint_mapping import JOINT_NAMES
HISTORY_LEN = 3
NQ = 16


def _vector(values, size, label):
    value = np.asarray(values, dtype=np.float64)
    if value.shape != (size,) or not np.isfinite(value).all():
        raise ValueError(f'{label} must contain{size} finite values.')
    return value


def _unit_quaternion(values, label):
    value = _vector(values, 4, label)
    if not np.isclose(np.linalg.norm(value), 1.0, rtol=0., atol=1e-6):
        raise ValueError(f'{label} must be a unit quaternion in w,x,y,z order.')
    return value


def quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ], dtype=np.float64)


def quat_inv(q):
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=np.float64) / float(q @ q)


def quat_to_mat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z),
         2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z),
         2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x),
         1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


class LeapObservationBuilder:
    """Maintain the same three-sample histories as the reference deployment."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.qpos_err_hist = np.zeros(HISTORY_LEN * NQ)
        self.cube_pos_err_hist = np.zeros(HISTORY_LEN * 3)
        self.cube_ori_err_hist = np.zeros(HISTORY_LEN * 6)
        self.last_act = np.zeros(NQ)

    def fill_orientation_history(self, cube_quat_wxyz, goal_quat_wxyz):
        """Seed all three orientation-history slots from an explicit plan state."""
        cube_quat = _unit_quaternion(cube_quat_wxyz, 'Cube orientation')
        goal_quat = _unit_quaternion(goal_quat_wxyz, 'Goal orientation')
        error = self._xmat_diff(cube_quat, goal_quat)
        self.cube_ori_err_hist = np.tile(error, HISTORY_LEN)

    @staticmethod
    def _xmat_diff(cube_quat, goal_quat):
        return quat_to_mat(quat_mul(cube_quat, quat_inv(goal_quat))).ravel()[3:]

    def build(self, q_meas, q_cmd, palm_position, cube_position,
              cube_quat_wxyz, goal_quat_wxyz):
        # Validate all fields before preparing any new history. Rejection must
        # not leave partially advanced joint/position histories.
        q_meas = _vector(q_meas, NQ, 'Measured joint positions')
        q_cmd = _vector(q_cmd, NQ, 'Commanded joint positions')
        palm_position = _vector(palm_position, 3, 'Palm position')
        cube_position = _vector(cube_position, 3, 'Cube position')
        cube_quat_wxyz = _unit_quaternion(cube_quat_wxyz, 'Cube orientation')
        goal_quat_wxyz = _unit_quaternion(goal_quat_wxyz, 'Goal orientation')
        qe = q_meas - q_cmd
        q_history = np.roll(self.qpos_err_hist, NQ)
        q_history[:NQ] = qe

        position_error = (
            np.asarray(palm_position, dtype=np.float64)
            - np.asarray(cube_position, dtype=np.float64))
        position_history = np.roll(self.cube_pos_err_hist, 3)
        position_history[:3] = position_error

        qd = quat_mul(cube_quat_wxyz, quat_inv(goal_quat_wxyz))
        orientation_history = np.roll(self.cube_ori_err_hist, 6)
        orientation_history[:6] = quat_to_mat(qd).ravel()[3:]

        qn = qd / np.linalg.norm(qd)
        orientation_error = 2.0 * np.arcsin(min(np.linalg.norm(qn[1:]), 1.0))
        observation = np.concatenate([
            q_meas,
            q_history,
            position_history,
            orientation_history,
            self.last_act,
            [orientation_error],
        ])
        if observation.shape != (108,) or not np.all(np.isfinite(observation)):
            raise ValueError('LEAP observation must be 108 finite values.')
        self.qpos_err_hist = q_history
        self.cube_pos_err_hist = position_history
        self.cube_ori_err_hist = orientation_history
        return observation

    def set_last_action(self, action):
        action = np.asarray(action, dtype=np.float64)
        if action.shape != (NQ,) or not np.all(np.isfinite(action)):
            raise ValueError('LEAP action must be 16 finite values.')
        self.last_act = action.copy()
