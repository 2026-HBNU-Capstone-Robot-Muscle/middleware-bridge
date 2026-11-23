"""Consume stamped images/OBBs; publish candidate or registered poses, never commands."""
from collections import OrderedDict
from copy import deepcopy
import json,time
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy,QoSProfile,ReliabilityPolicy,qos_profile_sensor_data
from cv_bridge import CvBridge,CvBridgeError
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import Image
from std_msgs.msg import String
from system_interfaces.msg import CubeColorReference,FaceDetectionArray
from .metric_cube_pose import PoseRejected,quaternion_xyzw
from .placement_profile import load_pipeline


def stamp_ns(header):
    return int(header.stamp.sec)*1_000_000_000+int(header.stamp.nanosec)


class MarkerlessCubePoseNode(Node):
    def __init__(self):
        super().__init__('markerless_cube_pose')
        for key,value in (('camera_calibration_path',''),('registration_path',''),('setup_id',''),
                          ('image_topic','/camera/image_raw'),('detections_topic','/cube/face_detections'),
                          ('max_input_age_ms',150)):
            self.declare_parameter(key,value)
        self.pipeline=load_pipeline(str(self.get_parameter('camera_calibration_path').value),
                                    str(self.get_parameter('registration_path').value),
                                    active_setup_id=str(self.get_parameter('setup_id').value))
        self.max_age_ms=float(self.get_parameter('max_input_age_ms').value)
        if not np.isfinite(self.max_age_ms) or not 0<self.max_age_ms<=1000:
            raise PoseRejected('max_input_age_ms must be in (0,1000]')
        self.bridge=CvBridge();self.images=OrderedDict();self.detections=OrderedDict();self.last_stamp=0;self.reference_stamp=0
        self.candidate_pub=self.create_publisher(PoseStamped,'/cube/pose_camera_candidate',10)
        self.relative_pub=self.create_publisher(PoseStamped,'/cube/pose_wrist_candidate',10)
        self.cube_pub=self.create_publisher(PoseStamped,'/cube/pose',10)
        self.palm_pub=self.create_publisher(PoseStamped,'/leap_hand/palm_pose',10)
        self.status_pub=self.create_publisher(String,'/cube/pose_status',10)
        self.image_sub=self.create_subscription(Image,str(self.get_parameter('image_topic').value),self._image,qos_profile_sensor_data)
        self.detection_sub=self.create_subscription(FaceDetectionArray,str(self.get_parameter('detections_topic').value),self._detection,qos_profile_sensor_data)
        qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.reference_sub=self.create_subscription(CubeColorReference,'/cube/color_reference',self._reference,qos)
        self.get_logger().info('Markerless pose input ready. Policy pose publication requires explicit verified registrations; no motor output.')

    def _status(self,valid,**details):
        message=String();message.data=json.dumps(dict(candidate_valid=valid,**details),ensure_ascii=False)
        self.status_pub.publish(message)

    def _reference(self,message):
        self.pipeline.reference=None
        self.images.clear();self.detections.clear();self.last_stamp=0
        self.reference_stamp=stamp_ns(message.header)
        try:
            if message.header.frame_id!=self.pipeline.registration.camera_frame:
                raise PoseRejected('Color reference camera frame mismatch')
            self.pipeline.set_reference(np.asarray(message.center_bgr).reshape(6,3),message.scan_id)
            self._status(False,reason='Color reference accepted; waiting for synchronized images',scan_id=message.scan_id)
        except (ValueError,TypeError) as exc:self._status(False,reason=str(exc),policy_pose_ready=False)

    def _image(self,message):self._cache(self.images,message)
    def _detection(self,message):self._cache(self.detections,message)

    def _cache(self,cache,message):
        try:
            stamp=stamp_ns(message.header)
            if stamp<=0 or stamp<=self.last_stamp:raise PoseRejected('Missing, duplicate or out-of-order image timestamp')
            if stamp<self.reference_stamp:raise PoseRejected('Image predates the active six-face scan')
            if message.header.frame_id!=self.pipeline.registration.camera_frame:raise PoseRejected('Image/detection camera frame mismatch')
            age=(self.get_clock().now().nanoseconds-stamp)/1e6
            if not 0<=age<=self.max_age_ms:raise PoseRejected('Image/detection is future-dated or stale')
            cache[stamp]=(message,time.monotonic());cache.move_to_end(stamp)
            while len(cache)>8:cache.popitem(last=False)
            if stamp in self.images and stamp in self.detections:self._consume(stamp)
        except (ValueError,CvBridgeError,RuntimeError) as exc:
            self._status(False,reason=str(exc),policy_pose_ready=False)

    @staticmethod
    def _pose(header,frame,rotation,translation):
        message=PoseStamped();message.header=deepcopy(header);message.header.frame_id=frame
        message.pose.position.x,message.pose.position.y,message.pose.position.z=map(float,translation)
        q=quaternion_xyzw(rotation)
        message.pose.orientation.x,message.pose.orientation.y,message.pose.orientation.z,message.pose.orientation.w=map(float,q)
        return message

    def _consume(self,stamp):
        image,received_image=self.images.pop(stamp);detection,received_detection=self.detections.pop(stamp)
        # A failed frame is consumed once; duplicate deliveries cannot turn it
        # into a newly acquired pose or advance policy histories.
        self.last_stamp=stamp
        frame=self.bridge.imgmsg_to_cv2(image,desired_encoding='bgr8')
        observations=[([[p.x,p.y] for p in d.corners_px],float(d.confidence))
                      for d in detection.detections if d.class_name=='side']
        result=self.pipeline.process(frame,observations)
        age=(self.get_clock().now().nanoseconds-stamp)/1e6
        wall_ms=(time.monotonic()-min(received_image,received_detection))*1000
        if not 0<=age<=self.max_age_ms or wall_ms>self.max_age_ms:
            raise PoseRejected('Pose computation or input wait exceeded the freshness budget')
        reg=self.pipeline.registration
        self.candidate_pub.publish(self._pose(image.header,reg.camera_frame,result['rotation'],result['translation']))
        if 'cube_in_wrist_candidate' in result:
            relative=result['cube_in_wrist_candidate']
            self.relative_pub.publish(self._pose(image.header,f'leap_wrist_marker_{reg.wrist_id}',relative[:3,:3],relative[:3,3]))
        if result['policy_pose_ready']:
            cube=result['cube_world'];palm=result['palm_world']
            # Same exposure timestamp and world coordinates for both inputs.
            self.cube_pub.publish(self._pose(image.header,reg.world_frame,cube[:3,:3],cube[:3,3]))
            self.palm_pub.publish(self._pose(image.header,reg.world_frame,palm[:3,:3],palm[:3,3]))
        self._status(True,policy_pose_ready=result['policy_pose_ready'],scan_id=result['scan_id'],
            visible_faces=result['visible_faces'],reprojection_rms_px=result['rms_px'],
            source_stamp_ns=stamp,source_age_ms=age,processing_and_wait_ms=wall_ms,
            camera_binding_verified=result['camera_binding_verified'],registration_verified=result['registration_verified'],
            setup_id=result.get('setup_id',''),temporary_setup=result.get('temporary_setup',True),
            reason=result.get('policy_rejection','registered pose'),feature_rejections=result['feature_rejections'])


def main(args=None):
    rclpy.init(args=args);node=None
    try:
        node=MarkerlessCubePoseNode();rclpy.spin(node)
    except KeyboardInterrupt:pass
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('markerless_cube_pose:',exc);return 2
    finally:
        if node is not None:node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
    return 0
