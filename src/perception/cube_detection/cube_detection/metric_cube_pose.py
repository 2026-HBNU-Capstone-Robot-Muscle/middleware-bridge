"""Markerless cube geometry in OpenCV camera coordinates; no ROS or device I/O."""
from dataclasses import dataclass
from itertools import product
import cv2
import numpy as np

FACE_ORDER = 'URFDLB'
# right/up axes of each face; right cross up is its outward normal.
AXES = {
    'F': ((1,0,0),(0,1,0)), 'B': ((-1,0,0),(0,1,0)),
    'R': ((0,0,-1),(0,1,0)), 'L': ((0,0,1),(0,1,0)),
    'U': ((1,0,0),(0,0,-1)), 'D': ((1,0,0),(0,0,1)),
}


class PoseRejected(ValueError):
    pass


def finite(values, shape, label):
    a = np.asarray(values, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise PoseRejected(f'{label}: expected finite shape{shape}')
    return a


@dataclass(frozen=True)
class CameraModel:
    K: np.ndarray
    distortion: np.ndarray
    width: int
    height: int

    def __post_init__(self):
        k = finite(self.K, (3,3), 'camera matrix').copy()
        d = np.asarray(self.distortion, dtype=np.float64).reshape(-1).copy()
        if (d.size not in (4,5,8,12,14) or not np.isfinite(d).all()
                or self.width <= 0 or self.height <= 0 or k[0,0] <= 0 or k[1,1] <= 0
                or not np.allclose(k[2], [0,0,1]) or k[0,1] != 0 or k[1,0] != 0):
            raise PoseRejected('Invalid camera intrinsic calibration')
        object.__setattr__(self, 'K', k)
        object.__setattr__(self, 'distortion', d)

    @classmethod
    def from_npz(cls, path):
        with np.load(path, allow_pickle=False) as z:
            return cls(z['K'], z['dist'], int(z['width']), int(z['height']))

    def check_image(self, frame):
        if (frame is None or frame.ndim != 3 or frame.shape[2] != 3
                or frame.shape[:2] != (self.height,self.width) or frame.dtype != np.uint8):
            raise PoseRejected('Image size/type does not match camera calibration; no automatic scaling')


def ordered_quad(points, *, min_area=100., min_edge=5.):
    q = finite(points, (4,2), 'face corners')
    center = q.mean(axis=0)
    q = q[np.argsort(np.arctan2(q[:,1]-center[1], q[:,0]-center[0]))]
    contour = q.astype(np.float32)
    if (not cv2.isContourConvex(contour) or cv2.contourArea(contour) < min_area
            or np.min(np.linalg.norm(q-np.roll(q,1,axis=0),axis=1)) < min_edge):
        raise PoseRejected('Degenerate or tiny face polygon')
    return np.roll(q, -int(np.argmin(q.sum(axis=1))), axis=0)


def face_geometry(face, side_m=.055):
    if face not in AXES or not np.isfinite(side_m) or not .01 <= side_m <= .2:
        raise PoseRejected('Unknown face or invalid cube side length')
    u,v = map(lambda x:np.asarray(x,dtype=float), AXES[face])
    n = np.cross(u,v); h = side_m/2
    return h*np.asarray([n-u+v,n+u+v,n+u-v,n-u-v]), n


def estimate_cube_pose(faces, camera, *, side_m=.055, max_rms_px=2., ambiguity_px=.75):
    """Solve all cyclic corner assignments for2+ labeled, perspective-refined faces.

    A single square has unresolved90deg symmetry and is deliberately rejected.
    Labels are cube-body center colors from the accepted six-face scan.
    """
    if not 2 <= len(faces) <= 3:
        raise PoseRejected('Need two or three distinct visible labeled faces; single-face orientation is ambiguous')
    if not np.isfinite([max_rms_px,ambiguity_px]).all() or max_rms_px<=0 or ambiguity_px<=0:
        raise PoseRejected('Invalid pose quality thresholds')
    labels = list(faces)
    quads = [ordered_quad(faces[label]) for label in labels]
    geometry = [face_geometry(label,side_m) for label in labels]
    for i,(_,normal) in enumerate(geometry):
        if any(abs(normal@other[1])>.5 for other in geometry[:i]):
            raise PoseRejected('Duplicate or opposite faces cannot form a visible corner')
    for q in quads:
        if np.any(q<0) or np.any(q[:,0]>=camera.width) or np.any(q[:,1]>=camera.height):
            raise PoseRejected('Face polygon is clipped by the image')
    objects = np.concatenate([g[0] for g in geometry])
    candidates = []
    for shifts in product(range(4), repeat=len(labels)):
        pixels = np.concatenate([np.roll(q,k,axis=0) for q,k in zip(quads,shifts)])
        try:
            ok,rvec,tvec = cv2.solvePnP(objects,pixels,camera.K,camera.distortion,flags=cv2.SOLVEPNP_EPNP)
            if not ok:continue
            rvec,tvec = cv2.solvePnPRefineLM(objects,pixels,camera.K,camera.distortion,rvec,tvec)
            r = cv2.Rodrigues(rvec)[0];t=tvec.reshape(3)
            if not np.isfinite(np.r_[r.ravel(),t]).all() or not .08<=t[2]<=2.:continue
            vertices = np.asarray(list(product((-.5,.5),repeat=3)))*side_m
            if np.min((vertices@r.T+t)[:,2])<=0:continue
            if any(float((r@n)@(r@(n*side_m/2)+t))>=-1e-6 for _,n in geometry):continue
            projected = cv2.projectPoints(objects,rvec,tvec,camera.K,camera.distortion)[0].reshape(-1,2)
            errors = np.linalg.norm(projected-pixels,axis=1)
            rms = float(np.sqrt(np.mean(errors**2)))
            if rms>max_rms_px or errors.max()>2*max_rms_px:continue
            candidates.append(dict(rotation=r,translation=t,rms_px=rms,max_error_px=float(errors.max()),corner_shifts=list(shifts)))
        except cv2.error:
            continue
    if not candidates:raise PoseRejected('No positive-depth, front-facing multi-face pose passes reprojection')
    candidates.sort(key=lambda p:p['rms_px']);best=candidates[0]
    for other in candidates[1:]:
        delta=other['rotation']@best['rotation'].T
        angle=np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2,-1,1)))
        if (angle>2 or np.linalg.norm(other['translation']-best['translation'])>.002) and other['rms_px']-best['rms_px']<ambiguity_px:
            raise PoseRejected('Multiple distinct cube poses fit the visible faces')
    best.update(visible_faces=labels,cube_side_m=side_m,frame_convention='camera optical: X right, Y down, Z forward')
    return best


def checked_transform(value, label='transform'):
    t=finite(value,(4,4),label)
    r=t[:3,:3]
    if (not np.allclose(t[3],[0,0,0,1],atol=1e-9)
            or not np.allclose(r.T@r,np.eye(3),atol=1e-6)
            or not np.isclose(np.linalg.det(r),1.,atol=1e-6)):
        raise PoseRejected(label+': not a rigid transform in metres')
    return t.copy()


def pose_matrix(rotation,translation):
    t=np.eye(4);t[:3,:3]=rotation;t[:3,3]=translation
    return checked_transform(t)


def quaternion_xyzw(rotation):
    """Convert a proper rotation without adding a SciPy runtime dependency."""
    r=checked_transform(pose_matrix(rotation,np.zeros(3)))[:3,:3]
    # Rodrigues handles the180deg case as well as small rotations.
    v=cv2.Rodrigues(r)[0].reshape(3);theta=float(np.linalg.norm(v))
    xyz=v*(np.sin(theta/2)/theta) if theta>1e-12 else v*.5
    return np.r_[xyz,np.cos(theta/2)]
