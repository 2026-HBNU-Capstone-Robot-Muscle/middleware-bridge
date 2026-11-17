"""Start and stop the interactive cube camera node through a ROS service."""

import subprocess
import sys
import time

import cv2
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from system_interfaces.srv import ListCameras, SetCameraEnabled


class CubeCameraManagerNode(Node):
    """Own the camera capture process so the GUI can toggle it safely."""

    def __init__(self):
        super().__init__("cube_camera_manager")
        self.declare_parameter("camera_index", 0)
        self.declare_parameter("camera_backend", "dshow")
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 720)
        self.declare_parameter("camera_fps", 30.0)
        self.declare_parameter("startup_check_sec", 1.5)
        self.declare_parameter("camera_probe_max_index", 2)
        self._camera_process = None
        self._active_camera_index = -1
        self._camera_indices = []
        self._active_publisher = self.create_publisher(Bool, "/cube/camera_active", 1)
        self._state_timer = self.create_timer(0.5, self._publish_state)
        self._service = self.create_service(
            SetCameraEnabled,
            "/cube/set_camera_enabled",
            self._set_camera_enabled,
        )
        self._list_service = self.create_service(
            ListCameras,
            "/cube/list_cameras",
            self._list_cameras,
        )
        self.get_logger().info(
            "Camera manager ready: /cube/list_cameras and /cube/set_camera_enabled."
        )

    def _is_active(self):
        if self._camera_process is None:
            return False
        if self._camera_process.poll() is None:
            return True
        self._camera_process = None
        self._active_camera_index = -1
        return False

    def _publish_state(self):
        message = Bool()
        message.data = self._is_active()
        self._active_publisher.publish(message)

    def _camera_command(self, backend, camera_index):
        camera_main = (
            "from cube_detection.camera_capture_node import main; "
            "raise SystemExit(main())"
        )
        return [
            sys.executable,
            "-c",
            camera_main,
            "--ros-args",
            "-p",
            f"camera_index:={camera_index}",
            "-p",
            f"camera_backend:={backend}",
            "-p",
            f"width:={int(self.get_parameter('width').value)}",
            "-p",
            f"height:={int(self.get_parameter('height').value)}",
            "-p",
            f"camera_fps:={float(self.get_parameter('camera_fps').value):.1f}",
        ]

    def _probe_camera(self, camera_index):
        preferred = str(self.get_parameter("camera_backend").value).lower()
        backend_ids = {
            "dshow": cv2.CAP_DSHOW,
            "msmf": cv2.CAP_MSMF,
            "any": cv2.CAP_ANY,
        }
        backends = list(dict.fromkeys((preferred, "dshow", "msmf", "any")))
        for backend in backends:
            capture = None
            try:
                capture = cv2.VideoCapture(camera_index, backend_ids[backend])
                if capture.isOpened():
                    success, frame = capture.read()
                    if success and frame is not None and frame.size:
                        return True
            except (cv2.error, KeyError):
                pass
            finally:
                if capture is not None:
                    capture.release()
        return False

    def _list_cameras(self, _request, response):
        if not self._is_active():
            max_index = max(0, int(self.get_parameter("camera_probe_max_index").value))
            detected = []
            for camera_index in range(max_index + 1):
                if self._probe_camera(camera_index):
                    detected.append(camera_index)
                    if len(detected) == 3:
                        break
            self._camera_indices = detected
        elif self._active_camera_index >= 0 and self._active_camera_index not in self._camera_indices:
            self._camera_indices = [*self._camera_indices, self._active_camera_index][:3]

        response.camera_indices = self._camera_indices[:3]
        response.active = self._is_active()
        response.active_camera_index = self._active_camera_index if response.active else -1
        response.preferred_camera_index = int(
            self.get_parameter("camera_index").value
        )
        response.message = (
            f"Detected {len(response.camera_indices)} camera(s)."
            if response.camera_indices
            else "No camera detected at indices 0-2."
        )
        self.get_logger().info(response.message)
        return response

    def _start_camera(self, camera_index):
        if self._is_active():
            if self._active_camera_index == camera_index:
                return True, "Camera capture is already active."
            return False, "Stop the active camera before selecting another device."

        preferred = str(self.get_parameter("camera_backend").value).lower()
        if preferred not in ("dshow", "msmf", "any"):
            return False, f"Unsupported camera backend: {preferred}"
        backends = list(dict.fromkeys((preferred, "dshow", "msmf", "any")))
        startup_check_sec = float(self.get_parameter("startup_check_sec").value)
        errors = []

        for backend in backends:
            try:
                process = subprocess.Popen(self._camera_command(backend, camera_index))
            except OSError as exc:
                errors.append(f"{backend}: {exc}")
                continue

            deadline = time.monotonic() + max(startup_check_sec, 0.2)
            while time.monotonic() < deadline:
                exit_code = process.poll()
                if exit_code is not None:
                    errors.append(f"{backend}: camera process exited with code {exit_code}")
                    break
                time.sleep(0.1)
            else:
                self._camera_process = process
                self._active_camera_index = camera_index
                if camera_index not in self._camera_indices:
                    self._camera_indices = [*self._camera_indices, camera_index][:3]
                self.get_logger().info(
                    f"Camera capture started: index={camera_index}, backend={backend}."
                )
                return True, f"Camera started on device {camera_index} ({backend})."

        detail = "; ".join(errors) or "No camera backend could open the device."
        self.get_logger().warning(
            f"Could not start camera index={camera_index}: {detail}"
        )
        return False, detail

    def _stop_camera(self):
        if not self._is_active():
            return True, "Camera capture is already stopped."

        process = self._camera_process
        if sys.platform == "win32":
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 and process.poll() is None:
                return False, result.stderr.strip() or "Could not stop camera process."
        else:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)

        self._camera_process = None
        self._active_camera_index = -1
        self.get_logger().info("Camera capture stopped.")
        return True, "Camera capture stopped."

    def _set_camera_enabled(self, request, response):
        if request.enabled:
            camera_index = int(request.camera_index)
            if camera_index < 0 or camera_index > 2:
                response.success = False
                response.message = "camera_index must be between 0 and 2."
            else:
                response.success, response.message = self._start_camera(camera_index)
        else:
            response.success, response.message = self._stop_camera()
        response.active = self._is_active()
        response.active_camera_index = self._active_camera_index if response.active else -1
        return response

    def destroy_node(self):
        self._stop_camera()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CubeCameraManagerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
