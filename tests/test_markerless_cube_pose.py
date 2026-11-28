"""Project known3D cubes to test markerless geometry and rejection, no devices."""
from pathlib import Path
import sys,unittest
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/perception/cube_detection'))
from cube_detection.metric_cube_pose import (
    CameraModel,PoseRejected,FACE_ORDER,face_geometry,ordered_quad,estimate_cube_pose,
    checked_transform,quaternion_xyzw)
from cube_detection.markerless_features import ColorReference,refine_face_quad,extract_labeled_faces
from cube_detection.markerless_pipeline import MarkerlessPipeline,Registration

COLORS=np.array([[30,30,230],[30,170,240],[230,60,30],
                 [30,230,230],[50,180,30],[235,235,235]],np.uint8)


def scene(rotation=None,noise=0.):
    camera=CameraModel(np.array([[950.,0,640],[0,950.,360],[0,0,1]]),np.zeros(5),1280,720)
    rvec=np.array([2.6,.35,-.25]) if rotation is None else np.asarray(rotation,dtype=float)
    r=cv2.Rodrigues(rvec)[0];t=np.array([.015,-.01,.38]);faces={}
    for label in FACE_ORDER:
        p,n=face_geometry(label)
        if (r@n)@(r@(n*.055/2)+t)<-.01:
            projected=cv2.projectPoints(p,rvec,t,camera.K,camera.distortion)[0].reshape(4,2)
            if noise:projected+=np.random.default_rng(ord(label)).normal(0,noise,(4,2))
            faces[label]=projected
    return camera,r,t,faces


def image_scene():
    camera,r,t,faces=scene();frame=np.full((720,1280,3),25,np.uint8);detections=[]
    for label,q in faces.items():
        cv2.fillConvexPoly(frame,np.rint(q).astype(int),(250,250,250))
        h=cv2.getPerspectiveTransform(np.array([[0,0],[3,0],[3,3],[0,3]],np.float32),q.astype(np.float32))
        for y in range(3):
            for x in range(3):
                tile=np.array([[x+.12,y+.12],[x+.88,y+.12],[x+.88,y+.88],[x+.12,y+.88]],float)
                polygon=cv2.perspectiveTransform(tile.reshape(-1,1,2),h).reshape(4,2)
                cv2.fillConvexPoly(frame,np.rint(polygon).astype(int),COLORS[FACE_ORDER.index(label)].tolist())
        rect=cv2.minAreaRect(q.astype(np.float32));detections.append((cv2.boxPoints(rect),.95))
    return camera,r,t,faces,frame,detections


class GeometryTests(unittest.TestCase):
    def test_two_and_three_face_recovery_ignores_corner_start_order(self):
        camera,r,t,faces=scene()
        self.assertEqual(len(faces),3)
        for count in (2,3):
            observed={k:np.roll(q,i+1,axis=0)[::-1] for i,(k,q) in enumerate(list(faces.items())[:count])}
            actual=estimate_cube_pose(observed,camera)
            np.testing.assert_allclose(actual['rotation'],r,atol=1e-6)
            np.testing.assert_allclose(actual['translation'],t,atol=1e-8)
    def test_small_pixel_noise_keeps_metric_pose_close(self):
        camera,r,t,faces=scene(noise=.15);actual=estimate_cube_pose(faces,camera)
        self.assertLess(np.linalg.norm(actual['translation']-t),.002)
        self.assertLess(actual['rms_px'],1.)
    def test_varied_cube_directions_preserve_the_color_body_frame(self):
        rng=np.random.default_rng(55);count=0
        for _ in range(16):
            axis=rng.normal(size=3);axis/=np.linalg.norm(axis)
            camera,r,t,faces=scene(axis*rng.uniform(.3,3.))
            faces={k:q for k,q in faces.items() if cv2.contourArea(q.astype(np.float32))>200}
            if len(faces)<2:continue
            actual=estimate_cube_pose(faces,camera)
            np.testing.assert_allclose(actual['rotation'],r,atol=1e-6)
            np.testing.assert_allclose(actual['translation'],t,atol=1e-8);count+=1
        self.assertGreaterEqual(count,10)
    def test_single_face_is_not_an_absolute_cube_orientation(self):
        camera,_,_,faces=scene()
        with self.assertRaisesRegex(PoseRejected,'two or three'):estimate_cube_pose(dict(list(faces.items())[:1]),camera)
    def test_inconsistent_face_pixels_rejected(self):
        camera,_,_,faces=scene();key=list(faces)[-1];faces[key]=faces[key]+[70,0]
        with self.assertRaises(PoseRejected):estimate_cube_pose(faces,camera)
    def test_opposite_faces_or_image_clipping_rejected(self):
        camera,_,_,faces=scene();q=next(iter(faces.values()))
        with self.assertRaises(PoseRejected):estimate_cube_pose({'F':q,'B':q},camera)
        faces[next(iter(faces))][0,0]=-1
        with self.assertRaises(PoseRejected):estimate_cube_pose(faces,camera)
    def test_calibration_resolution_cannot_be_silently_resized(self):
        camera,*_=scene()
        with self.assertRaises(PoseRejected):camera.check_image(np.zeros((480,640,3),np.uint8))
        with self.assertRaises(PoseRejected):CameraModel(np.eye(3)*0,np.zeros(5),1280,720)
    def test_quad_and_size_validation(self):
        with self.assertRaises(PoseRejected):ordered_quad([[1,1],[2,2],[3,3],[4,4]])
        with self.assertRaises(PoseRejected):face_geometry('F',55.)
    def test_rigid_transform_and180degree_quaternion(self):
        r=cv2.Rodrigues(np.array([np.pi,0.,0.]))[0];q=quaternion_xyzw(r)
        self.assertAlmostEqual(np.linalg.norm(q),1.)
        np.testing.assert_allclose(np.abs(q),[1,0,0,0],atol=1e-12)
        bad=np.eye(4);bad[0,0]=2
        with self.assertRaises(PoseRejected):checked_transform(bad)


class FeatureTests(unittest.TestCase):
    def test_saved_shadow_front_recovers_a_full_face_grid(self):
        # Coarse ROIs and real camera pixels, not ground truth for metric pose.
        with np.load(ROOT/'tests/fixtures/markerless_shadow_cube_20261116.npz',allow_pickle=False) as fixture:
            q=fixture['front_obb']
            for frame in fixture['frames']:
                with self.subTest(frame_hash=int(frame.sum())):
                    refined=refine_face_quad(frame,q)
                    self.assertLess(np.linalg.norm(refined.mean(0)-q.mean(0)),15.)
                    ratio=cv2.contourArea(refined.astype(np.float32))/cv2.contourArea(q.astype(np.float32))
                    self.assertTrue(.55<ratio<1.45)
    def test_saved_clipped_highlights_do_not_invent_white_cells(self):
        with np.load(ROOT/'tests/fixtures/markerless_shadow_cube_20261116.npz',allow_pickle=False) as fixture:
            for frame in fixture['frames']:
                with self.assertRaises(PoseRejected):refine_face_quad(frame,fixture['upper_obb'])
    def test_duplicate_contours_cannot_turn_six_stickers_into_seven(self):
        frame=np.full((480,640,3),30,np.uint8)
        cv2.rectangle(frame,(200,120),(380,300),(200,210,220),-1)
        for y in range(2):
            for x in range(3):
                cv2.rectangle(frame,(209+60*x,129+60*y),(251+60*x,171+60*y),(50,2,0),-1)
        with self.assertRaises(PoseRejected):
            refine_face_quad(frame,[[200,120],[380,120],[380,300],[200,300]])
    def test_plain_OBB_without_visible_boundary_is_rejected(self):
        frame=np.full((720,1280,3),90,np.uint8)
        with self.assertRaises(PoseRejected):refine_face_quad(frame,[[200,200],[400,200],[400,400],[200,400]])
    def test_distinct_scan_centers_and_center_only_label(self):
        ref=ColorReference(COLORS,'scan');frame=np.full((720,1280,3),80,np.uint8)
        frame[200:400,200:400]=COLORS[2]
        self.assertEqual(ref.label(frame,[[200,200],[400,200],[400,400],[200,400]])[0],'F')
        with self.assertRaises(PoseRejected):ColorReference(np.zeros((6,3)),'scan')
    def test_synthetic_images_refine_true_faces_and_recover_pose(self):
        camera,r,t,faces,frame,detections=image_scene()
        refined,rejected=extract_labeled_faces(frame,detections,ColorReference(COLORS,'scan'))
        self.assertGreaterEqual(len(refined),2,rejected)
        actual=estimate_cube_pose(refined,camera,max_rms_px=3.)
        self.assertLess(np.linalg.norm(actual['translation']-t),.01)
    def test_invalid_registration_cannot_become_a_policy_pose(self):
        registration=Registration()
        self.assertFalse(registration.ready)
        with self.assertRaises(PoseRejected):Registration(camera_binding_verified='true')
        bad=np.eye(4);bad[0,3]=.01
        with self.assertRaises(PoseRejected):Registration(color_cube_from_policy_cube=bad)
    def test_no_color_scan_means_no_pose(self):
        camera,_,_,_,frame,detections=image_scene();pipeline=MarkerlessPipeline(camera)
        with self.assertRaises(PoseRejected):pipeline.process(frame,detections)
    def test_complete_image_pipeline_keeps_unverified_poses_out_of_policy(self):
        camera,r,t,_,frame,detections=image_scene();pipeline=MarkerlessPipeline(camera)
        pipeline.set_reference(COLORS,'scan');result=pipeline.process(frame,detections)
        self.assertFalse(result['policy_pose_ready']);self.assertNotIn('cube_world',result)
        self.assertLess(np.linalg.norm(result['translation']-t),.005)
    def test_verified_transform_chain_uses_policy_sensor_and_cube_axes(self):
        from unittest.mock import patch
        camera,r,t,_,frame,detections=image_scene()
        world=np.eye(4);world[:3,3]=[1,2,3]
        wrist_sensor=np.eye(4);wrist_sensor[:3,3]=[.01,0,0]
        cube_axes=np.eye(4);cube_axes[:3,:3]=cv2.Rodrigues(np.array([0.,0.,np.pi/2]))[0]
        registration=Registration(True,True,True,True,'world','camera_optical_frame',world,wrist_sensor,cube_axes)
        pipeline=MarkerlessPipeline(camera,registration);pipeline.set_reference(COLORS,'scan')
        with patch('cube_detection.markerless_pipeline.wrist_pose',return_value=np.eye(4)):
            result=pipeline.process(frame,detections)
        self.assertTrue(result['policy_pose_ready'])
        np.testing.assert_allclose(result['cube_world'][:3,3],world[:3,3]+result['translation'])
        np.testing.assert_allclose(result['palm_world'][:3,3],[1.01,2,3])
        np.testing.assert_allclose(result['cube_world'][:3,:3],result['rotation']@cube_axes[:3,:3])
    def test_missing_wrist_marker_does_not_publish_registered_poses(self):
        camera,_,_,_,frame,detections=image_scene()
        registration=Registration(True,True,True,True,'world','camera_optical_frame',np.eye(4),np.eye(4),np.eye(4))
        pipeline=MarkerlessPipeline(camera,registration);pipeline.set_reference(COLORS,'scan')
        result=pipeline.process(frame,detections)
        self.assertFalse(result['policy_pose_ready']);self.assertNotIn('palm_world',result)


if __name__=='__main__':unittest.main()
