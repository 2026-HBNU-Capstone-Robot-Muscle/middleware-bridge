"""Measured physical ID1..16 order and simulation radians, without actuation."""

import math
import numpy as np

JOINT_NAMES = (
    'if_mcp', 'if_rot', 'if_pip', 'if_dip',
    'mf_mcp', 'mf_rot', 'mf_pip', 'mf_dip',
    'rf_mcp', 'rf_rot', 'rf_pip', 'rf_dip',
    'th_cmc', 'th_axl', 'th_mcp', 'th_ipl',
)
MOTOR_IDS = (8, 6, 7, 5, 12, 10, 11, 9, 16, 14, 15, 13, 4, 3, 2, 1)
TICK_RAD = 2.0 * math.pi / 4096.0


def _vector(values, label):
    result = np.asarray(values, dtype=np.float64)
    if result.shape != (16,) or not np.isfinite(result).all():
        raise ValueError(f'{label} must contain16 finite values.')
    return result


def sim_positions(physical_ticks):
    """ID1..16 encoder ticks -> named simulation radians; no wrap or clipping."""
    raw = _vector(physical_ticks, 'Physical ticks')
    if np.any(raw != np.rint(raw)):
        raise ValueError('Expected16 finite integer ticks in physical ID order.')
    return ((raw[np.asarray(MOTOR_IDS)-1]-2048)*TICK_RAD).tolist()


def physical_ticks(sim_radians):
    """Inverse conversion only; does not approve ranges or transmit a goal."""
    values = _vector(sim_radians, 'Simulation joint positions')
    with np.errstate(over='raise', invalid='raise'):
        try:
            ticks = np.rint(values / TICK_RAD + 2048)
        except FloatingPointError as exc:
            raise ValueError('Simulation positions exceed integer tick representation.') from exc
    if np.any(np.abs(ticks) >= np.iinfo(np.int64).max):
        raise ValueError('Simulation positions exceed integer tick representation.')
    result = np.empty(16, dtype=np.int64)
    result[np.asarray(MOTOR_IDS)-1] = ticks.astype(np.int64)
    return result.tolist()


def ordered_positions(names, positions):
    """ROS named radians -> policy order, rejecting duplicate/missing names."""
    names = tuple(names)
    if len(names) != 16 or set(names) != set(JOINT_NAMES):
        raise ValueError('Expected the16 distinct reference joint names.')
    values = _vector(positions, 'Named joint positions')
    by_name = dict(zip(names, values))
    return np.asarray([by_name[name] for name in JOINT_NAMES], dtype=np.float64)
