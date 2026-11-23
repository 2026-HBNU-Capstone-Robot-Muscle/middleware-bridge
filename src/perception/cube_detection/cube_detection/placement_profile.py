"""Placement-scoped profiles; temporary work never enables policy pose output."""
import hashlib,json
from pathlib import Path
from .metric_cube_pose import CameraModel,PoseRejected
from .markerless_pipeline import MarkerlessPipeline,Registration


def load_pipeline(calibration_path,registration_path='',*,active_setup_id=''):
    path=Path(calibration_path).expanduser()
    if not path.is_file():raise PoseRejected('Set camera_calibration_path to an existing NPZ')
    camera=CameraModel.from_npz(path);registration=Registration(diagnostic_only=True);side=.055
    placement={};doc={}
    if registration_path:
        doc=json.loads(Path(registration_path).expanduser().read_text(encoding='utf-8'))
        registration=Registration(**doc['registration']);side=float(doc.get('cube_side_m',.055))
        placement=doc.get('placement',{})
        if not isinstance(placement,dict):raise PoseRejected('placement must be an object')
        temporary=placement.get('temporary',True)
        setup_id=placement.get('setup_id','')
        if type(temporary) is not bool or not isinstance(setup_id,str):raise PoseRejected('Invalid placement identity')
        confirmed=bool(setup_id and active_setup_id==setup_id)
        if temporary or not confirmed:registration.diagnostic_only=True
        if registration.camera_binding_verified:
            actual=hashlib.sha256(path.read_bytes()).hexdigest()
            if actual!=doc.get('camera_calibration_sha256') or not str(doc.get('camera_binding_record','')).strip():
                raise PoseRejected('Verified camera binding requires matching calibration SHA256 and a physical assignment record')
        scan_id=placement.get('registered_color_scan_id','')
        if not isinstance(scan_id,str):raise PoseRejected('registered_color_scan_id must be a string')
        if not scan_id:registration.diagnostic_only=True
    pipeline=MarkerlessPipeline(camera,registration,cube_side_m=side)
    pipeline.setup_id=placement.get('setup_id','')
    pipeline.temporary_setup=placement.get('temporary',True)
    pipeline.required_scan_id=placement.get('registered_color_scan_id') or None
    return pipeline


def temporary_profile(calibration_path,setup_id,*,previous=None,camera_settings_changed=False,wrist_remounted=False):
    """Create a new document; never alter the source profile or grant verification."""
    if not isinstance(setup_id,str) or not setup_id.strip():raise PoseRejected('A new setup_id is required')
    path=Path(calibration_path);CameraModel.from_npz(path)
    source={} if previous is None else json.loads(Path(previous).read_text(encoding='utf-8'))
    if source.get('placement',{}).get('setup_id')==setup_id:
        raise PoseRejected('Relocation needs a different setup_id')
    registration=dict(source.get('registration',{}))
    defaults=Registration()
    for key in vars(defaults):registration.setdefault(key,getattr(defaults,key))
    registration.update(diagnostic_only=True,world_registration_verified=False,world_from_camera=None,
                        cube_frame_registration_verified=False)
    if camera_settings_changed:
        registration['camera_binding_verified']=False
    if wrist_remounted:
        registration['wrist_sensor_registration_verified']=False
        registration['wrist_from_palm_sensor']=None
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if source.get('camera_calibration_sha256')!=digest:
        registration['camera_binding_verified']=False
    # Validate this document's matrices/types before writing it.
    Registration(**registration)
    return dict(cube_side_m=source.get('cube_side_m',.055),camera_calibration_sha256=digest,
        camera_binding_record='' if camera_settings_changed else source.get('camera_binding_record',''),
        placement=dict(setup_id=setup_id,temporary=True,registered_color_scan_id='',
            prior_profile=str(previous) if previous is not None else '',
            camera_settings_changed=bool(camera_settings_changed),wrist_remounted=bool(wrist_remounted)),
        registration=registration)
