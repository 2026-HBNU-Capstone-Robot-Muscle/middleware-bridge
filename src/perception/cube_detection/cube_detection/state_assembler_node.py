"""Assemble labeled face detections into a validated cube and request a solution."""

from collections import OrderedDict
import time

import rclpy
from cv_bridge import CvBridge, CvBridgeError
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from system_interfaces.msg import (
    CubeState,
    FaceCaptureLabel,
    FaceDetectionArray,
)
from system_interfaces.srv import SolveCube

from .cube_state import CAPTURE_FACE_ORDER, classify_cube, sample_face_colors


class CubeStateAssemblerNode(Node):
    """Pair image, YOLO result, and scan label by their ROS header timestamp."""

    def __init__(self):
        super().__init__("cube_state_assembler")
        self.declare_parameter("image_topic", "/camera/image_raw")
        self.declare_parameter("detections_topic", "/cube/face_detections")
        self.declare_parameter("face_label_topic", "/cube/scan/face_label")
        self.declare_parameter("cube_state_topic", "/cube/state")
        self.declare_parameter("solve_service", "/cube/solve")
        self.declare_parameter("scan_timeout_sec", 12.0)
        self.bridge = CvBridge()
        self._pending = {
            "image": OrderedDict(),
            "detections": OrderedDict(),
            "label": OrderedDict(),
        }
        self._captures = {}
        self._errors = []
        self._completed = False
        self._scan_timeout = float(self.get_parameter("scan_timeout_sec").value)
        if self._scan_timeout <= 0:
            raise ValueError("scan_timeout_sec must be greater than zero")
        self._last_label_time = None
        self._last_header = None
        self.state_publisher = self.create_publisher(
            CubeState, str(self.get_parameter("cube_state_topic").value), 10
        )
        self.solve_client = self.create_client(
            SolveCube, str(self.get_parameter("solve_service").value)
        )
        self.create_subscription(
            Image,
            str(self.get_parameter("image_topic").value),
            self._on_image,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            FaceDetectionArray,
            str(self.get_parameter("detections_topic").value),
            self._on_detections,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            FaceCaptureLabel,
            str(self.get_parameter("face_label_topic").value),
            self._on_label,
            10,
        )
        self._timeout_timer = self.create_timer(1.0, self._check_scan_timeout)
        self.get_logger().info(
            "Pairing images, detections, and face labels by timestamp; "
            "waiting for F, R, B, L, U, D."
        )

    @staticmethod
    def _stamp_key(message):
        return (message.header.stamp.sec, message.header.stamp.nanosec)

    def _store(self, kind, message):
        pending = self._pending[kind]
        key = self._stamp_key(message)
        pending[key] = message
        pending.move_to_end(key)
        while len(pending) > 32:
            pending.popitem(last=False)
        self._try_consume(key)

    def _on_image(self, message):
        self._store("image", message)

    def _on_detections(self, message):
        self._store("detections", message)

    def _on_label(self, message):
        self._last_label_time = time.monotonic()
        self._last_header = message.header
        self._store("label", message)

    def _check_scan_timeout(self):
        if (
            self._completed
            or self._last_label_time is None
            or time.monotonic() - self._last_label_time <= self._scan_timeout
        ):
            return
        missing = [face for face in CAPTURE_FACE_ORDER if face not in self._captures]
        if missing:
            self._errors.append(
                f"Timed out waiting for cube faces: {', '.join(missing)}"
            )
        self._finalize(self._last_header)

    def _try_consume(self, key):
        if self._completed or any(key not in items for items in self._pending.values()):
            return
        image = self._pending["image"].pop(key)
        detections = self._pending["detections"].pop(key)
        label = self._pending["label"].pop(key)
        face_name = label.face_name.strip().upper()
        if face_name not in CAPTURE_FACE_ORDER:
            self._errors.append(f"Unsupported face label: {label.face_name!r}")
            self.get_logger().error(self._errors[-1])
            return
        if face_name in self._captures:
            self.get_logger().warning(f"Ignoring duplicate capture for {face_name}")
            return
        if not detections.detections:
            self.get_logger().warning(f"No YOLO face detection for {face_name}; awaiting retry")
            return

        detection = max(detections.detections, key=lambda item: item.confidence)
        try:
            frame = self.bridge.imgmsg_to_cv2(image, desired_encoding="bgr8")
            corners = [[point.x, point.y] for point in detection.corners_px]
            self._captures[face_name] = sample_face_colors(frame, corners)
            self.get_logger().info(
                f"Captured {face_name}: class={detection.class_name}, "
                f"confidence={detection.confidence:.3f}"
            )
        except (CvBridgeError, ValueError, RuntimeError) as exc:
            self.get_logger().warning(
                f"Could not sample {face_name} face; awaiting retry: {exc}"
            )
            return
        self._finish_if_complete(detections.header)

    def _finish_if_complete(self, header):
        if len(self._captures) == len(CAPTURE_FACE_ORDER):
            self._finalize(header)

    def _finalize(self, header):
        if self._completed:
            return
        self._completed = True
        facelets, validation_errors = classify_cube(self._captures)
        errors = self._errors + validation_errors
        state = CubeState()
        if header is not None:
            state.header = header
        state.valid = not errors and bool(facelets)
        state.facelets = facelets if state.valid else ""
        state.observed_faces = [
            face for face in CAPTURE_FACE_ORDER
            if face in self._captures
        ]
        state.validation_errors = errors
        self.state_publisher.publish(state)
        if not state.valid:
            self.get_logger().error(
                "Cube state rejected: " + "; ".join(errors)
            )
            return

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
                "Solver response: " + (" ".join(response.moves) or "already solved")
            )
        else:
            self.get_logger().error(f"Cube solver rejected state: {response.error_message}")


def main(args=None):
    rclpy.init(args=args)
    node = CubeStateAssemblerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
