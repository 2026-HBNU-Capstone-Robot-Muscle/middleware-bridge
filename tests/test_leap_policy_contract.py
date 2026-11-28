"""Known joint motions, training-observation fixtures and atomic rejection."""
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/control/leap_hand_control'))
from leap_hand_control.joint_mapping import (
    JOINT_NAMES, MOTOR_IDS, TICK_RAD, sim_positions, physical_ticks, ordered_positions)
from leap_hand_control.observation_builder import LeapObservationBuilder
from leap_hand_control.policy_adapter import LeapPolicyAdapter


class MappingTests(unittest.TestCase):
    def test_each_physical_motor_changes_only_its_named_joint(self):
        expected = {1:'th_ipl',2:'th_mcp',3:'th_axl',4:'th_cmc',
                    5:'if_dip',6:'if_rot',7:'if_pip',8:'if_mcp',
                    9:'mf_dip',10:'mf_rot',11:'mf_pip',12:'mf_mcp',
                    13:'rf_dip',14:'rf_rot',15:'rf_pip',16:'rf_mcp'}
        for motor, name in expected.items():
            raw = np.full(16,2048); raw[motor-1] += 256
            sim = np.asarray(sim_positions(raw))
            self.assertEqual([JOINT_NAMES[i] for i in np.flatnonzero(sim)], [name])
            self.assertAlmostEqual(sim[JOINT_NAMES.index(name)], np.pi/8)
    def test_roundtrip_including_negative_and_above_single_turn(self):
        rng = np.random.default_rng(116)
        for raw in rng.integers(-4096,8193,size=(128,16)):
            self.assertEqual(physical_ticks(sim_positions(raw)),raw.tolist())
    def test_named_joint_order_is_not_motor_number_order(self):
        values=np.arange(16)/10
        self.assertTrue(np.array_equal(ordered_positions(JOINT_NAMES[::-1],values[::-1]),values))
        with self.assertRaises(ValueError):ordered_positions(JOINT_NAMES[:-1]+(JOINT_NAMES[0],),values)
        with self.assertRaises(ValueError):ordered_positions(JOINT_NAMES,values[:-1])
    def test_no_silent_integer_truncation_or_nonfinite_conversion(self):
        for raw in ([2048.25]*16,[np.nan]*16,[2048]*15):
            with self.assertRaises(ValueError):sim_positions(raw)
        for values in ([np.inf]*16,[1e308]*16,[0.]*17):
            with self.assertRaises(ValueError):physical_ticks(values)


class ObservationTests(unittest.TestCase):
    def args(self):
        return [np.arange(16)/10,np.arange(16)/10+.01,np.ones(3)*.1,np.zeros(3),np.array([1.,0,0,0]),np.array([1.,0,0,0])]
    def test_reference_128_sample_sequence_and_actor_512_samples(self):
        f=np.load(Path(__file__).parent/'fixtures/leap_policy_reference.npz',allow_pickle=False)
        builder=LeapObservationBuilder()
        for i in range(len(f['q_meas'])):
            if f['fill_orientation'][i]:builder.fill_orientation_history(f['cube_quat'][i],f['goal_quat'][i])
            actual=builder.build(*(f[k][i] for k in ('q_meas','q_cmd','palm','cube','cube_quat','goal_quat')))
            np.testing.assert_allclose(actual,f['observations'][i],rtol=0,atol=1e-12)
            builder.set_last_action(f['applied_actions'][i])
        actor=LeapPolicyAdapter(ROOT/'src/control/leap_hand_control/models/policy_np.npz')
        for obs,expected in zip(f['actor_inputs'],f['actor_outputs']):
            np.testing.assert_allclose(actor.infer(obs),expected,rtol=0,atol=1e-12)
    def test_invalid_input_cannot_partially_advance_any_history(self):
        builder=LeapObservationBuilder();builder.build(*self.args())
        before={k:v.copy() for k,v in vars(builder).items()}
        bad=[(0,np.zeros(15)),(1,np.zeros((1,16))),(2,np.array([np.nan,0,0])),
             (3,np.zeros(4)),(4,np.zeros(4)),(5,np.array([2.,0,0,0]))]
        for slot,value in bad:
            args=self.args();args[slot]=value
            with self.assertRaises(ValueError):builder.build(*args)
            for name,expected in before.items():np.testing.assert_array_equal(getattr(builder,name),expected)
    def test_invalid_orientation_seed_preserves_history(self):
        b=LeapObservationBuilder();b.fill_orientation_history([1.,0,0,0],[1.,0,0,0]);old=b.cube_ori_err_hist.copy()
        with self.assertRaises(ValueError):b.fill_orientation_history([0.,0,0,0],[1.,0,0,0])
        np.testing.assert_array_equal(old,b.cube_ori_err_hist)
    def test_previous_action_is_explicit_and_copied(self):
        b=LeapObservationBuilder();action=np.linspace(-1,1,16);b.set_last_action(action);action[:]=0
        np.testing.assert_allclose(b.build(*self.args())[91:107],np.linspace(-1,1,16))
    def test_wrong_policy_input_dimension_rejected(self):
        actor=LeapPolicyAdapter(ROOT/'src/control/leap_hand_control/models/policy_np.npz')
        for size in (96,102,110):
            with self.assertRaises(ValueError):actor.infer(np.zeros(size))


if __name__=='__main__':unittest.main()
