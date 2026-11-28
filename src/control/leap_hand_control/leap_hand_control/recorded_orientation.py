"""Whole-cube direction routing from the user's fixed-G color observations.

Slot order is U,R,F,D,L,B in the fixed hand/view frame. Permutations contain
the old slot occupying each new slot. No motor path is reversed or synthesized.
"""
from heapq import heappop, heappush

FACES = 'URFDLB'
FACE_UP_PRIMITIVE = 'orient_face_up_and_support'
PERMUTATIONS = {
    'horizontal': (0, 2, 4, 3, 5, 1),  # U fixed; old F becomes new R.
    'vertical': (5, 1, 0, 2, 4, 3),    # R fixed; old U becomes new F.
}
NOMINAL_SECONDS = {'horizontal': 5278*.075, 'vertical': 5549*.075, 'grip': 0.}
COLOR_OBSERVATIONS = {
    'horizontal_before': {'U': 'green', 'F': 'yellow', 'R': 'red'},
    'horizontal_after': {'U': 'green', 'F': 'orange', 'R': 'yellow'},
    'vertical_before': {'U': 'green', 'F': 'orange', 'R': 'yellow'},
    'vertical_after': {'U': 'red', 'F': 'green', 'R': 'yellow'},
}


def apply(order, kind):
    return ''.join(order[i] for i in PERMUTATIONS[kind]) if kind != 'grip' else order


def orientations():
    found, pending = {FACES}, [FACES]
    while pending:
        state = pending.pop()
        for kind in PERMUTATIONS:
            after = apply(state, kind)
            if after not in found:
                found.add(after)
                pending.append(after)
    return frozenset(found)


ORIENTATIONS = orientations()


def checked_order(order):
    if not isinstance(order, str) or order not in ORIENTATIONS:
        raise ValueError('Direction order must be one of the24 proper URFDLB orientations in the fixed-G frame.')
    return order


def observed_permutation(before, after):
    """Two independent observed faces determine one proper cube rotation."""
    if (set(before) != {'U', 'F', 'R'} or set(after) != {'U', 'F', 'R'}
            or len(set(before.values())) != 3 or len(set(after.values())) != 3):
        raise ValueError('Three distinct visible center colors are required on each side.')
    if len(set(before.values()) & set(after.values())) < 2:
        raise ValueError('At least two independent observed faces must determine the rotation.')
    candidates = []
    for order in ORIENTATIONS:
        good = True
        for destination, color in after.items():
            origin = order[FACES.index(destination)]
            if origin in before and before[origin] != color:
                good = False
            for old_slot, old_color in before.items():
                if old_color == color and origin != old_slot:
                    good = False
        if good:
            candidates.append(tuple(FACES.index(x) for x in order))
    if len(candidates) != 1:
        raise ValueError('Observed color transitions do not determine a unique proper rotation.')
    return candidates[0]


def validate_observations():
    if COLOR_OBSERVATIONS['horizontal_after'] != COLOR_OBSERVATIONS['vertical_before']:
        raise ValueError('Observed H/V handoff colors disagree.')
    for kind, permutation in PERMUTATIONS.items():
        actual = observed_permutation(COLOR_OBSERVATIONS[kind+'_before'],
                                      COLOR_OBSERVATIONS[kind+'_after'])
        if actual != permutation:
            raise ValueError('Recorded direction mapping differs from user observations: '+kind)


def route_to_up(order, target):
    """Choose the least nominal time using only existing positive H/V motions."""
    checked_order(order)
    if target not in FACES or len(target) != 1:
        raise ValueError('Expected a single URFDLB target face.')
    heap, best = [(0., 0, (), order)], {}
    while heap:
        cost, count, route, state = heappop(heap)
        if state in best:
            continue
        best[state] = cost
        if state[0] == target:
            return route, state
        for kind in PERMUTATIONS:
            after = apply(state, kind)
            if after not in best:
                heappush(heap, (cost+NOMINAL_SECONDS[kind], count+1, route+(kind,), after))
    raise ValueError('Target is unreachable using the recorded paths.')


def calibration_report():
    validate_observations()
    return dict(observation_source='User report2026-11-24',
                raw_up_front_right='초/노/빨 초/주/노 초/주/노 빨/초/노',
                observations=COLOR_OBSERVATIONS, slot_order=FACES,
                permutations={k: list(v) for k,v in PERMUTATIONS.items()},
                interpretation='after_slot = before_slot[permutation]',
                fixed_frame='Same observer/hand frame at G, after rotation and return',
                source_manifest_sha256='a4f3c93ca9c606e3874203dabc61c0e9b3e3cc61ff4bcca52d5e4d3543f1498e',
                horizontal_candidate_sha256='01283c7624a9f6db52e88c2f838fec604e19274ce61f35f54b27f3e2960256cc',
                vertical_candidate_sha256='41af28ada212563aa81558f081e5a7eb9f9712e7bd0868eca501327e65fa8591',
                axis_and_sign_user_observed=True, rotation_angle_measured=False,
                repeated_orientation_accuracy_verified=False,
                continuous_cube_pose_sensor_used=False)


validate_observations()
