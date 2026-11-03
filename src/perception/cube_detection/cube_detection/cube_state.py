"""Color-sample and validate six YOLO-detected cube faces."""

from collections import Counter

import cv2
import numpy as np


CAPTURE_FACE_ORDER = ("F", "R", "B", "L", "U", "D")
SOLVER_FACE_ORDER = ("U", "R", "F", "D", "L", "B")
WARP_SIZE = 300
INNER_RATIO = 0.72
DEFAULT_MAX_REASSIGNMENT_DELTA = 20.0


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


def _balance_color_assignments(distances, max_reassignment_delta):
    """Balance nearest-center labels to nine stickers per color conservatively."""
    labels = np.argmin(distances, axis=1)
    initial_counts = np.bincount(labels, minlength=len(CAPTURE_FACE_ORDER))
    counts = initial_counts.copy()
    corrections = []
    while np.any(counts != 9):
        best = None
        for sticker_index, source in enumerate(labels):
            if counts[source] <= 9 or sticker_index % 9 == 4:
                continue
            for target in range(len(CAPTURE_FACE_ORDER)):
                if counts[target] >= 9:
                    continue
                delta = float(
                    distances[sticker_index, target]
                    - distances[sticker_index, source]
                )
                if best is None or delta < best[0]:
                    best = (delta, sticker_index, int(source), target)
        if best is None or best[0] > max_reassignment_delta:
            raw_counts = ", ".join(
                f"{face}={initial_counts[index]}"
                for index, face in enumerate(CAPTURE_FACE_ORDER)
            )
            return None, corrections, (
                "Could not balance sticker colors within the configured Lab "
                f"reassignment limit ({max_reassignment_delta:.1f}); "
                f"nearest-center counts: {raw_counts}"
            )

        delta, sticker_index, source, target = best
        labels[sticker_index] = target
        counts[source] -= 1
        counts[target] += 1
        face = CAPTURE_FACE_ORDER[sticker_index // 9]
        cell = sticker_index % 9 + 1
        corrections.append(
            f"{face}[{cell}] {CAPTURE_FACE_ORDER[source]}->"
            f"{CAPTURE_FACE_ORDER[target]} (extra Lab distance {delta:.1f})"
        )
    return labels, corrections, None


def classify_cube(
    captures,
    max_reassignment_delta=DEFAULT_MAX_REASSIGNMENT_DELTA,
):
    """Map six face samples to balanced URFDLB facelets and validate them."""
    missing = [face for face in CAPTURE_FACE_ORDER if face not in captures]
    if missing:
        return "", [f"Missing captured faces: {', '.join(missing)}"], []
    if max_reassignment_delta < 0:
        return "", ["max_reassignment_delta must be non-negative"], []

    centers_bgr = np.asarray([captures[face][4] for face in CAPTURE_FACE_ORDER])
    centers_lab = _bgr_to_lab(centers_bgr).astype(np.float32)
    errors = []
    for index, face in enumerate(CAPTURE_FACE_ORDER):
        for other_index in range(index):
            distance = float(
                np.linalg.norm(centers_lab[index] - centers_lab[other_index])
            )
            if distance < 16.0:
                errors.append(
                    f"Center colors for {CAPTURE_FACE_ORDER[other_index]} and {face} "
                    f"are too similar (Lab distance {distance:.1f})"
                )

    all_samples = np.vstack([captures[face] for face in CAPTURE_FACE_ORDER])
    samples_lab = _bgr_to_lab(all_samples).astype(np.float32)
    distances = np.linalg.norm(
        samples_lab[:, None, :] - centers_lab[None, :, :], axis=2
    )
    assigned, corrections, balance_error = _balance_color_assignments(
        distances, float(max_reassignment_delta)
    )
    if balance_error:
        errors.append(balance_error)

    labels_by_face = {}
    for face in CAPTURE_FACE_ORDER:
        face_index = CAPTURE_FACE_ORDER.index(face)
        if assigned is None:
            labels_by_face[face] = [
                CAPTURE_FACE_ORDER[index]
                for index in np.argmin(
                    distances[face_index * 9:(face_index + 1) * 9], axis=1
                )
            ]
        else:
            labels_by_face[face] = [
                CAPTURE_FACE_ORDER[index]
                for index in assigned[face_index * 9:(face_index + 1) * 9]
            ]

    facelets = "".join("".join(labels_by_face[face]) for face in SOLVER_FACE_ORDER)
    counts = Counter(facelets)
    wrong_counts = [
        f"{face}={counts.get(face, 0)}"
        for face in SOLVER_FACE_ORDER
        if counts.get(face, 0) != 9
    ]
    if wrong_counts:
        errors.append(
            "Each face color must occur exactly 9 times: "
            + ", ".join(wrong_counts)
        )
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
    return (facelets if not errors else ""), errors, corrections
