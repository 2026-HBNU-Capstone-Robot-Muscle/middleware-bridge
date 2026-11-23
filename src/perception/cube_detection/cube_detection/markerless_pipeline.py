"""Image-to-pose processing with explicit camera and policy-frame registration."""
from dataclasses import dataclass
import cv2
import numpy as np
from .metric_cube_pose import (
    CameraModel,PoseRejected,checked_transform,estimate_cube_pose,pose_matrix)
from .markerless_features import ColorReference,extract_labeled_faces


@dataclass
class Registration:
    camera_binding_verified: bool = False
    world_registration_verified: bool = False
    wrist_sensor_registration_verified: bool = False
    cube_frame_registration_verified: bool = False
    world_frame: str = ''
    camera_frame: str = 'camera_optical_frame'
    world_from_camera: object = None
    wrist_from_palm_sensor: object = None
    color_cube_from_policy_cube: object = None
    wrist_id: int = 41
    wrist_size_m: float = .027
    diagnostic_only: bool = False

    def __post_init__(self):
        for name in ('camera_binding_verified','world_registration_verified',
                     'wrist_sensor_registration_verified','cube_frame_registration_verified','diagnostic_only'):
            if type(getattr(self,name)) is not bool:raise PoseRejected(name+': expected boolean')
        if not self.camera_frame or not 0<=self.wrist_id<50 or not .005<=self.wrist_size_m<=.1:
            raise PoseRejected('Invalid camera frame or wrist marker configuration')
        for name in ('world_from_camera','wrist_from_palm_sensor','color_cube_from_policy_cube'):
            value=getattr(self,name)
            if value is not None:setattr(self,name,checked_transform(value,name))
        if self.color_cube_from_policy_cube is not None and np.linalg.norm(self.color_cube_from_policy_cube[:3,3])>1e-9:
            raise PoseRejected('Cube coordinate frames must share the cube center')

    @property
    def ready(self):
        return bool(not self.diagnostic_only and self.camera_binding_verified and self.world_registration_verified
            and self.wrist_sensor_registration_verified and self.cube_frame_registration_verified
            and self.world_frame and self.world_from_camera is not None
            and self.wrist_from_palm_sensor is not None and self.color_cube_from_policy_cube is not None)


def wrist_pose(frame,camera,registration):
    if not hasattr(cv2,'aruco'):raise PoseRejected('OpenCV ArUco module is required for the wrist marker')
    dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    corners,ids,_=cv2.aruco.ArucoDetector(dictionary).detectMarkers(frame)
    matches=[] if ids is None else [i for i,x in enumerate(ids.ravel()) if int(x)==registration.wrist_id]
    if len(matches)!=1:raise PoseRejected('Need one visible wrist marker ID'+str(registration.wrist_id))
    image=np.asarray(corners[matches[0]],dtype=float).reshape(4,2)
    h=registration.wrist_size_m/2
    points=np.asarray([[-h,h,0],[h,h,0],[h,-h,0],[-h,-h,0]],dtype=float)
    result=cv2.solvePnPGeneric(points,image,camera.K,camera.distortion,flags=cv2.SOLVEPNP_IPPE_SQUARE)
    fits=[]
    for rvec,tvec in zip(result[1],result[2]):
        r=cv2.Rodrigues(rvec)[0];t=tvec.reshape(3)
        if not np.isfinite(np.r_[r.ravel(),t]).all() or not .05<t[2]<2.:continue
        projected=cv2.projectPoints(points,rvec,tvec,camera.K,camera.distortion)[0].reshape(-1,2)
        rms=float(np.sqrt(np.mean(np.sum((projected-image)**2,axis=1))))
        if rms<=2:fits.append((rms,pose_matrix(r,t)))
    if not fits:raise PoseRejected('Wrist marker pose has excessive reprojection error')
    fits.sort(key=lambda x:x[0])
    if len(fits)>1:
        delta=fits[0][1][:3,:3]@fits[1][1][:3,:3].T
        angle=np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2,-1,1)))
        if angle>3 and fits[1][0]-fits[0][0]<.5:raise PoseRejected('Wrist marker orientation is ambiguous')
    return fits[0][1]


class MarkerlessPipeline:
    def __init__(self,camera,registration=None,*,cube_side_m=.055):
        if not isinstance(camera,CameraModel):raise PoseRejected('CameraModel required')
        if not np.isfinite(cube_side_m) or not .01<=cube_side_m<=.2:raise PoseRejected('Invalid cube dimensions')
        self.camera=camera;self.registration=registration or Registration()
        self.cube_side_m=cube_side_m;self.reference=None
        self.setup_id='';self.temporary_setup=False;self.required_scan_id=None

    def set_reference(self,centers_bgr,scan_id):
        reference=ColorReference(centers_bgr,scan_id)
        if self.required_scan_id is not None and scan_id!=self.required_scan_id:
            # A new six-face scan can redefine which physical colors are
            # named URFDLB. Never reuse a verified policy-axis registration.
            self.registration.cube_frame_registration_verified=False
        self.reference=reference

    def process(self,frame,detections):
        self.camera.check_image(frame)
        if self.reference is None:raise PoseRejected('Waiting for a valid six-face color reference')
        faces,rejected=extract_labeled_faces(frame,detections,self.reference)
        result=estimate_cube_pose(faces,self.camera,side_m=self.cube_side_m)
        result.update(scan_id=self.reference.scan_id,feature_rejections=rejected,
            policy_pose_ready=False,registration_verified=self.registration.ready,
            camera_binding_verified=self.registration.camera_binding_verified,
            setup_id=self.setup_id,temporary_setup=self.temporary_setup)
        cam_cube=pose_matrix(result['rotation'],result['translation'])
        try:
            cam_wrist=wrist_pose(frame,self.camera,self.registration)
            # This relation does not require a fixed camera-to-world pose.
            # It remains a candidate: marker size/intrinsics may be unverified.
            result['cube_in_wrist_candidate']=np.linalg.inv(cam_wrist)@cam_cube
        except PoseRejected as exc:
            result['wrist_rejection']=str(exc)
            result['policy_rejection']=str(exc)
            return result
        if self.registration.ready:
            result['cube_world']=self.registration.world_from_camera@cam_cube@self.registration.color_cube_from_policy_cube
            result['palm_world']=self.registration.world_from_camera@cam_wrist@self.registration.wrist_from_palm_sensor
            result['policy_pose_ready']=True
        else:result['policy_rejection']='Camera binding and camera/world, wrist/sensor, cube/policy frame registration are not verified'
        return result
