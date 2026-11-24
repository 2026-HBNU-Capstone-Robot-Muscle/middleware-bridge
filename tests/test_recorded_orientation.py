"""User color transitions, all cube orientations, route ownership and failures."""
from concurrent.futures import Future
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/control/leap_hand_control'))
from leap_hand_control.hardware_adapter import AdapterError
from leap_hand_control.recorded_orientation import (
    COLOR_OBSERVATIONS, FACES, ORIENTATIONS, PERMUTATIONS, NOMINAL_SECONDS,
    FACE_UP_PRIMITIVE, apply, checked_order, observed_permutation, route_to_up)
import test_recorded_backend as backend_helpers
from test_recorded_backend import command


def face_command(order='URFDLB', target='R', **extra):
    return command(primitive_id=FACE_UP_PRIMITIVE, face_direction_order=order,
                   target_face=target, target_face_direction_index=order.index(target), **extra)


class OrientationTests(unittest.TestCase):
    def test_reported_colors_uniquely_determine_both_signed_rotations(self):
        for kind, expected in PERMUTATIONS.items():
            self.assertEqual(observed_permutation(COLOR_OBSERVATIONS[kind+'_before'],
                COLOR_OBSERVATIONS[kind+'_after']), expected)
        h = apply(FACES, 'horizontal')
        self.assertEqual(h, 'UFLDBR')
        self.assertEqual(apply(h, 'vertical'), 'RFULBD')

    def test_24_proper_orientations_and_four_turn_identity(self):
        self.assertEqual(len(ORIENTATIONS), 24)
        for kind in PERMUTATIONS:
            state = FACES
            for _ in range(4):
                state = apply(state, kind)
            self.assertEqual(state, FACES)
        with self.assertRaises(ValueError):
            checked_order('UF RDLB')
        with self.assertRaises(ValueError):
            checked_order('URBDLF')  # Mirror, not a physical cube rotation.

    def test_all_144_current_orientation_target_pairs_reach_requested_up_face(self):
        for state in ORIENTATIONS:
            for face in FACES:
                route, expected = route_to_up(state, face)
                actual = state
                for kind in route:
                    actual = apply(actual, kind)
                self.assertEqual(actual, expected)
                self.assertEqual(actual[0], face)
                self.assertLessEqual(len(route), 4)
                if state[0] == face:
                    self.assertEqual(route, ())

    def test_known_routes_use_existing_forward_paths_and_less_nominal_time(self):
        self.assertEqual(route_to_up(FACES, 'R')[0], ('horizontal', 'vertical'))
        self.assertEqual(route_to_up(FACES, 'D')[0], ('vertical', 'vertical'))
        self.assertEqual(route_to_up(FACES, 'F')[0], ('horizontal', 'horizontal', 'vertical'))
        self.assertLess(2*NOMINAL_SECONDS['horizontal']+NOMINAL_SECONDS['vertical'],
                        3*NOMINAL_SECONDS['vertical'])

    def test_ambiguous_or_inconsistent_observation_is_rejected(self):
        with self.assertRaises(ValueError):
            observed_permutation({'U':'a','F':'b','R':'c'}, {'U':'a','F':'x','R':'y'})
        with self.assertRaises(ValueError):
            observed_permutation({'U':'a','F':'b','R':'c'}, {'U':'a','F':'a','R':'c'})


class BackendOrientationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the tested memory I/O setup, without importing its test class as
        # a discoverable test class in this module.
        self.helper = backend_helpers.BackendTests()
        self.core = self.helper.ready()
        self.addCleanup(self.helper.doCleanups)
        self.backend = self.helper.backend

    def finish(self, request):
        future = Future()
        self.core.submit(request, future)
        self.helper.until(future.done)
        self.assertTrue(future.result()[0])
        return future

    def test_orientation_updates_only_after_complete_motion(self):
        request = face_command()
        future = Future()
        self.core.submit(request, future)
        self.core.tick(time.monotonic())
        status = self.backend.orientation_status()
        self.assertFalse(status['orientation_state_known'])
        self.assertEqual(status['predicted_face_direction_order'][0], 'R')
        self.helper.until(future.done)
        self.assertTrue(self.backend.orientation_status()['orientation_state_known'])
        self.assertEqual(self.backend.face_order[0], 'R')

    def test_next_request_must_match_the_completed_direction_state(self):
        self.finish(face_command())
        after = self.backend.face_order
        with self.assertRaisesRegex(AdapterError, 'disagrees'):
            self.core.submit(face_command(target='F', step_index=2), Future())
        self.finish(face_command(after, 'F', step_index=2))
        self.assertEqual(self.backend.face_order[0], 'F')

    def test_direct_command_updates_a_known_state_but_never_seeds_from_metadata(self):
        self.finish(command())
        self.assertIsNone(self.backend.face_order)
        self.finish(face_command(step_index=2))
        before = self.backend.face_order
        self.finish(command('vertical', step_index=3))
        self.assertEqual(self.backend.face_order, apply(before, 'vertical'))

    def test_long_route_has_a_budget_covering_all_legs(self):
        request = face_command(target='L')
        route, _ = route_to_up(FACES, 'L')
        future = Future()
        self.core.submit(request, future)
        self.assertGreater(self.core.job['timeout'], sum(NOMINAL_SECONDS[k] for k in route)+290.)
        self.assertGreater(self.core.job['timeout'], 900.)

    def test_cancel_mid_route_does_not_claim_a_new_orientation(self):
        self.helper.runtime.duration = 10.
        future = Future()
        self.core.submit(face_command(), future)
        self.core.tick(time.monotonic())
        self.core.cancel(future)
        self.core.tick(time.monotonic())
        self.assertFalse(future.result()[0])
        self.assertFalse(self.backend.orientation_status()['orientation_state_known'])


if __name__ == '__main__':
    unittest.main()
