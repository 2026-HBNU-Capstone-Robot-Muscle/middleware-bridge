"""Exercise production shadow callbacks; no ROS installation, serial or camera."""
import importlib
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace as NS
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/control/leap_hand_control'))
from leap_hand_control.joint_mapping import JOINT_NAMES
from leap_hand_control.observation_builder import LeapObservationBuilder


def load_node():
    names=('rclpy','rclpy.node','rclpy.qos','ament_index_python',
           'ament_index_python.packages','system_interfaces','system_interfaces.msg')
    modules={name:ModuleType(name) for name in names}
    modules['rclpy.node'].Node=object
    modules['rclpy.qos'].QoSProfile=object
    modules['ament_index_python.packages'].get_package_share_directory=lambda _:''
    class Action:pass
    modules['system_interfaces.msg'].HandPolicyAction=Action
    modules['system_interfaces.msg'].LeapPolicyInput=object
    with patch.dict(sys.modules,modules):
        return importlib.import_module('leap_hand_control.policy_shadow_node')


MODULE=load_node()


class Tests(unittest.TestCase):
    def setUp(self):
        self.at=10_000_000_000;self.outputs=[];self.observations=[];self.warnings=[]
        self.node=object.__new__(MODULE.LeapPolicyShadowNode)
        n=self.node;n._world_frame='world';n._max_age_ms=150
        n._builder=LeapObservationBuilder();n._last_identity=None;n._last_source_stamps=None
        n._last_goal=None;n._last_accepted_at=None;n._history_valid=False
        def infer(obs):self.observations.append(obs.copy());return np.full(16,.25)
        n._policy=NS(infer=infer)
        n._action_publisher=NS(publish=self.outputs.append)
        n.get_clock=lambda:NS(now=lambda:NS(nanoseconds=self.at))
        n.get_logger=lambda:NS(warning=self.warnings.append)
    def stamp(self,at):return NS(sec=at//1_000_000_000,nanosec=at%1_000_000_000)
    def message(self,*,at=None,execution='exec',error=.01):
        at=self.at if at is None else at
        def header():return NS(stamp=self.stamp(at),frame_id='world')
        def pose():return NS(header=header(),pose=NS(position=NS(x=0.,y=0.,z=0.),orientation=NS(w=1.,x=0.,y=0.,z=0.)))
        return NS(header=header(),scan_id='scan',execution_id=execution,target_face='R',
            cube_pose=pose(),palm_pose=pose(),goal_orientation=NS(w=1.,x=0.,y=0.,z=0.),
            leap_joint_state=NS(header=header(),name=list(JOINT_NAMES),position=[error]*16),
            commanded_joint_positions=[0.]*16)
    def next(self,**kw):self.at+=75_000_000;return self.message(**kw)
    def test_unsent_actions_never_enter_next_observation(self):
        self.node._on_input(self.message());self.node._on_input(self.next())
        self.assertEqual(len(self.outputs),2)
        self.assertTrue(all(o.shadow_only for o in self.outputs))
        self.assertTrue(all(np.all(obs[91:107]==0) for obs in self.observations))
        self.assertTrue(np.all(self.node._builder.last_act==0))
    def test_duplicate_and_reordered_encoder_sample_do_not_advance_history(self):
        first=self.message();self.node._on_input(first)
        before=self.node._builder.qpos_err_hist.copy()
        self.at+=25_000_000;duplicate=self.message()
        duplicate.leap_joint_state.header=first.leap_joint_state.header
        self.node._on_input(duplicate)
        older=self.message(at=9_999_000_000);self.node._on_input(older)
        self.assertEqual(len(self.outputs),1);self.assertEqual(len(self.observations),1)
        np.testing.assert_array_equal(before,self.node._builder.qpos_err_hist)
    def test_new_execution_does_not_reuse_old_histories(self):
        self.node._on_input(self.message(error=.1))
        self.node._on_input(self.next(execution='new',error=.2))
        np.testing.assert_array_equal(self.observations[-1][32:64],np.zeros(32))
        np.testing.assert_allclose(self.observations[-1][16:32],.2)
    def test_gap_resets_history_even_if_new_sources_are_fresh(self):
        self.node._on_input(self.message(error=.1));self.at+=200_000_000
        self.node._on_input(self.message(error=.2))
        np.testing.assert_array_equal(self.observations[-1][32:64],np.zeros(32))
    def test_new_goal_reseeds_only_orientation_history(self):
        self.node._on_input(self.message(error=.1));m=self.next(error=.2)
        m.goal_orientation=NS(w=np.sqrt(.5),x=0.,y=0.,z=np.sqrt(.5))
        self.node._on_input(m)
        np.testing.assert_allclose(self.observations[-1][73:91],np.tile([-1.,0,0,0,0,1.],3),atol=1e-12)
        np.testing.assert_allclose(self.observations[-1][32:48],.1)
    def test_quaternion_sign_change_is_not_a_new_goal(self):
        self.node._on_input(self.message());m=self.next();m.goal_orientation.w=-1.
        with patch.object(LeapObservationBuilder,'fill_orientation_history',side_effect=AssertionError('same rotation')):
            self.node._on_input(m)
        self.assertEqual(len(self.outputs),2)
    def test_stale_pose_does_not_publish_and_invalidates_history(self):
        self.node._on_input(self.message());m=self.next()
        m.cube_pose.header.stamp=self.stamp(self.at-151_000_000)
        self.node._on_input(m);self.assertEqual(len(self.outputs),1);self.assertFalse(self.node._history_valid)
        self.node._on_input(self.next(error=.2))
        np.testing.assert_array_equal(self.observations[-1][32:64],np.zeros(32))
    def test_malformed_pose_or_joint_names_do_not_reach_actor(self):
        bad=self.message();bad.cube_pose.pose.orientation=NS(w=0.,x=0.,y=0.,z=0.)
        self.node._on_input(bad)
        bad=self.message();bad.leap_joint_state.name[-1]=bad.leap_joint_state.name[0]
        self.node._on_input(bad)
        self.assertEqual(self.observations,[]);self.assertEqual(self.outputs,[])
    def test_actor_failure_cannot_commit_sample_or_publish(self):
        self.node._on_input(self.message());stamps=self.node._last_source_stamps
        self.node._policy.infer=lambda _:(_ for _ in ()).throw(ValueError('bad actor'))
        self.node._on_input(self.next())
        self.assertEqual(self.node._last_source_stamps,stamps)
        self.assertEqual(len(self.outputs),1);self.assertFalse(self.node._history_valid)
    def test_invalid_actor_output_is_not_clipped_into_an_action(self):
        for output in ([np.nan]*16,[1.01]*16,[0.]*15):
            self.node._policy.infer=lambda _,output=output:output
            self.node._on_input(self.message())
        self.assertEqual(self.outputs,[])
    def test_failed_publish_cannot_commit_sample(self):
        self.node._action_publisher.publish=lambda _:(_ for _ in ()).throw(RuntimeError('publisher failed'))
        self.node._on_input(self.message());self.assertIsNone(self.node._last_source_stamps)
        self.assertFalse(self.node._history_valid)


if __name__=='__main__':unittest.main()
