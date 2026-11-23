"""Successful scan emits URFDLB colors; failed/new scan clears the old reference."""
from pathlib import Path
from types import ModuleType,SimpleNamespace as NS
from unittest.mock import patch
import importlib,sys,unittest
import numpy as np
import cv2  # Load the native module before patch.dict restores sys.modules.

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/perception/cube_detection'))


def load_capture():
    names=('rclpy','rclpy.executors','rclpy.node','rclpy.qos','cv_bridge',
           'sensor_msgs','sensor_msgs.msg','system_interfaces','system_interfaces.msg','system_interfaces.srv')
    modules={name:ModuleType(name) for name in names}
    class Reference:
        def __init__(self):self.header=NS(stamp=None,frame_id='');self.center_bgr=[0]*18
    class State:pass
    modules['rclpy.node'].Node=object;modules['rclpy.executors'].SingleThreadedExecutor=object
    modules['cv_bridge'].CvBridge=object;modules['sensor_msgs.msg'].Image=object
    qos=modules['rclpy.qos'];qos.DurabilityPolicy=NS(TRANSIENT_LOCAL=1);qos.ReliabilityPolicy=NS(RELIABLE=1);qos.QoSProfile=object;qos.qos_profile_sensor_data=object()
    msg=modules['system_interfaces.msg'];msg.CubeColorReference=Reference;msg.CubeState=State;msg.CubeSolution=object;msg.FaceDetectionArray=object
    modules['system_interfaces.srv'].SolveCube=object
    with patch.dict(sys.modules,modules):return importlib.import_module('cube_detection.camera_capture_node')


MODULE=load_capture()


class Tests(unittest.TestCase):
    def setUp(self):
        self.reference=[];self.states=[];n=self.node=object.__new__(MODULE.CubeCameraCaptureNode)
        self.colors={face:[i*20+1,i*20+2,i*20+3] for i,face in enumerate('FRBLUD')}
        n._captures={face:np.tile(color,(9,1)) for face,color in self.colors.items()}
        n._scan_id='scan';n.frame_id='camera_optical_frame';n._max_color_reassignment_delta=20;n._completed=False
        n._pending_captures={};n._capture_retries=[]
        n.color_reference_publisher=NS(publish=self.reference.append);n.state_publisher=NS(publish=self.states.append)
        n.get_clock=lambda:NS(now=lambda:NS(to_msg=lambda:NS(sec=10,nanosec=0)))
        n.get_logger=lambda:NS(info=lambda *_:None,error=lambda *_:None,warning=lambda *_:None)
        n.solve_client=NS(wait_for_service=lambda **_:False)
    def test_valid_scan_emits_center_colors_in_URFDLB_order(self):
        header=NS(frame_id='camera_optical_frame',stamp=NS(sec=10,nanosec=0))
        with patch.object(MODULE,'classify_cube',return_value=('U'*54,[],[])):
            self.node._finalize_cube_state(header)
        self.assertEqual(self.reference[-1].center_bgr,[v for face in 'URFDLB' for v in self.colors[face]])
        self.assertEqual(self.reference[-1].scan_id,'scan');self.assertIs(self.reference[-1].header,header)
    def test_invalid_scan_cannot_retain_a_previous_palette(self):
        with patch.object(MODULE,'classify_cube',return_value=('', ['bad state'], [])):
            self.node._finalize_cube_state(NS())
        self.assertFalse(self.states[-1].valid);self.assertEqual(self.reference[-1].center_bgr,[0]*18)
    def test_rescan_invalidates_before_new_faces_are_collected(self):
        self.node._pending_captures={};self.node._capture_retries=[]
        self.node._start_new_scan()
        self.assertEqual(self.node._captures,{})
        self.assertNotEqual(self.reference[-1].scan_id,'scan')
        self.assertEqual(self.reference[-1].center_bgr,[0]*18)


if __name__=='__main__':unittest.main()
