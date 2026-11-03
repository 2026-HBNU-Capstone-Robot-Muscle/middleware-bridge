"""Color-sample and validate six YOLO-detected cube faces."""

from collections import Counter

import cv2
import numpy as np


CAPTURE_FACE_ORDER = ("F", "R", "B", "L", "U", "D")
SOLVER_FACE_ORDER = ("U", "R", "F", "D", "L", "B")
WARP_SIZE = 300
INNER_RATIO = 0.72


def order_corners(corners):
    """Order a convex four-corner polygon from image top-left clockwise."""
    points = np.asarray(corners, dtype=np.float32).reshape(4, 2)
    if not np.isfinite(points).all():
        raise ValueError("OBB corners contain non-finite coordinates")
    if abs(float(cv2.contourArea(cv2.convexHull(points)))) < 1e-3:
        raise ValueError("OBB corners do not form a valid quadrilateral")
    by_y = points[np.lexsort((points[:, 0], points[:, 1]))]
    top = by_y[:2][np.argsort(by_y[:2, 0])]
    bottom = by_y[2:][np.argsort(by_y[2:, 0])]
    return np.asarray([top[0], top[1], bottom[1], bottom[0]], dtype=np.float32)


def sample_face_colors(frame, corners):
    """Perspective-correct one face and return its nine median BGR samples."""
    source = order_corners(corners)
    end = WARP_SIZE - 1
    destination = np.asarray(
        [[0, 0], [end, 0], [end, end], [0, end]], dtype=np.float32
    )
    transform = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(frame, transform, (WARP_SIZE, WARP_SIZE))
    colors = []
    cell_size = WARP_SIZE / 3
    for row in range(3):
        for column in range(3):
            center_x = (column + 0.5) * cell_size
            center_y = (row + 0.5) * cell_size
            sample_width = cell_size * INNER_RATIO
            left = max(0, int(round(center_x - sample_width / 2)))
            right = min(WARP_SIZE, int(round(center_x + sample_width / 2)))
            top = max(0, int(round(center_y - sample_width / 2)))
            bottom = min(WARP_SIZE, int(round(center_y + sample_width / 2)))
            patch = warped[top:bottom, left:right]
            if patch.size == 0:
                raise ValueError("Sticker sample region is empty")
            colors.append(np.median(patch.reshape(-1, 3), axis=0))
    return np.asarray(colors, dtype=np.uint8)


def _bgr_to_lab(colors):
    values = np.ascontiguousarray(np.asarray(colors, dtype=np.uint8))
    return cv2.cvtColor(values.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3)


def classify_cube(captures):
    """Map six face samples to URFDLB facelets and return validation messages."""
    missing = [face for face in CAPTURE_FACE_ORDER if face not in captures]
    if missing:
        return "", [f"Missing captured faces: {', '.join(missing)}"]

    centers_bgr = np.asarray([captures[face][4] for face in CAPTURE_FACE_ORDER])
    centers_lab = _bgr_to_lab(centers_bgr).astype(np.float32)
    errors = []
    for index, face in enumerate(CAPTURE_FACE_ORDER):
        for other_index in range(index):
            distance = float(np.linalg.norm(centers_lab[index] - centers_lab[other_index]))
            if distance < 16.0:
                errors.append(
                    f"Center colors for {CAPTURE_FACE_ORDER[other_index]} and {face} "
                    f"are too similar (Lab distance {distance:.1f})"
                )

    labels_by_face = {}
    for face in CAPTURE_FACE_ORDER:
        samples_lab = _bgr_to_lab(captures[face]).astype(np.float32)
        distances = np.linalg.norm(samples_lab[:, None, :] - centers_lab[None, :, :], axis=2)
        order = np.argsort(distances, axis=1)
        labels_by_face[face] = [CAPTURE_FACE_ORDER[index] for index in order[:, 0]]

    facelets = "".join("".join(labels_by_face[face]) for face in SOLVER_FACE_ORDER)
    counts = Counter(facelets)
    wrong_counts = [f"{face}={counts.get(face, 0)}" for face in SOLVER_FACE_ORDER if counts.get(face, 0) != 9]
    if wrong_counts:
        errors.append("Each face color must occur exactly 9 times: " + ", ".join(wrong_counts))
    for face_index, face in enumerate(SOLVER_FACE_ORDER):
        center = facelets[face_index * 9 + 4]
        if center != face:
            errors.append(f"Center sticker for {face} face is {center}")

    if not errors:
        try:
            from rubik_solver import Cube

            cube = Cube.from_string(facelets)
            verification = cube.verify()
            if verification is not True:
                errors.append(f"Kociemba rejected the detected state: {verification}")
        except Exception as exc:
            errors.append(f"Physical cube-state validation failed: {exc}")
    return (facelets if not errors else ""), errors
