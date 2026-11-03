"""Capture six operator-labeled cube faces from a Windows camera."""

import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from system_interfaces.msg import CubeState, FaceCaptureLabel

from .cube_state import CAPTURE_FACE_ORDER


class CubeCameraCaptureNode(Node):
    """Preview a camera and publish one image when the operator presses Space."""

    def __init__(self):
        super().__init__("cube_camera_capture")
        self.declare_parameter("camera_index", 0)
        self.declare_parameter("camera_backend", "dshow")
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 720)
        self.declare_parameter("camera_fps", 30.0)
        self.declare_parameter("preview_fps", 30.0)
        self.declare_parameter("frame_id", "camera_optical_frame")
        self.declare_parameter("image_topic", "/camera/image_raw")
        self.declare_parameter("face_label_topic", "/cube/scan/face_label")
        self.declare_parameter("cube_state_topic", "/cube/state")
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
            Image, str(self.get_parameter("image_topic").value), 10
        )
        self.label_publisher = self.create_publisher(
            FaceCaptureLabel,
            str(self.get_parameter("face_label_topic").value),
            10,
        )
        self.create_subscription(
            CubeState,
            str(self.get_parameter("cube_state_topic").value),
            self._on_cube_state,
            10,
        )
        self._face_index = 0
        self._waiting_for_state = False
        # 자동 인식의 경우 주석 해제
        # self._result_deadline = None
        self._shutdown_deadline = None
        self._capture_retries = []
        self._last_frame_log = 0.0
        cv2.namedWindow("Cube camera scan", cv2.WINDOW_NORMAL)
        self._timer = self.create_timer(1.0 / preview_fps, self._on_timer)
        self._retry_timer = self.create_timer(
            self._capture_retry_interval, self._retry_captures
        )
        self.get_logger().info(
            "Starting pose: camera-facing F, top U, user-right R. "
            "Press Space to capture each face in F, R, B, L, U, D order; "
            "rotate the whole cube without twisting individual faces."
        )

    def _on_timer(self):
        now = time.monotonic()
        if self._shutdown_deadline is not None and now >= self._shutdown_deadline:
            rclpy.shutdown()
            return
        # 자동 인식의 경우 주석 해제
        # if (
        #     self._waiting_for_state
        #     and self._result_deadline is not None
        #     and now >= self._result_deadline
        # ):
        #     self.get_logger().error(
        #         "No CubeState arrived before result_timeout_sec elapsed."
        #     )
        #     rclpy.shutdown()
        #     return

        ok, frame = self.camera.read()
        if not ok or frame is None:
            if now - self._last_frame_log > 2.0:
                self.get_logger().warning("Camera frame read failed; retrying.")
                self._last_frame_log = now
            cv2.waitKey(1)
            return

        instruction = (
            f"Face: {CAPTURE_FACE_ORDER[self._face_index]}  "
            "[SPACE] capture  [Q] quit"
            if self._face_index < len(CAPTURE_FACE_ORDER)
            else "All six faces sent; waiting for CubeState  [Q] quit"
        )
        preview = frame.copy()
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
            rclpy.shutdown()
            return
        if key == 32 and self._face_index < len(CAPTURE_FACE_ORDER):
            self._publish_capture(frame)

    def _publish_capture(self, frame):
        face_name = CAPTURE_FACE_ORDER[self._face_index]
        image = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        image.header.stamp = self.get_clock().now().to_msg()
        image.header.frame_id = self.frame_id
        label = FaceCaptureLabel()
        label.header = image.header
        label.face_name = face_name
        self.image_publisher.publish(image)
        self.label_publisher.publish(label)
        if self._capture_retry_count:
            self._capture_retries.append(
                (image, label, self._capture_retry_count)
            )
        self._face_index += 1
        self.get_logger().info(
            f"Captured face {face_name} ({self._face_index}/6). "
            "Hold still for a moment, then follow the next face instruction."
        )
        if self._face_index == len(CAPTURE_FACE_ORDER):
            self._waiting_for_state = True
            # 자동 인식의 경우 주석 해제
            # self._result_deadline = time.monotonic() + self._result_timeout
            self.get_logger().info(
                "All six labeled images published; waiting for state validation "
                "and solve."
            )

    def _retry_captures(self):
        remaining = []
        for image, label, attempts_left in self._capture_retries:
            self.image_publisher.publish(image)
            self.label_publisher.publish(label)
            attempts_left -= 1
            if attempts_left:
                remaining.append((image, label, attempts_left))
            self.get_logger().info(
                f"Resent capture for {label.face_name}; "
                f"{attempts_left} retry attempt(s) remain."
            )
        self._capture_retries = remaining

    def _on_cube_state(self, message):
        if not self._waiting_for_state:
            return
        if message.valid:
            self.get_logger().info(
                f"Camera scan produced a valid cube state: {message.facelets}"
            )
        else:
            self.get_logger().error(
                "Camera scan state is invalid: "
                + "; ".join(message.validation_errors)
            )
        self._waiting_for_state = False
        # 자동 인식의 경우 주석 해제
        # self._result_deadline = None
        self._shutdown_deadline = time.monotonic() + 2.0

    def destroy_node(self):
        if hasattr(self, "camera"):
            self.camera.release()
        cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = CubeCameraCaptureNode()
        rclpy.spin(node)
    except (RuntimeError, ValueError) as exc:
        print(f"cube_camera_capture: {exc}")
        return 2
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0
