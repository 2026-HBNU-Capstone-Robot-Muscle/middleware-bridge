"""Refine YOLO search regions to image-supported face boundaries and center colors."""
import cv2
import numpy as np
from itertools import combinations
from .metric_cube_pose import FACE_ORDER,PoseRejected,finite,ordered_quad


class ColorReference:
    def __init__(self, centers_bgr, scan_id):
        if not isinstance(scan_id,str) or not scan_id.strip():raise PoseRejected('Color reference needs scan_id')
        self.scan_id=scan_id
        self.centers=finite(centers_bgr,(6,3),'URFDLB center colors')
        if np.any(self.centers<0) or np.any(self.centers>255):raise PoseRejected('Invalid BGR color range')
        self.lab=cv2.cvtColor(self.centers.astype(np.uint8).reshape(6,1,3),cv2.COLOR_BGR2LAB).reshape(6,3).astype(float)
        distances=np.linalg.norm(self.lab[:,None]-self.lab[None,:],axis=2)+np.eye(6)*1e6
        if distances.min()<16:raise PoseRejected('Six center colors are not distinct')

    def label(self,frame,quad):
        q=ordered_quad(quad).astype(np.float32)
        target=np.array([[0,0],[119,0],[119,119],[0,119]],np.float32)
        warped=cv2.warpPerspective(frame,cv2.getPerspectiveTransform(q,target),(120,120))
        # Center only: the surrounding eight stickers can be scrambled.
        patch=warped[48:72,48:72].reshape(-1,3)
        color=np.median(patch,axis=0).astype(np.uint8)
        lab=cv2.cvtColor(color.reshape(1,1,3),cv2.COLOR_BGR2LAB).reshape(3).astype(float)
        scores=np.linalg.norm(self.lab-lab,axis=1);order=np.argsort(scores)
        if scores[order[0]]>35 or scores[order[1]]-scores[order[0]]<8:
            raise PoseRejected('Face center color is occluded or ambiguous')
        return FACE_ORDER[int(order[0])],float(scores[order[0]])


def _grid_hypotheses(grid,square,centers,tiles,seeds,pitch):
    for seed in seeds:
        for cell in grid:
            for ratio in (.65,.75,.85):
                lattice=cell+(square-.5)*ratio
                yield cv2.getPerspectiveTransform(lattice.astype(np.float32),tiles[seed].astype(np.float32))
    # Rounded sticker corners are a noisy source of perspective at close range.
    # Observed neighboring *centers* provide an independent affine search seed.
    # They never supply final corners: all hypotheses need the same projective
    # inlier fit below, including seven cells spanning all three rows/columns.
    for seed in seeds[:3]:
        delta=centers-centers[seed]
        distances=np.linalg.norm(delta,axis=1)
        near=[i for i in np.argsort(distances) if .4*pitch<distances[i]<1.6*pitch][:5]
        for i,j in combinations(near,2):
            a,b=delta[i],delta[j]
            if abs(float(a@b))/(distances[i]*distances[j])>.75:continue
            if a[0]*b[1]-a[1]*b[0]<0:a,b=b,a
            basis=np.column_stack((a,b))
            for cell in grid:
                h=np.eye(3);h[:2,:2]=basis;h[:2,2]=centers[seed]-basis@cell
                yield h


def refine_face_quad(frame,obb):
    """OBB is only a search ROI; never promote its rectangle directly to PnP."""
    q=ordered_quad(obb);height,width=frame.shape[:2]
    diagonal=float(np.linalg.norm(q.max(axis=0)-q.min(axis=0)))
    pad=max(4,int(diagonal*.08));lo=np.floor(q.min(axis=0)).astype(int)-pad
    hi=np.ceil(q.max(axis=0)).astype(int)+pad
    if np.any(lo<0) or hi[0]>=width or hi[1]>=height:raise PoseRejected('Face search region reaches image border')
    roi=frame[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
    # Yellow/white and some red/green edges have little grayscale contrast.
    # Retain chromatic boundaries instead of silently losing whole grid rows.
    lab=cv2.cvtColor(roi,cv2.COLOR_BGR2LAB)
    edges=np.zeros(lab.shape[:2],np.uint8)
    for channel in cv2.split(lab):
        edges|=cv2.Canny(cv2.GaussianBlur(channel,(3,3),0),10,35)
    edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    # A shorter exposure preserves white stickers but darkens the side face.
    # A monotonic tone curve reveals existing shadow contrast without adding
    # geometric observations. Keep its contours separate to avoid joining
    # unrelated original/enhanced edge fragments into a fabricated boundary.
    curve=np.rint(np.sqrt(np.arange(256)/255.)*255).astype(np.uint8)
    boosted=cv2.cvtColor(cv2.LUT(roi,curve),cv2.COLOR_BGR2LAB)
    shadow_edges=np.zeros(edges.shape,np.uint8)
    for channel in cv2.split(boosted):
        shadow_edges|=cv2.Canny(cv2.GaussianBlur(channel,(3,3),0),10,35)
    shadow_edges=cv2.morphologyEx(shadow_edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    shadow_contours,_=cv2.findContours(shadow_edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    contours=list(contours)+list(shadow_contours)
    # Color-filled components remain usable when glare/noise breaks a Canny
    # loop. They are only sticker candidates; all still need the same grid fit.
    hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
    saturated=((hsv[:,:,1]>50)&(hsv[:,:,2]>55)).astype(np.uint8)*255
    saturated=cv2.morphologyEx(saturated,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    filled,_=cv2.findContours(saturated,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    # Shadow gives white plastic a color cast, joining blue stickers in the
    # broad mask. A second, higher-chroma mask separates those real boundaries
    # without requiring bright pixels. Both still need the same seven-cell fit.
    for saturation,value in ((120,30),(200,15)):
        shadow=((hsv[:,:,1]>saturation)&(hsv[:,:,2]>value)).astype(np.uint8)*255
        shadow=cv2.morphologyEx(shadow,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        separated,_=cv2.findContours(shadow,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        filled=list(filled)+list(separated)
    contours=list(filled)+list(contours)
    area=cv2.contourArea(q.astype(np.float32));centers=[];tiles=[];groups=[];group_centers=[]
    square=np.array([[0,0],[1,0],[1,1],[0,1]],np.float32)
    for contour in contours:
        # Printed stickers have rounded corners and compression notches.
        # Fit their convex outline; the multi-sticker lattice below still
        # rejects a clipped/merged patch that is not a consistent grid cell.
        hull=cv2.convexHull(contour);perimeter=cv2.arcLength(hull,True)
        approx=cv2.approxPolyDP(hull,.025*perimeter,True)
        if len(approx)>4:approx=cv2.approxPolyDP(hull,.04*perimeter,True)
        if len(approx)!=4 or not cv2.isContourConvex(approx):continue
        candidate_area=cv2.contourArea(approx)
        # Individual stickers, rather than the inner colored outline of an
        # entire face. Treating that outline as55mm biases metric depth.
        if not .018*area<=candidate_area<=.18*area:continue
        try:points=ordered_quad(approx.reshape(4,2)+lo,min_area=15,min_edge=2)
        except PoseRejected:continue
        # The candidate should explain this face ROI, rather than a nearby
        # sticker or another object. Keep perspective skew intact.
        transform=cv2.getPerspectiveTransform(square,points.astype(np.float32))
        center=cv2.perspectiveTransform(np.array([[[.5,.5]]],np.float64),transform).reshape(2)
        # Several masks can observe the same sticker. Preserve alternative
        # centers instead of making contour order choose the measurement, but
        # give them one identity so they cannot count as distinct grid cells.
        if any(np.linalg.norm(center-old)<1. for old in centers):continue
        close=[i for i,old in enumerate(group_centers) if np.linalg.norm(center-old)<max(3,np.sqrt(area)/25)]
        group=close[0] if close else len(group_centers)
        if not close:group_centers.append(center)
        centers.append(center);tiles.append(points);groups.append(group)
    # Assign image-supported sticker centers to a3x3 lattice. The OBB is
    # only the coarse search frame. Extrapolate the metric face from pitch,
    # not from an assumed physical width of sticker borders.
    if len(group_centers)<7:raise PoseRejected('Need seven image-supported stickers on a3x3 face grid inside the OBB')
    centers=np.asarray(centers);grid=np.array([[x+.5,y+.5] for y in range(3) for x in range(3)])
    candidates=[];pitch=np.sqrt(area)/3
    # Large, close-up stickers contain several pixels of rounded-edge and
    # camera sampling variation. Bound this *image feature* residual by cell
    # pitch, capped at3px; the downstream multi-face PnP limits stay unchanged.
    grid_tolerance=min(3.,max(1.5,.035*pitch))
    seeds=[];seen=set()
    for index in np.argsort(np.linalg.norm(centers-q.mean(axis=0),axis=1)):
        if groups[index] in seen:continue
        seeds.append(index);seen.add(groups[index])
        if len(seeds)==4:break
    # Seed using a few observed sticker quadrilaterals. This preserves their
    # perspective skew, unlike assigning rows directly in the rectangular OBB.
    # Sticker/border ratios are only search seeds; the final homography is
    # fitted to center-to-center pitch and does not retain that assumed ratio.
    for h in _grid_hypotheses(grid,square,centers,tiles,seeds,pitch):
        predicted=cv2.perspectiveTransform(grid.reshape(-1,1,2),h).reshape(-1,2)
        distances=np.linalg.norm(predicted[:,None,:]-centers[None,:,:],axis=2)
        used_grid=set();used_image=set();matches=[]
        for index in np.argsort(distances,axis=None):
            a,b=np.unravel_index(index,distances.shape)
            if distances[a,b]>pitch*.35:break
            if a not in used_grid and groups[b] not in used_image:
                used_grid.add(a);used_image.add(groups[b]);matches.append((a,b))
        if len(matches)<7:continue
        source=grid[[a for a,_ in matches]];image=centers[[b for _,b in matches]]
        h,mask=cv2.findHomography(source,image,cv2.RANSAC,grid_tolerance)
        if h is None or mask is None or np.count_nonzero(mask)<7:continue
        chosen=source[mask.ravel().astype(bool)]
        if any(len(np.unique(chosen[:,axis]))<3 for axis in (0,1)):continue
        fitted=cv2.perspectiveTransform(source.reshape(-1,1,2),h).reshape(-1,2)
        errors=np.linalg.norm(fitted-image,axis=1)[mask.ravel().astype(bool)]
        if errors.max()>grid_tolerance:continue
        try:refined=ordered_quad(cv2.perspectiveTransform((square*3).astype(float).reshape(-1,1,2),h).reshape(4,2))
        except PoseRejected:continue
        distance=min(np.mean(np.linalg.norm(refined-np.roll(q,k,axis=0),axis=1)) for k in range(4))/diagonal
        if distance>.2 or np.linalg.norm(refined.mean(axis=0)-q.mean(axis=0))>.15*diagonal:continue
        candidates.append((int(np.count_nonzero(mask)),float(np.sqrt(np.mean(errors**2))),refined))
    if not candidates:raise PoseRejected('Sticker centers do not fit a perspective3x3 face grid')
    candidates.sort(key=lambda c:(-c[0],c[1]));best=candidates[0]
    for count,error,other in candidates[1:]:
        difference=min(np.mean(np.linalg.norm(best[2]-np.roll(other,k,axis=0),axis=1)) for k in range(4))
        if count==best[0] and error-best[1]<.15 and difference>.05*diagonal:
            raise PoseRejected('Multiple3x3 grids explain the same OBB')
    return best[2]


def extract_labeled_faces(frame,detections,reference):
    faces={};rejected=[];ambiguous=set()
    for corners,confidence in detections:
        if not np.isfinite(confidence) or confidence<.5:continue
        try:
            q=refine_face_quad(frame,corners);label,_=reference.label(frame,q)
            if label in faces or label in ambiguous:
                faces.pop(label,None);ambiguous.add(label)
                raise PoseRejected('Duplicate center color in visible faces')
            faces[label]=q
        except PoseRejected as exc:rejected.append(str(exc))
    return faces,rejected
