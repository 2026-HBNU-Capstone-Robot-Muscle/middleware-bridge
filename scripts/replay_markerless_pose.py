"""Saved image diagnostic only: refine supplied ROIs, optionally solve pose."""
import argparse,hashlib,json,sys
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/perception/cube_detection'))
from cube_detection.metric_cube_pose import CameraModel,PoseRejected
from cube_detection.markerless_features import refine_face_quad
from cube_detection.markerless_pipeline import MarkerlessPipeline,Registration


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True);p.add_argument('--calibration',required=True)
    p.add_argument('--detections',required=True,help='Saved OBB search ROIs, not trusted physical corners')
    p.add_argument('--color-reference',help='JSON {scan_id,center_bgr:[18 values in URFDLB order]} from a valid scan')
    p.add_argument('--output',required=True);a=p.parse_args()
    image_path=Path(a.image);calibration_path=Path(a.calibration);source=Path(a.detections)
    frame=cv2.imdecode(np.frombuffer(image_path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    camera=CameraModel.from_npz(calibration_path);camera.check_image(frame)
    document=json.loads(source.read_text(encoding='utf-8'))
    expected=document.get('image_sha256')
    digest=hashlib.sha256(image_path.read_bytes()).hexdigest()
    if expected and digest!=expected:raise PoseRejected('Saved detections belong to a different image')
    detections=[(d['corners_px'],d.get('confidence',1.)) for d in document['detections']]
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    overlay=frame.copy();features=[]
    for i,(corners,confidence) in enumerate(detections):
        try:
            refined=refine_face_quad(frame,corners)
            cv2.polylines(overlay,[np.rint(refined).astype(int)],True,(0,230,0),2)
            features.append(dict(index=i,accepted=True,refined_corners_px=refined.tolist()))
        except PoseRejected as exc:
            features.append(dict(index=i,accepted=False,reason=str(exc)))
            cv2.polylines(overlay,[np.rint(corners).astype(int)],True,(0,160,240),1)
    report=dict(image=str(image_path),image_sha256=digest,calibration=str(calibration_path),
        calibration_sha256=hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
        resolution=[camera.width,camera.height],roi_source=document.get('source','provided search ROIs'),
        features=features,camera_binding_verified=False,physical_pose_verified=False,
        policy_pose_ready=False,devices_opened=False,pose_estimated=False)
    if a.color_reference:
        reference=json.loads(Path(a.color_reference).read_text(encoding='utf-8'))
        pipeline=MarkerlessPipeline(camera,Registration())
        pipeline.set_reference(np.asarray(reference['center_bgr']).reshape(6,3),reference['scan_id'])
        try:
            result=pipeline.process(frame,detections)
            report.update(pose_estimated=True,camera_pose_candidate=result)
        except PoseRejected as exc:report['pose_rejection']=str(exc)
    else:report['pose_rejection']='No accepted six-face color reference; image features only'
    ok,encoded=cv2.imencode('.jpg',overlay)
    if not ok:raise PoseRejected('Could not encode diagnostic overlay')
    (out/'overlay.jpg').write_bytes(encoded.tobytes())
    text=json.dumps(report,indent=2,ensure_ascii=False,default=lambda x:x.tolist() if isinstance(x,np.ndarray) else x.item())+'\n'
    (out/'review.json').write_text(text,encoding='utf-8')
    print(json.dumps(dict(features_accepted=sum(f['accepted'] for f in features),
        pose_estimated=report['pose_estimated'],physical_pose_verified=False,report=str(out/'review.json'))))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError) as exc:print('REJECTED:',exc);raise SystemExit(2)
