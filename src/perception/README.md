# 큐브 인식

`cube_detection` 패키지는 `/camera/image_raw` (`sensor_msgs/msg/Image`)를 받아
YOLO OBB 큐브 면 검출 결과를 `/cube/face_detections`
(`system_interfaces/msg/FaceDetectionArray`)로 발행합니다.

패키지 설치 시 `model/cube-detector.pt`가 패키지 공유 디렉토리로 설치되며,
기본 모델로 사용됩니다. 다른 가중치를 쓸 때는 `model_path` 매개변수로 경로를
지정할 수 있습니다. 카메라 토픽, 출력 토픽, confidence 임계값, 추론 장치도
ROS 매개변수로 설정합니다.

## YOLO 검출기 단독 확인 (진단용)

아래 명령은 YOLO 노드만 따로 확인할 때 사용합니다. 실시간 카메라 실험에서는 아래
3개 명령을 별도 실행하지 말고, 뒤의 `카메라 검증 절차`에 나온 3개 셸 구성을 따릅니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi run build-windows
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
ros2 run cube_detection cube_detector
```

실시간 카메라 경로에서는 `cube_camera_capture`가 촬영 순서, YOLO 결과와 timestamp
매칭, 색상 수집, 큐브 상태 검증, solver 호출을 한 노드에서 관리합니다. YOLO 추론은
별도 `cube_detector`가 담당합니다. 카메라 노드는 미리보기 프레임을 기본 5 FPS로
검출기에 보내고 반환된 OBB 꼭짓점·클래스·신뢰도를 카메라 창에 표시합니다. 수동 촬영
프레임도 같은 이미지 토픽으로 보내며, 해당 timestamp의 검출 결과로 색상을 샘플링합니다.
6면 순서는 `F, R, B, L, U, D`입니다.
풀이 성공 시 수열을 `/cube/solution` (`system_interfaces/msg/CubeSolution`)으로 발행하고
JSON 파일로 저장합니다. 기본 저장 위치는 프로젝트 루트의
`results/cube_solutions/`이며 `solution_json_dir` 매개변수로 변경할 수 있습니다.

`cube_state_assembler`는 분리된 수집 경로를 확인하는 오프라인 재생/진단용으로
유지합니다. 실제 카메라 검증에서는 실행하지 않습니다. 통합 노드는 중심색 기준 Lab
분류·색상 개수·중심 스티커·Kociemba 상태 검증을 통과한 경우에만 `/cube/state`에
54자 URFDLB facelet을 발행하고 `/cube/solve`를 호출합니다. 실패 시 `valid=false` 상태를
발행하며 풀이 요청은 보내지 않습니다.

최근접 중심색 분류 결과가 색상별 9개 규칙에 맞지 않으면, 중심 스티커를 제외한
스티커 중 Lab 거리 차이가 설정 한도 안인 경우에만 색상별 개수를 맞춰봅니다.
보정된 스티커 위치와 변경 색상은 카메라/수집 통합 노드의 경고 로그에 표시합니다.
한도를 넘거나 Kociemba 물리 검증에서 거부되면 상태를 유효하지 않게 처리합니다.
기본 Lab 거리 추가 한도는 20이며 `max_color_reassignment_delta` ROS 매개변수로
조정할 수 있습니다.

## 오프라인 재생·분리형 수집기 확인

다음 4개 노드 절차는 저장 이미지로 오프라인 재생을 하거나 `cube_state_assembler`를
독립 진단할 때만 사용합니다. 실제 카메라 실험에서는 이 분리형 수집기를 실행하지
않습니다.

먼저 한 번 빌드합니다.

```powershell
pixi run build-windows
```

PowerShell 창 네 개에서 프로젝트 루트로 이동한 뒤 각각 Pixi 환경과 ROS overlay를
불러옵니다. 창 1에는 solver, 창 2에는 YOLO detector, 창 3에는 `cube_state_assembler`,
창 4에는 아래 오프라인 재생 노드를 실행합니다.

```powershell
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
```

각 셸에서 아래 명령을 하나씩 실행합니다.

1. 창 1 — 풀이 서비스: `ros2 run cube_solver cube_solver`
2. 창 2 — YOLO 검출기: `ros2 run cube_detection cube_detector`
3. 창 3 — 분리형 큐브 상태 조립기: `ros2 run cube_detection cube_state_assembler`
4. 창 4 — 오프라인 재생기:

```powershell
ros2 run cube_detection cube_offline_replay --ros-args `
  -p capture_root:="C:/Users/jeonj/Desktop/middleware/cube_3D_conversion/captures"
```

재생기는 참조 디렉토리를 읽기만 하며, 시작 후 5초 대기하고
`F/R/B/L/U/D/original.png`를 3초 간격으로 두 차례 ROS 이미지 및 면 라벨 토픽에
발행합니다. 실제 카메라 입력은 아래 수동 캡처 절차를 사용합니다.

수동 스캔에서는 오프라인 상태 조립기와 카메라 통합 노드의 결과 대기 타임아웃이
비활성화되어 있습니다. 면 입력이 누락되면 결과를 임의로 확정하지 않고 추가 입력을
기다립니다. 타임아웃 코드는 삭제하지 않고, 자동 인식으로 전환할 때 다시 켤 수 있도록 각 코드 위에
`# 자동 인식의 경우 주석 해제`를 적어 주석 처리했습니다.

## 카메라 검증 절차

먼저 카메라를 연결하고 프로젝트 루트에서 최신 변경을 빌드합니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi run build-windows
```

PowerShell 창을 세 개 열고 **각 창에서** 프로젝트 루트로 이동해 Pixi 환경과 ROS
overlay를 불러옵니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
```

창 1~3에서 아래 노드를 순서대로 각각 실행합니다.

1. 창 1 — 풀이 서비스

   ```powershell
   ros2 run cube_solver cube_solver
   ```

2. 창 2 — YOLO 검출기

   ```powershell
   ros2 run cube_detection cube_detector
   ```

3. 창 3 — 카메라 캡처 및 큐브 상태 수집 통합 노드

   ```powershell
   ros2 run cube_detection cube_camera_capture --ros-args `
     -p camera_index:=0 `
     -p camera_backend:=dshow `
     -p width:=1280 `
     -p height:=720 `
     -p camera_fps:=30.0
   ```

풀이 토픽을 별도로 확인하려면 네 번째 PowerShell 창에서 같은 Pixi 환경과 ROS overlay를
불러온 뒤 아래 명령을 실행합니다. 카메라 노드가 실행 중이면 이미 풀이가 나온 뒤에도
최근 풀이 한 건을 받을 수 있도록 publisher가 transient-local QoS를 사용합니다.

```powershell
ros2 topic echo /cube/solution system_interfaces/msg/CubeSolution
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
2. 창 3 영상 위에 녹색 YOLO OBB 박스와 `side` 클래스·신뢰도가 표시되는지 확인합니다.
3. 여섯 번 촬영한 뒤 카메라 노드 로그에서 `Captured F`, `Captured R`, `Captured B`,
   `Captured L`, `Captured U`, `Captured D`가 모두 출력되는지 확인합니다.
4. 상태 검증 성공 시 카메라 노드 로그에 `Valid URFDLB cube state`와
   `Solver response`가 출력되는지 확인합니다. 이어서 `Published solution on /cube/solution`
   및 `Saved solution JSON` 로그를 확인합니다.
5. JSON이 기본 경로 `results/cube_solutions/`에 생성되는지 확인합니다. 파일에는
   `scan_id`, UTC 생성 시각, 54자 `facelets`, 풀이 `moves`, `move_count`가 들어갑니다.

   ```powershell
   Get-ChildItem .\results\cube_solutions\cube_solution_*.json |
     Sort-Object LastWriteTime -Descending |
     Select-Object -First 1 FullName, LastWriteTime
   ```

6. 선택적으로 네 번째 토픽 확인 셸에서 같은 `scan_id`와 이동 수열이 발행되는지
   확인합니다. ROS 메시지에는 `header`, `scan_id`, `facelets`, `moves`가 포함됩니다.
7. 검증 오류가 있으면 `Cube state rejected` 뒤에 표시되는 원인을 확인합니다.

색상 개수 보정이 적용되면 카메라 노드 로그에
`Balanced near-boundary color assignments`와
스티커별 변경 내역이 경고로 표시됩니다. 보정만으로 유효한 큐브임을 보장하지 않으며,
중심 스티커와 Kociemba 물리 상태 검증을 모두 통과해야 풀이를 요청합니다.

검출 결과가 오지 않거나 상태 검증에 실패하면 카메라 미리보기에서 `R`을 눌러
6면을 처음부터 다시 촬영합니다. 촬영 중에도 `R`로 현재 세션을 취소하고 재시작할
수 있습니다. 통합 카메라 노드가 자체적으로 수집 상태를 초기화하므로 별도 assembler를
재시작할 필요가 없습니다. `scan_id`는 발행되는 상태 메시지의 세션을 식별합니다.

면 검출 결과가 오지 않으면 카메라 창은 타임아웃 없이 기다립니다. `R`을 눌러 전체
6면을 재촬영하거나 `Q`로 카메라 노드를 종료할 수 있습니다. solver와 detector는
계속 실행할 수 있습니다.

이 노드는 카메라 프레임에서 YOLO가 검출한 면을 사용합니다. 모델이 큐브의 의미상
면 방향을 자동으로 알아내는 것은 아니므로 `Space`를 누를 때의 면 라벨과 회전
순서를 따라야 합니다.

사용자 Windows 세션에서는 `camera_index=0`, `dshow`, 1280×720, 30 FPS 연결과 6면
캡처·상태 검증·풀이 수신이 확인됐습니다. 실행 로그에서 유효한 54자 URFDLB 상태와
20수 풀이 수열이 출력됐습니다. 결과 저장·발행 기능은 추가됐으며, JSON 파일과
`/cube/solution` 토픽의 실제 동작은 아직 검증되지 않았습니다. Q 종료 뒤
`Camera scan cancelled by operator`가
출력됐으며, 이어서 `QThreadStorage: entry ... destroyed before end of thread` 경고도
관찰됐습니다. 카메라 통합 및 YOLO 박스 미리보기 변경은 Windows에서 실행됐지만,
화면의 YOLO 박스 표시 여부는 아직 별도로 확인되지 않았습니다.
