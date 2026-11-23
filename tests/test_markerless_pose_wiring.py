"""ROS publication/synchronization contract using the production callbacks."""
from collections import OrderedDict
import importlib,json,sys,unittest
from pathlib import Path
from types import ModuleType,SimpleNamespace as NS
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/perception/cube_detection'))
from cube_detection.markerless_pipeline import Registration
from cube_detection.markerless_features import ColorReference


def load_node():
    names=('rclpy','rclpy.node','rclpy.qos','cv_bridge','geometry_msgs','geometry_msgs.msg',
           'sensor_msgs','sensor_msgs.msg','std_msgs','std_msgs.msg','system_interfaces','system_interfaces.msg')
    modules={name:ModuleType(name) for name in names}
    class Pose:
        def __init__(self):self.header=NS();self.pose=NS(position=NS(),orientation=NS())
    class Text:
        pass
    modules['rclpy.node'].Node=object
    qos=modules['rclpy.qos'];qos.DurabilityPolicy=NS(TRANSIENT_LOCAL=1);qos.ReliabilityPolicy=NS(RELIABLE=1);qos.QoSProfile=object;qos.qos_profile_sensor_data=object()
    modules['cv_bridge'].CvBridge=object;modules['cv_bridge'].CvBridgeError=ValueError
    modules['geometry_msgs.msg'].PoseStamped=Pose;modules['sensor_msgs.msg'].Image=object
    modules['std_msgs.msg'].String=Text
    modules['system_interfaces.msg'].CubeColorReference=object;modules['system_interfaces.msg'].FaceDetectionArray=object
    with patch.dict(sys.modules,modules):return importlib.import_module('cube_detection.markerless_pose_node')


MODULE=load_node()
COLORS=[[20,20,230],[20,150,240],[220,40,20],[20,230,230],[40,170,20],[235,235,235]]


class Tests(unittest.TestCase):
    def setUp(self):
        self.at=10_000_000_000;self.calls=0;self.candidates=[];self.cubes=[];self.palms=[];self.status=[]
        n=self.node=object.__new__(MODULE.MarkerlessCubePoseNode)
        n.max_age_ms=150;n.images=OrderedDict();n.detections=OrderedDict();n.last_stamp=0;n.reference_stamp=0
        self.registration=Registration()
        n.pipeline=NS(registration=self.registration,reference=None,process=self.process,
            set_reference=lambda colors,scan:setattr(n.pipeline,'reference',ColorReference(colors,scan)))
        n.bridge=NS(imgmsg_to_cv2=lambda m,**_:m.frame)
        n.candidate_pub=NS(publish=self.candidates.append);n.cube_pub=NS(publish=self.cubes.append)
        self.relative=[];n.relative_pub=NS(publish=self.relative.append)
        n.palm_pub=NS(publish=self.palms.append);n.status_pub=NS(publish=lambda m:self.status.append(json.loads(m.data)))
        n.get_clock=lambda:NS(now=lambda:NS(nanoseconds=self.at))
    def process(self,*_):
        self.calls+=1
        result=dict(rotation=np.eye(3),translation=np.array([0.,0.,.4]),policy_pose_ready=self.registration.ready,
            scan_id='s',visible_faces=['F','U'],rms_px=.5,camera_binding_verified=self.registration.camera_binding_verified,
            registration_verified=self.registration.ready,feature_rejections=[])
        if self.registration.ready:result.update(cube_world=np.eye(4),palm_world=np.eye(4))
        else:result['policy_rejection']='registration unverified'
        return result
    def header(self,stamp=None,frame='camera_optical_frame'):
        value=self.at if stamp is None else stamp
        return NS(stamp=NS(sec=value//1_000_000_000,nanosec=value%1_000_000_000),frame_id=frame)
    def messages(self):
        return NS(header=self.header(),frame=np.zeros((4,4,3),np.uint8)),NS(header=self.header(),detections=[])
    def pair(self):
        image,detection=self.messages()
        with patch.object(MODULE.time,'monotonic',return_value=1.):self.node._image(image);self.node._detection(detection)
        return image,detection
    def test_candidate_only_until_registration_is_verified(self):
        self.pair();self.assertEqual(len(self.candidates),1);self.assertEqual(self.cubes,[]);self.assertEqual(self.palms,[])
        self.assertFalse(self.status[-1]['policy_pose_ready'])
    def test_registered_pair_uses_same_original_exposure_and_world_frame(self):
        self.node.pipeline.registration=self.registration=Registration(True,True,True,True,'world','camera_optical_frame',np.eye(4),np.eye(4),np.eye(4))
        image,_=self.pair();self.assertEqual(len(self.cubes),1);self.assertEqual(len(self.palms),1)
        for pose in self.cubes+self.palms:
            self.assertEqual(pose.header.frame_id,'world');self.assertEqual(pose.header.stamp.sec,image.header.stamp.sec)
    def test_relative_candidate_is_separate_from_policy_pose(self):
        original=self.node.pipeline.process
        def relative(*args):
            result=original(*args);result['cube_in_wrist_candidate']=np.eye(4);return result
        self.node.pipeline.process=relative;image,_=self.pair()
        self.assertEqual(len(self.relative),1);self.assertEqual(self.cubes,[]);self.assertEqual(self.palms,[])
        self.assertEqual(self.relative[0].header.frame_id,'leap_wrist_marker_41')
        self.assertEqual(self.relative[0].header.stamp.sec,image.header.stamp.sec)
    def test_mismatched_exposure_cannot_be_fused(self):
        image,detection=self.messages();detection.header=self.header(self.at-1)
        self.node._image(image);self.node._detection(detection)
        self.assertEqual(self.calls,0)
    def test_stale_and_future_inputs_rejected_before_processing(self):
        for delta in (-151_000_000,1_000_000):
            image,_=self.messages();image.header=self.header(self.at+delta);self.node._image(image)
        self.assertEqual(self.calls,0);self.assertEqual(len(self.node.images),0)
    def test_duplicate_inputs_never_republish_with_a_new_stamp(self):
        image,detection=self.pair();self.at+=50_000_000
        self.node._image(image);self.node._detection(detection)
        self.assertEqual(len(self.candidates),1);self.assertEqual(self.calls,1)
    def test_wrong_camera_frame_rejected(self):
        image,_=self.messages();image.header.frame_id='other_camera';self.node._image(image)
        self.assertEqual(self.calls,0)
    def test_slow_processing_does_not_publish_a_stale_pose(self):
        image,detection=self.messages()
        with patch.object(MODULE.time,'monotonic',side_effect=[1.,1.,1.151]):
            self.node._image(image);self.node._detection(detection)
        self.assertEqual(self.candidates,[]);self.assertFalse(self.status[-1]['candidate_valid'])
    def test_invalid_new_reference_clears_previous_palette_and_cached_images(self):
        self.node._reference(NS(header=self.header(),scan_id='s',center_bgr=np.array(COLORS).ravel()))
        self.assertIsNotNone(self.node.pipeline.reference)
        image,_=self.messages();self.node._image(image)
        self.node._reference(NS(header=self.header(),scan_id='new',center_bgr=[0]*18))
        self.assertIsNone(self.node.pipeline.reference);self.assertEqual(len(self.node.images),0)
    def test_images_before_new_reference_are_not_used(self):
        self.node.reference_stamp=self.at
        image,_=self.messages();image.header=self.header(self.at-1);self.node._image(image)
        self.assertEqual(self.calls,0)
    def test_pair_cache_is_bounded(self):
        for _ in range(12):
            image,_=self.messages();self.node._image(image);self.at+=1
        self.assertEqual(len(self.node.images),8)


if __name__=='__main__':unittest.main()
