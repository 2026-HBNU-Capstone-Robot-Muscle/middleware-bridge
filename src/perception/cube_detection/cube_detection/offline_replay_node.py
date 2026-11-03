"""Publish the six reference captures as labeled ROS image messages."""

from pathlib import Path

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from system_interfaces.msg import FaceCaptureLabel

from .cube_state import CAPTURE_FACE_ORDER


class CubeOfflineReplayNode(Node):
    """Replay original.png files in the established face-capture order."""

    def __init__(self):
        super().__init__("cube_offline_replay")
        self.declare_parameter("capture_root", "")
        self.declare_parameter("image_topic", "/camera/image_raw")
        self.declare_parameter("face_label_topic", "/cube/scan/face_label")
        self.declare_parameter("replay_interval_sec", 3.0)
        self.declare_parameter("startup_delay_sec", 5.0)
        self.declare_parameter("replay_passes", 2)
        root_value = str(self.get_parameter("capture_root").value).strip()
        if not root_value:
            raise ValueError("Set capture_root to the captures directory.")
        self.capture_root = Path(root_value).expanduser()
        if not self.capture_root.is_dir():
            raise ValueError(f"Capture directory does not exist: {self.capture_root}")
        self.images = {}
        for face in CAPTURE_FACE_ORDER:
            path = self.capture_root / face / "original.png"
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError(f"Could not read reference image: {path}")
            self.images[face] = frame

        self.bridge = CvBridge()
        self.image_publisher = self.create_publisher(
            Image, str(self.get_parameter("image_topic").value), 10
        )
        self.label_publisher = self.create_publisher(
            FaceCaptureLabel,
            str(self.get_parameter("face_label_topic").value),
            10,
        )
        interval = float(self.get_parameter("replay_interval_sec").value)
        startup_delay = float(self.get_parameter("startup_delay_sec").value)
        replay_passes = int(self.get_parameter("replay_passes").value)
        if interval <= 0 or startup_delay < 0 or replay_passes < 1:
            raise ValueError(
                "replay_interval_sec must be positive, startup_delay_sec non-negative, "
                "and replay_passes at least one"
            )
        self._faces = CAPTURE_FACE_ORDER * replay_passes
        self._index = 0
        self._interval = interval
        self._first_publish = True
        self._timer = self.create_timer(
            max(startup_delay, 0.1), self._publish_next
        )
        self.get_logger().info(
            f"Loaded six read-only sample images from {self.capture_root}"
        )

    def _publish_next(self):
        if self._index >= len(self._faces):
            self._timer.cancel()
            self.get_logger().info("Replay complete; keep ROS nodes running for results.")
            return
        face = self._faces[self._index]
        image = self.bridge.cv2_to_imgmsg(self.images[face], encoding="bgr8")
        image.header.stamp = self.get_clock().now().to_msg()
        image.header.frame_id = "offline_cube_scan"
        label = FaceCaptureLabel()
        label.header = image.header
        label.face_name = face
        self.label_publisher.publish(label)
        self.image_publisher.publish(image)
        pass_number = self._index // len(CAPTURE_FACE_ORDER) + 1
        self.get_logger().info(
            f"Published sample image for {face} (pass {pass_number})"
        )
        self._index += 1
        if self._first_publish:
            self._first_publish = False
            self._timer.cancel()
            self._timer = self.create_timer(self._interval, self._publish_next)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = CubeOfflineReplayNode()
        rclpy.spin(node)
    except ValueError as exc:
        print(f"cube_offline_replay: {exc}")
        return 2
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0
