# 큐브 인식

`cube_detection` 패키지는 `/camera/image_raw` (`sensor_msgs/msg/Image`)를 받아
YOLO OBB 큐브 면 검출 결과를 `/cube/face_detections`
(`system_interfaces/msg/FaceDetectionArray`)로 발행합니다.

패키지 설치 시 `model/cube-detector.pt`가 패키지 공유 디렉토리로 설치되며,
기본 모델로 사용됩니다. 다른 가중치를 쓸 때는 `model_path` 매개변수로 경로를
지정할 수 있습니다. 카메라 토픽, 출력 토픽, confidence 임계값, 추론 장치도
ROS 매개변수로 설정합니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi run build-windows
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
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
발행합니다. 실제 카메라 입력은 아래 수동 캡처 절차를 사용합니다.

수동 스캔에서는 상태 조립기와 카메라의 결과 대기 타임아웃이 비활성화되어 있습니다.
면 입력이 누락되면 결과를 임의로 확정하지 않고 추가 입력을 기다립니다. 타임아웃
코드는 삭제하지 않고, 자동 인식으로 전환할 때 다시 켤 수 있도록 각 코드 위에
`# 자동 인식의 경우 주석 해제`를 적어 주석 처리했습니다.

## 카메라 검증 절차

먼저 카메라를 연결하고 프로젝트 루트에서 최신 변경을 빌드합니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi run build-windows
```

PowerShell 창을 네 개 열고 **각 창에서** 프로젝트 루트로 이동해 Pixi 환경과 ROS
overlay를 불러옵니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
```

창 1~4에서 아래 노드를 순서대로 각각 실행합니다.

1. 창 1 — 풀이 서비스

   ```powershell
   ros2 run cube_solver cube_solver
   ```

2. 창 2 — YOLO 검출기

   ```powershell
   ros2 run cube_detection cube_detector
   ```

3. 창 3 — 큐브 상태 조립기

   ```powershell
   ros2 run cube_detection cube_state_assembler
   ```

4. 창 4 — 카메라 캡처 노드

   ```powershell
   ros2 run cube_detection cube_camera_capture --ros-args `
     -p camera_index:=0 `
     -p camera_backend:=dshow `
     -p width:=1280 `
     -p height:=720 `
     -p camera_fps:=30.0
   ```

OpenCV 미리보기 창이 뜨면 시작 자세를 `F` 정면, `U` 위쪽, `R` 사용자 기준
오른쪽으로 맞춥니다. 각 면이 카메라를 향할 때 `Space`를 눌러 촬영합니다. 순서는
`F→R→B→L→U→D`입니다.

- `F`: 처음 정면에 보이는 면
- `R`, `B`, `L`: 큐브 전체를 왼쪽으로 90도씩 돌려 촬영
- `U`: 앞면 자세로 돌아온 뒤 큐브 전체를 아래로 90도 기울여 촬영
- `D`: `U` 촬영 자세에서 아래로 180도 더 돌려 촬영

개별 면을 따로 비틀지 말고 큐브 전체를 움직입니다. 각 면을 프레임 안에 온전히
넣고 흔들림이 적을 때 `Space`를 누릅니다. 이 순서를 지켜야 색상 배열 방향이
Kociemba solver 규칙에 맞습니다.

`camera_index`, `camera_backend` (`dshow`, `msmf`, `any`), `width`, `height`,
`camera_fps`는 카메라에 맞게 바꿀 수 있습니다. `camera_fps`는 ROS 매개변수 형식에
맞춰 `30.0`처럼 소수점으로 입력합니다. 노드는 실제 열린 해상도와 FPS를 로그에
출력합니다. 기본 장치 `0`이 열리지 않으면 `camera_index:=1` 또는
`camera_backend:=msmf`로 다시 실행합니다.

검증할 항목:

1. 카메라 창에 `Opened camera ... actual format=...`이 출력되는지 확인합니다.
2. 여섯 번 촬영한 뒤 카메라 창에 `All six labeled images published`가 나오는지
   확인합니다. 원본 발행에 더해 같은 timestamp의 이미지·라벨 쌍을 두 차례 재전송합니다.
3. 창 3에서 `Captured F`, `Captured R`, `Captured B`, `Captured L`, `Captured U`,
   `Captured D`가 모두 출력되는지 확인합니다.
4. 상태 검증 성공 시 창 3에 `Valid URFDLB cube state`와 `Solver response`가
   출력되는지, 카메라 창에 `Camera scan produced a valid cube state`가 출력되는지
   확인합니다.
5. 검증 오류가 있으면 창 3의 `Cube state rejected` 뒤에 표시되는 원인을 확인합니다.

면이 누락되어 결과 메시지가 오지 않으면 카메라 창은 타임아웃 없이 계속 대기합니다.
카메라 창에서 `Q`로 종료하고 창 3의 assembler에서 `Ctrl+C`를 누른 뒤 두 노드를
다시 시작해 전체 6면을 재촬영합니다. 상태가 `invalid`로 발행되면 카메라 노드는
결과를 표시한 뒤 종료하며, 이때도 assembler와 카메라 노드를 재시작해야 합니다.
solver와 detector는 계속 실행해도 됩니다.

이 노드는 카메라 프레임에서 YOLO가 검출한 면을 사용합니다. 모델이 큐브의 의미상
면 방향을 자동으로 알아내는 것은 아니므로 `Space`를 누를 때의 면 라벨과 회전
순서를 따라야 합니다.

사용자 Windows 세션에서 `camera_index=0`, `dshow`, 1280×720, 30 FPS 연결 및 6면 캡처를
확인했습니다. 첫 실시간 검증에서는 `F`가 조립되지 않아 실패했고, 카메라 캡처를
두 차례 재전송하도록 수정했습니다. 수정 후 재검증은 위 절차로 진행합니다.
