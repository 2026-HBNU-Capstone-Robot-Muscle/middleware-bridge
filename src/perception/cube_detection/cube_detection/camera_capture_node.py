"""Capture six operator-labeled cube faces from a Windows camera."""

import time
import uuid
from collections import OrderedDict

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from system_interfaces.msg import CubeState, FaceDetectionArray
from system_interfaces.srv import SolveCube

from .cube_state import (
    CAPTURE_FACE_ORDER,
    DEFAULT_MAX_REASSIGNMENT_DELTA,
    classify_cube,
    sample_face_colors,
)


class CubeCameraCaptureNode(Node):
    """Capture cube faces, collect their YOLO detections, and validate the cube."""

    def __init__(self):
        super().__init__("cube_camera_capture")
        self.declare_parameter("camera_index", 0)
        self.declare_parameter("camera_backend", "dshow")
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 720)
        self.declare_parameter("camera_fps", 30.0)
        self.declare_parameter("preview_fps", 30.0)
        self.declare_parameter("detection_preview_fps", 5.0)
        self.declare_parameter("detection_overlay_max_age_sec", 1.0)
        self.declare_parameter("frame_id", "camera_optical_frame")
        self.declare_parameter("image_topic", "/camera/image_raw")
        self.declare_parameter("detections_topic", "/cube/face_detections")
        self.declare_parameter("cube_state_topic", "/cube/state")
        self.declare_parameter("solve_service", "/cube/solve")
        self.declare_parameter(
            "max_color_reassignment_delta", DEFAULT_MAX_REASSIGNMENT_DELTA
        )
        # 자동 인식의 경우 주석 해제
        # self.declare_parameter("result_timeout_sec", 30.0)
        self.declare_parameter("capture_retry_count", 2)
        self.declare_parameter("capture_retry_interval_sec", 0.5)

        camera_index = int(self.get_parameter("camera_index").value)
        backend_name = str(self.get_parameter("camera_backend").value).lower()
        backend_ids = {
            "dshow": cv2.CAP_DSHOW,
            "msmf": cv2.CAP_MSMF,
            "any": cv2.CAP_ANY,
        }
        if backend_name not in backend_ids:
            raise ValueError("camera_backend must be dshow, msmf, or any")

        self.camera = cv2.VideoCapture(camera_index, backend_ids[backend_name])
        if not self.camera.isOpened():
            self.camera.release()
            raise RuntimeError(
                f"Could not open camera_index={camera_index} with "
                f"camera_backend={backend_name}. Try another index or backend."
            )

        width = int(self.get_parameter("width").value)
        height = int(self.get_parameter("height").value)
        camera_fps = float(self.get_parameter("camera_fps").value)
        preview_fps = float(self.get_parameter("preview_fps").value)
        # 자동 인식의 경우 주석 해제
        # self._result_timeout = float(
        #     self.get_parameter("result_timeout_sec").value
        # )
        self._capture_retry_count = int(
            self.get_parameter("capture_retry_count").value
        )
        self._capture_retry_interval = float(
            self.get_parameter("capture_retry_interval_sec").value
        )
        if min(width, height) <= 0 or min(camera_fps, preview_fps) <= 0:
            self.camera.release()
            raise ValueError("Camera dimensions and frame rates must be positive")
        # 자동 인식의 경우 주석 해제
        # if self._result_timeout <= 0:
        #     self.camera.release()
        #     raise ValueError("result_timeout_sec must be greater than zero")
        if self._capture_retry_count < 0 or self._capture_retry_interval <= 0:
            self.camera.release()
            raise ValueError(
                "capture_retry_count must be non-negative and "
                "capture_retry_interval_sec must be positive"
            )

        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.camera.set(cv2.CAP_PROP_FPS, camera_fps)
        actual_width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
        self.get_logger().info(
            f"Opened camera {camera_index} ({backend_name}); "
            f"actual format={actual_width}x{actual_height} @ {actual_fps:.1f} FPS"
        )

        self.bridge = CvBridge()
        self.frame_id = str(self.get_parameter("frame_id").value)
        self.image_publisher = self.create_publisher(
            Image,
            str(self.get_parameter("image_topic").value),
            qos_profile_sensor_data,
        )
        self.detections_subscription = self.create_subscription(
            FaceDetectionArray,
            str(self.get_parameter("detections_topic").value),
            self._on_detections,
            qos_profile_sensor_data,
        )
        self.state_publisher = self.create_publisher(
            CubeState, str(self.get_parameter("cube_state_topic").value), 10
        )
        self.solve_client = self.create_client(
            SolveCube, str(self.get_parameter("solve_service").value)
        )
        self._max_color_reassignment_delta = float(
            self.get_parameter("max_color_reassignment_delta").value
        )
        detection_preview_fps = float(
            self.get_parameter("detection_preview_fps").value
        )
        self._overlay_max_age = float(
            self.get_parameter("detection_overlay_max_age_sec").value
        )
        if detection_preview_fps <= 0 or self._overlay_max_age <= 0:
            self.camera.release()
            raise ValueError(
                "detection_preview_fps and detection_overlay_max_age_sec "
                "must be positive"
            )
        self._inference_period = 1.0 / detection_preview_fps
        self._last_inference_publish = 0.0
        self._latest_detections = []
        self._latest_detection_time = 0.0
        self._pending_captures = OrderedDict()
        self._captures = {}
        self._completed = False
        self._phase = "capturing"
        self._face_index = 0
        self._scan_id = uuid.uuid4().hex
        # 자동 인식의 경우 주석 해제
        # self._result_deadline = None
        self._shutdown_requested = False
        self._capture_retries = []
        self._last_frame_log = 0.0
        cv2.namedWindow("Cube camera scan", cv2.WINDOW_NORMAL)
        self._timer = self.create_timer(1.0 / preview_fps, self._on_timer)
        self._retry_timer = self.create_timer(
            self._capture_retry_interval, self._retry_captures
        )
        self.get_logger().info(
            f"YOLO overlay enabled at up to "
            f"{1.0 / self._inference_period:.1f} FPS; "
            "camera capture and six-face collection run in this node."
        )
        self.get_logger().info(
            "Starting pose: camera-facing F, top U, user-right R. "
            "Press Space to capture each face in F, R, B, L, U, D order; "
            "press R to restart or Q to quit; rotate the whole cube without "
            "twisting individual faces."
        )

    def _on_timer(self):
        now = time.monotonic()
        # 자동 인식의 경우 주석 해제
        # if self._result_deadline is not None and now >= self._result_deadline:
        #     self.get_logger().error(
        #         "No CubeState arrived before result_timeout_sec elapsed."
        #     )
        #     self._retry_ready = True
        #     return

        ok, frame = self.camera.read()
        if not ok or frame is None:
            if now - self._last_frame_log > 2.0:
                self.get_logger().warning("Camera frame read failed; retrying.")
                self._last_frame_log = now
            cv2.waitKey(1)
            return

        self._publish_preview_for_detection(frame, now)
        if self._face_index < len(CAPTURE_FACE_ORDER):
            instruction = (
                f"Face: {CAPTURE_FACE_ORDER[self._face_index]}  "
                "[SPACE] capture  [R] restart  [Q] quit"
            )
        elif self._phase == "waiting_detection":
            instruction = "Waiting for YOLO result  [R] rescan  [Q] quit"
        elif self._phase == "invalid":
            instruction = "Scan invalid; press [R] to retry or [Q] to quit"
        else:
            instruction = "Cube state valid; [R] new scan  [Q] quit"
        preview = frame.copy()
        self._draw_latest_detections(preview, now)
        cv2.putText(
            preview,
            instruction,
            (20, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (30, 230, 30),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("Cube camera scan", preview)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q"), 27):
            self.get_logger().info("Camera scan cancelled by operator.")
            self._shutdown_requested = True
            return
        if key in (ord("r"), ord("R")):
            self._start_new_scan()
            return
        if key == 32 and self._face_index < len(CAPTURE_FACE_ORDER):
            self._publish_capture(frame)

    def _start_new_scan(self):
        self._scan_id = uuid.uuid4().hex
        self._face_index = 0
        self._phase = "capturing"
        self._completed = False
        self._captures.clear()
        self._pending_captures.clear()
        self._capture_retries.clear()
        self.get_logger().info(
            f"Starting a new camera scan (scan_id={self._scan_id}); "
            "capture all six faces again from F."
        )

    def _publish_capture(self, frame):
        face_name = CAPTURE_FACE_ORDER[self._face_index]
        image = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        image.header.stamp = self.get_clock().now().to_msg()
        image.header.frame_id = self.frame_id
        key = self._stamp_key(image)
        self._pending_captures[key] = (face_name, self._scan_id, frame.copy())
        self._pending_captures.move_to_end(key)
        while len(self._pending_captures) > 12:
            expired_key, expired_capture = self._pending_captures.popitem(last=False)
            self.get_logger().warning(
                f"Dropping stale pending capture {expired_capture[0]} "
                f"with stamp {expired_key}; press R to rescan if needed."
            )
        self.image_publisher.publish(image)
        if self._capture_retry_count:
            self._capture_retries.append(
                (image, face_name, self._scan_id, self._capture_retry_count)
            )
        self._face_index += 1
        self.get_logger().info(
            f"Captured face {face_name} ({self._face_index}/6). "
            "Hold still for a moment, then follow the next face instruction."
        )
        if self._face_index == len(CAPTURE_FACE_ORDER):
            self._phase = "waiting_detection"
            # 자동 인식의 경우 주석 해제
            # self._result_deadline = time.monotonic() + self._result_timeout
            self.get_logger().info(
                "All six capture images published; waiting for YOLO detections, "
                "state validation, and solve."
            )

    def _retry_captures(self):
        remaining = []
        for image, face_name, scan_id, attempts_left in self._capture_retries:
            if scan_id != self._scan_id:
                continue
            self.image_publisher.publish(image)
            attempts_left -= 1
            if attempts_left:
                remaining.append((image, face_name, scan_id, attempts_left))
            self.get_logger().info(
                f"Resent capture image for {face_name}; "
                f"{attempts_left} retry attempt(s) remain."
            )
        self._capture_retries = remaining

    @staticmethod
    def _stamp_key(message):
        return (message.header.stamp.sec, message.header.stamp.nanosec)

    def _publish_preview_for_detection(self, frame, now):
        if (
            self._pending_captures
            or now - self._last_inference_publish < self._inference_period
        ):
            return
        image = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        image.header.stamp = self.get_clock().now().to_msg()
        image.header.frame_id = self.frame_id
        self.image_publisher.publish(image)
        self._last_inference_publish = now

    def _on_detections(self, message):
        self._latest_detections = list(message.detections)
        self._latest_detection_time = time.monotonic()
        key = self._stamp_key(message)
        capture = self._pending_captures.get(key)
        if capture is None:
            return
        face_name, scan_id, frame = capture
        if scan_id != self._scan_id or face_name in self._captures:
            self._pending_captures.pop(key, None)
            return
        if not message.detections:
            self.get_logger().warning(
                f"No YOLO face detection for captured face {face_name}; "
                "waiting for its image retry."
            )
            return
        detection = max(message.detections, key=lambda item: item.confidence)
        try:
            corners = [[point.x, point.y] for point in detection.corners_px]
            self._captures[face_name] = sample_face_colors(frame, corners)
        except (ValueError, RuntimeError) as exc:
            self.get_logger().warning(
                f"Could not sample {face_name} face; awaiting retry: {exc}"
            )
            return
        self._pending_captures.pop(key, None)
        self.get_logger().info(
            f"Captured {face_name}: class={detection.class_name}, "
            f"confidence={detection.confidence:.3f}; "
            f"collected {len(self._captures)}/6 faces."
        )
        if len(self._captures) == len(CAPTURE_FACE_ORDER):
            self._finalize_cube_state(message.header)

    def _draw_latest_detections(self, frame, now):
        if now - self._latest_detection_time > self._overlay_max_age:
            cv2.putText(
                frame,
                "YOLO: waiting for detection",
                (20, 68),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 200, 255),
                2,
                cv2.LINE_AA,
            )
            return
        for detection in self._latest_detections:
            corners = np.asarray(
                [[point.x, point.y] for point in detection.corners_px],
                dtype=np.int32,
            ).reshape(-1, 1, 2)
            cv2.polylines(frame, [corners], True, (0, 255, 0), 2, cv2.LINE_AA)
            x, y = corners[0, 0]
            label = f"{detection.class_name} {detection.confidence:.2f}"
            cv2.putText(
                frame,
                label,
                (int(x), max(22, int(y) - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        cv2.putText(
            frame,
            f"YOLO: {len(self._latest_detections)} face(s)",
            (20, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    def _finalize_cube_state(self, header):
        if self._completed:
            return
        self._completed = True
        self._pending_captures.clear()
        self._capture_retries.clear()
        facelets, validation_errors, corrections = classify_cube(
            self._captures, self._max_color_reassignment_delta
        )
        if corrections:
            self.get_logger().warning(
                "Balanced near-boundary color assignments: "
                + "; ".join(corrections)
            )
        state = CubeState()
        state.header = header
        state.scan_id = self._scan_id
        state.valid = not validation_errors and bool(facelets)
        state.facelets = facelets if state.valid else ""
        state.observed_faces = [
            face for face in CAPTURE_FACE_ORDER if face in self._captures
        ]
        state.validation_errors = validation_errors
        self.state_publisher.publish(state)
        if not state.valid:
            self._phase = "invalid"
            self.get_logger().error(
                "Cube state rejected: " + "; ".join(validation_errors)
            )
            self.get_logger().info("Press R to start a new six-face scan.")
            return

        self._phase = "valid"
        self.get_logger().info(f"Valid URFDLB cube state: {state.facelets}")
        if not self.solve_client.wait_for_service(timeout_sec=0.1):
            self.get_logger().error(
                "Cube state published, but /cube/solve is not available."
            )
            return
        request = SolveCube.Request()
        request.facelets = state.facelets
        future = self.solve_client.call_async(request)
        future.add_done_callback(self._on_solution)

    def _on_solution(self, future):
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().error(f"Cube solver request failed: {exc}")
            return
        if response.success:
            self.get_logger().info(
                "Solver response: "
                + (" ".join(response.moves) or "already solved")
            )
        else:
            self.get_logger().error(
                f"Cube solver rejected state: {response.error_message}"
            )

    def destroy_node(self):
        if hasattr(self, "camera"):
            self.camera.release()
        cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = None
    try:
        node = CubeCameraCaptureNode()
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        while rclpy.ok() and not node._shutdown_requested:
            executor.spin_once(timeout_sec=0.1)
    except (RuntimeError, ValueError) as exc:
        print(f"cube_camera_capture: {exc}")
        return 2
    finally:
        if executor is not None:
            if node is not None:
                executor.remove_node(node)
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0
