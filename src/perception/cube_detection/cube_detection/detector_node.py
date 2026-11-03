"""ROS 2 image subscriber that publishes YOLO OBB cube-face detections."""

import os
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from cv_bridge import CvBridge, CvBridgeError
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from system_interfaces.msg import FaceDetection, FaceDetectionArray


class CubeDetectorNode(Node):
    """Run a configured Ultralytics OBB model for each incoming image."""

    def __init__(self):
        super().__init__('cube_detector')
        bundled_model_path = (
            Path(get_package_share_directory('cube_detection'))
            / 'model'
            / 'cube-detector.pt'
        )
        self.declare_parameter('model_path', str(bundled_model_path))
        self.declare_parameter('image_topic', '/camera/image_raw')
        self.declare_parameter('detections_topic', '/cube/face_detections')
        self.declare_parameter('confidence_threshold', 0.5)
        self.declare_parameter('device', 'cpu')

        model_path_value = str(self.get_parameter('model_path').value).strip()
        if not model_path_value:
            raise ValueError(
                'Set the model_path parameter to an existing YOLO .pt checkpoint.'
            )
        model_path = Path(model_path_value).expanduser()
        if not model_path.is_file():
            raise ValueError(f'YOLO checkpoint does not exist: {model_path}')

        try:
            config_directory = Path.cwd() / 'log' / 'ultralytics'
            config_directory.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault(
                'YOLO_CONFIG_DIR', str(config_directory)
            )
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                'Ultralytics is missing. Install the Pixi project dependencies.'
            ) from exc

        self.confidence_threshold = float(
            self.get_parameter('confidence_threshold').value
        )
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError('confidence_threshold must be between 0 and 1.')

        self.device = str(self.get_parameter('device').value)
        self.bridge = CvBridge()
        self.model = YOLO(str(model_path))
        self.publisher = self.create_publisher(
            FaceDetectionArray,
            str(self.get_parameter('detections_topic').value),
            qos_profile_sensor_data,
        )
        self.subscription = self.create_subscription(
            Image,
            str(self.get_parameter('image_topic').value),
            self._on_image,
            qos_profile_sensor_data,
        )
        self.get_logger().info(
            f'Loaded YOLO model {model_path}; waiting for images.'
        )

    def _on_image(self, image_message):
        try:
            frame = self.bridge.imgmsg_to_cv2(
                image_message, desired_encoding='bgr8'
            )
            result = self.model.predict(
                source=frame,
                conf=self.confidence_threshold,
                verbose=False,
                device=self.device,
            )[0]
        except CvBridgeError as exc:
            self.get_logger().error(f'Could not convert input image: {exc}')
            return
        except Exception as exc:  # Keep one bad frame from stopping the node.
            self.get_logger().error(f'YOLO inference failed: {exc}')
            return

        message = FaceDetectionArray()
        message.header = image_message.header
        obb = result.obb
        if obb is not None and len(obb) > 0:
            corners_batch = obb.xyxyxyxy.cpu().numpy()
            confidences = obb.conf.cpu().numpy()
            classes = obb.cls.cpu().numpy()
            names = result.names

            for corners, confidence, class_id in zip(
                corners_batch, confidences, classes
            ):
                detection = FaceDetection()
                detection.class_name = str(names[int(class_id)])
                detection.confidence = float(confidence)
                for index, (x, y) in enumerate(corners):
                    detection.corners_px[index].x = float(x)
                    detection.corners_px[index].y = float(y)
                    detection.corners_px[index].z = 0.0
                detection.center_px.x = float(corners[:, 0].mean())
                detection.center_px.y = float(corners[:, 1].mean())
                detection.center_px.z = 0.0
                message.detections.append(detection)

        self.publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = CubeDetectorNode()
        rclpy.spin(node)
    except (ValueError, RuntimeError) as exc:
        print(f'cube_detector: {exc}')
        return 2
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0
