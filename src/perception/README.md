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

`cube_state_assembler`는 `/camera/image_raw`, `/cube/face_detections`,
`/cube/scan/face_label`을 같은 ROS timestamp로 짝지어 원근 보정과 3×3 색상
샘플링을 수행합니다. 6면 순서는 참조 파이프라인과 같이 `F, R, B, L, U, D`이고,
중심색 기준 Lab 분류·색상 개수·중심 스티커·Kociemba 상태 검증을 통과한 경우에만
`/cube/state`에 54자 URFDLB facelet을 발행하고 `/cube/solve`를 호출합니다.
검증 오류가 있으면 `valid=false`, 빈 `facelets`, `validation_errors`를 발행하며
풀이 요청을 보내지 않습니다.

먼저 한 번 빌드합니다.

```powershell
pixi run build-windows
```

PowerShell 창 1~3에서 프로젝트 루트로 이동한 뒤 각각 Pixi 환경과 ROS overlay를
불러오고 노드를 실행합니다.

```powershell
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
ros2 run cube_solver cube_solver
```

창 2에서는 마지막 명령을 `ros2 run cube_detection cube_detector`로, 창 3에서는
`ros2 run cube_detection cube_state_assembler`로 바꿉니다. 창 4에서 같은 방식으로
환경을 불러온 뒤 참조 이미지 재생기를 실행합니다.

```powershell
ros2 run cube_detection cube_offline_replay --ros-args `
  -p capture_root:="C:/Users/jeonj/Desktop/middleware/cube_3D_conversion/captures"
```

재생기는 참조 디렉토리를 읽기만 하며, 시작 후 5초 대기하고
`F/R/B/L/U/D/original.png`를 3초 간격으로 두 차례 ROS 이미지 및 면 라벨 토픽에
발행합니다. 면별 첫 입력이 유실되거나 검출되지 않아도 다음 입력에서 재시도합니다.
실제 카메라 입력에서도 assembler가
동작하려면 스캔 절차가 각 이미지와 같은 timestamp를 가진
`FaceCaptureLabel`을 발행해야 합니다. assembler는 12초 동안 추가 면 입력이 없고
6면을 채우지 못하면 불완전 상태를 오류와 함께 발행합니다. 카메라와 실제 큐브는
이 검증에 포함되지 않습니다.
