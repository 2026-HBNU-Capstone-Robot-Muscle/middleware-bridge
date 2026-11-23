"""Placement changes invalidate only the registrations affected by the move."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/perception/cube_detection'))
from cube_detection.placement_profile import load_pipeline,temporary_profile
from cube_detection.markerless_pipeline import Registration,MarkerlessPipeline
from cube_detection.metric_cube_pose import CameraModel,PoseRejected,face_geometry,FACE_ORDER,pose_matrix


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.calib=self.root/'intrinsics.npz'
        np.savez(self.calib,K=np.array([[950.,0,640],[0,950.,360],[0,0,1]]),dist=np.zeros(5),width=1280,height=720)
        self.profile=self.root/'old.json';reg=Registration(True,True,True,True,'world','camera_optical_frame',np.eye(4),np.eye(4),np.eye(4))
        data=dict(camera_calibration_sha256=hashlib.sha256(self.calib.read_bytes()).hexdigest(),
            camera_binding_record='synthetic test camera assignment',cube_side_m=.055,
            placement=dict(setup_id='old',temporary=False,registered_color_scan_id='scan'),
            registration={k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in vars(reg).items()})
        self.profile.write_text(json.dumps(data))
    def test_temporary_profile_never_enables_policy_even_with_all_verified_flags(self):
        data=json.loads(self.profile.read_text());data['placement']['temporary']=True
        self.profile.write_text(json.dumps(data))
        p=load_pipeline(self.calib,self.profile,active_setup_id='old')
        self.assertFalse(p.registration.ready);self.assertTrue(p.temporary_setup)
    def test_permanent_verified_profile_requires_matching_active_setup_id(self):
        self.assertFalse(load_pipeline(self.calib,self.profile).registration.ready)
        self.assertFalse(load_pipeline(self.calib,self.profile,active_setup_id='different').registration.ready)
        self.assertTrue(load_pipeline(self.calib,self.profile,active_setup_id='old').registration.ready)
    def test_legacy_profile_is_candidate_only(self):
        data=json.loads(self.profile.read_text());data.pop('placement');self.profile.write_text(json.dumps(data))
        self.assertFalse(load_pipeline(self.calib,self.profile).registration.ready)
    def test_relocation_keeps_intrinsics_and_rigid_wrist_registration_but_invalidates_world(self):
        old=self.profile.read_bytes();new=temporary_profile(self.calib,'new',previous=self.profile)
        self.assertEqual(self.profile.read_bytes(),old)
        self.assertTrue(new['registration']['camera_binding_verified'])
        self.assertTrue(new['registration']['wrist_sensor_registration_verified'])
        self.assertFalse(new['registration']['world_registration_verified'])
        self.assertIsNone(new['registration']['world_from_camera'])
        self.assertFalse(new['registration']['cube_frame_registration_verified'])
        self.assertEqual(new['placement']['registered_color_scan_id'],'')
    def test_camera_settings_change_requires_intrinsic_binding_recheck(self):
        new=temporary_profile(self.calib,'new',previous=self.profile,camera_settings_changed=True)
        self.assertFalse(new['registration']['camera_binding_verified'])
        self.assertEqual(new['camera_binding_record'],'')
    def test_remounted_marker_invalidates_sensor_transform(self):
        new=temporary_profile(self.calib,'new',previous=self.profile,wrist_remounted=True)
        self.assertFalse(new['registration']['wrist_sensor_registration_verified'])
        self.assertIsNone(new['registration']['wrist_from_palm_sensor'])
    def test_relocation_does_not_reuse_old_setup_id(self):
        with self.assertRaises(PoseRejected):temporary_profile(self.calib,'old',previous=self.profile)
    def test_new_color_scan_invalidates_the_policy_cube_axes(self):
        p=load_pipeline(self.calib,self.profile,active_setup_id='old')
        centers=[[20,20,230],[20,150,240],[220,40,20],[20,230,230],[40,170,20],[235,235,235]]
        self.assertTrue(p.registration.ready);p.set_reference(centers,'new-scan')
        self.assertFalse(p.registration.ready)
    def test_wrong_calibration_hash_or_missing_assignment_record_is_rejected(self):
        for field,value in (('camera_calibration_sha256','bad'),('camera_binding_record','')):
            data=json.loads(self.profile.read_text());data[field]=value
            dest=self.root/(field+'.json');dest.write_text(json.dumps(data))
            with self.assertRaises(PoseRejected):load_pipeline(self.calib,dest,active_setup_id='old')


class RelativePoseTests(unittest.TestCase):
    def test_wrist_relative_cube_pose_is_invariant_under_rigid_camera_motion(self):
        camera=CameraModel(np.array([[950.,0,640],[0,950.,360],[0,0,1]]),np.zeros(5),1280,720)
        rc=cv2.Rodrigues(np.array([2.6,.35,-.25]))[0];tc=np.array([.015,-.01,.38])
        relative=pose_matrix(cv2.Rodrigues(np.array([0.,.1,.2]))[0],[.03,.02,.04])
        cube=pose_matrix(rc,tc);wrist=cube@np.linalg.inv(relative)
        motion=pose_matrix(cv2.Rodrigues(np.array([.04,-.06,.1]))[0],[.02,-.01,.03])
        outputs=[]
        for move in (np.eye(4),motion):
            target=move@cube;observations={}
            r=target[:3,:3];t=target[:3,3];rvec=cv2.Rodrigues(r)[0]
            for face in FACE_ORDER:
                points,normal=face_geometry(face)
                if (r@normal)@(r@(normal*.055/2)+t)<-.01:
                    observations[face]=cv2.projectPoints(points,rvec,t,camera.K,camera.distortion)[0].reshape(4,2)
            pipeline=MarkerlessPipeline(camera,Registration(diagnostic_only=True))
            pipeline.reference=SimpleNamespace(scan_id='synthetic')
            with patch('cube_detection.markerless_pipeline.extract_labeled_faces',return_value=(observations,[])), \
                 patch('cube_detection.markerless_pipeline.wrist_pose',return_value=move@wrist):
                result=pipeline.process(np.zeros((720,1280,3),np.uint8),[])
            self.assertFalse(result['policy_pose_ready']);self.assertNotIn('cube_world',result)
            outputs.append(result['cube_in_wrist_candidate'])
        np.testing.assert_allclose(outputs[0],relative,atol=1e-6)
        np.testing.assert_allclose(outputs[1],relative,atol=1e-6)


if __name__=='__main__':unittest.main()
