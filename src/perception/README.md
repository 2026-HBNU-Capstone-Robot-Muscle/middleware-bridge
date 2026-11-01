# 큐브 인식

`cube_detection` 패키지는 `/camera/image_raw` (`sensor_msgs/msg/Image`)를 받아
YOLO OBB 큐브 면 검출 결과를 `/cube/face_detections`
(`system_interfaces/msg/FaceDetectionArray`)로 발행합니다.

패키지 설치 시 `model/cube-detector.pt`가 패키지 공유 디렉토리로 설치되며,
기본 모델로 사용됩니다. 다른 가중치를 쓸 때는 `model_path` 매개변수로 경로를
지정할 수 있습니다. 카메라 토픽, 출력 토픽, confidence 임계값, 추론 장치도
ROS 매개변수로 설정합니다.

```powershell
pixi run build-windows
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.colcon-win\install\local_setup.ps1
ros2 run cube_detection cube_detector
```

이 패키지는 OBB 검출만 수행합니다. 색 분류, 6면 캡처, `CubeState` 조립은
구현되어 있지 않습니다.
