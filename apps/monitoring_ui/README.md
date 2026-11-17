# 큐브 조작 스테이션

`monitoring_ui`는 rosbridge WebSocket을 통해 큐브 풀이를 표시하고 `/cube/execute_solution`을 dry-run으로 요청하는 Tauri 데스크톱 GUI입니다. 기존의 임의 토픽 발행·정수 덧셈 진단 화면을 프로젝트의 실제 ROS 인터페이스 중심으로 바꿨습니다.

## 화면 기능

- rosbridge 주소, 연결 상태, 메시지 송수신 수와 마지막 신호 시각을 표시합니다.
- `/cube/solution` (`system_interfaces/msg/CubeSolution`)을 구독해 scan ID, URFDLB facelets와 풀이 토큰을 보여줍니다.
- `cube_3D_conversion`의 facelet 순서와 회전 규약을 참고한 로컬 3D 큐브 시뮬레이션을 표시합니다. 외부 Three.js CDN 없이 Canvas에서 렌더링하며, 큐브를 드래그해 시점을 바꿀 수 있습니다.
- 풀이 미리보기 토글은 기본 해제입니다. 해제 상태에서는 ROS 실행 피드백에 맞춰 완료된 이동을 갱신합니다. 켜면 화면 안에서만 이동당 고정 0.8초로 재생하며 ROS 액션을 전송하지 않습니다.
- `/cube/execution_status` (`system_interfaces/msg/CubeExecutionStatus`)의 현재 이동, 단계, 손, primitive, 오류 및 완료 상태를 표시합니다.
- 사용자가 `DRY-RUN 실행`을 누르면 `/cube/execute_solution` (`system_interfaces/action/ExecuteCubeSolution`)에 `dry_run: true`, `run_pretrained_policies: false`를 전송합니다. GUI에는 실물 구동 모드가 없습니다.
- 연결, 풀이 수신, 액션 요청·피드백·결과와 브릿지 오류를 이벤트 기록에 남깁니다.

3D 표시는 URFDLB 논리 면 라벨을 기준으로 합니다. 카메라 원본 색상이나 실물 큐브의 3D pose를 뜻하지 않습니다. 기본 동기화 모드에서도 GUI는 ROS 진행 피드백에 맞춰 **계획된 큐브 상태**를 갱신합니다. 현재 hand adapter는 dry-run이므로 실물 동작과 동기화되는 것은 아닙니다.

현재 workflow 피드백에는 `orient_face_up_and_support`, `grasp_upper_layer`, `rotate_upper_layer`, `release_upper_layer`가 표시됩니다. GUI는 hand 역할과 primitive 순서를 자체 추정하지 않고 ROS 상태 메시지 값을 사용합니다.

## 데스크톱 앱으로 실행

### 1. 정적 GUI 빌드

저장소 루트(`middleware-bridge`) PowerShell에서:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\apps\monitoring_ui\scripts\build.ps1
```

정적 GUI는 `apps/monitoring_ui/dist`에 생성됩니다. 스크립트는 Node.js나 npm을 요구하지 않습니다. 이번 변경에서는 ROS 패키지를 수정하지 않았으므로 기존 `.colcon-win/install`이 준비되어 있다면 `pixi run build-windows`는 다시 실행할 필요가 없습니다. ROS 패키지를 아직 빌드하지 않은 새 환경에서는 먼저 `pixi run build-windows`를 실행합니다.

### 2. 원클릭 dry-run 실행

저장소 루트의 `start.bat`을 더블클릭합니다. 실행기는 한 개의 PowerShell 창에서 다음 준비를 순서대로 처리합니다.

1. 정적 GUI 파일 생성
2. `.colcon-win/install/local_setup.ps1` ROS overlay를 적용해 rosbridge를 시작하고 `127.0.0.1:9090` 준비 확인
3. `/cube/solve` 서비스와 YOLO detector 시작
4. LEAP Hand, Custom Hand, 큐브 실행 dry-run 서버 시작
5. 카메라 관리 노드를 시작하고 GUI 버튼 요청을 기다림
6. Tauri 데스크톱 GUI 실행

GUI가 열리면 rosbridge에 자동 연결됩니다. 실행 서버는 요청을 검증하고 응답만 하며 모터 명령은 보내지 않습니다. 실행기 로그는 저장소의 `logs\gui-dryrun`에 기록됩니다. 종료할 때는 저장소 루트의 `stop.bat`을 더블클릭하세요. 실행기가 시작한 프로세스 트리만 정리합니다.

한 번 실행하려면 perception을 포함한 ROS 패키지가 `.colcon-win\install`에 빌드되어 있어야 합니다. Pixi, Rust/Cargo, Tauri CLI가 준비되어 있고 `9090` 포트가 비어 있어야 합니다. ROS 패키지를 새로 빌드해야 하는 경우 저장소 루트에서 먼저 `pixi run build-windows`를 실행하세요. Cargo가 사용자 PATH에 없더라도 실행기는 `%USERPROFILE%\.cargo\bin\cargo.exe`를 찾아 사용합니다.

원클릭 실행에는 perception의 solver, YOLO detector, 카메라 관리 노드가 포함됩니다. GUI의 `카메라 시작` 버튼을 누르면 캡처 노드가 별도 카메라 창으로 열리고, `Space`로 면을 촬영해 풀이 JSON을 저장하고 `/cube/solution`을 발행합니다. `카메라 중지` 버튼은 캡처 노드를 종료합니다. 기본 backend `dshow`가 카메라를 열지 못하면 `msmf`, `any` 순서로 자동 재시도합니다. 카메라 장치 번호나 시작 backend가 다른 경우 다음처럼 실행 매개변수를 바꿀 수 있습니다.

```powershell
.\start.bat -CameraIndex 1 -CameraBackend msmf
```

수동으로 실행해야 하는 경우에는 저장소 루트에서 rosbridge, solver, detector, 카메라 및 세 dry-run 서버를 각각 시작한 뒤 `apps\monitoring_ui\src-tauri`에서 `cargo tauri dev`를 실행하면 됩니다. GUI는 기본 `ws://127.0.0.1:9090`에 자동 연결합니다.

## dry-run 화면 확인

1. 원클릭 실행 후 GUI 상단이 `연결됨`으로 표시되는지 확인합니다. `/cube/solution`, `/cube/execution_status` 카드가 구독 상태를 표시합니다.
2. `카메라 시작`을 눌러 카메라 창을 열고 큐브를 스캔합니다. 인식 결과의 `scan_id`, facelets, 이동 토큰과 3D 큐브가 표시됩니다. 카메라 상태는 GUI에 반영되며 버튼으로 캡처 노드를 중지할 수 있습니다.
3. 기본 토글 상태에서는 ROS 실행 상태가 들어올 때 진행 상황을 표시합니다. `풀이 미리보기`를 켜면 GUI 애니메이션만 고정 속도로 재생됩니다. 이 토글은 ROS 액션을 보내지 않습니다.
4. 실험용으로 실제 dry-run 액션을 보내려면 미리보기 토글을 끄고 `DRY-RUN 실행`을 누릅니다. 진행 단계와 이벤트 기록을 확인합니다. 액션 완료 시 성공 상태와 완료 이동 수가 표시됩니다.
5. 실행 중에는 `실행 취소`를 눌러 취소 요청을 확인할 수 있습니다.

카메라 없이 GUI 경로만 확인할 때는 연결 후 별도 ROS 셸에서 최근 저장된 풀이 JSON을 `/cube/solution`으로 발행할 수 있습니다. 프로젝트 루트의 PowerShell에서 예를 들면:

```powershell
$solutionFile = Get-ChildItem .\results\cube_solutions\cube_solution_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$solution = Get-Content $solutionFile.FullName -Raw | ConvertFrom-Json
$moves = ($solution.moves | ForEach-Object { '"' + $_ + '"' }) -join ', '
$yaml = "{scan_id: $($solution.scan_id), facelets: '$($solution.facelets)', moves: [$moves]}"
ros2 topic pub --qos-durability transient_local --qos-reliability reliable --once /cube/solution system_interfaces/msg/CubeSolution $yaml
```

이 명령은 GUI 표시와 dry-run workflow 확인용입니다. 저장 JSON의 풀이가 현재 실제 큐브 상태와 일치하는지는 별도 확인 대상입니다.

## 제한 사항

- GUI의 dry-run 표시와 액션 요청은 고정이며 실물 동작 모드로 전환할 수 없습니다.
- 실제 hand adapter, 모터, Feetech 손목, 카메라의 3D pose 및 물리 좌표계는 이 UI에서 제어하거나 표시하지 않습니다.
- ROS 상태 피드백은 계획된 workflow 진행을 뜻합니다. 현재 dry-run 결과를 실물 동작 완료로 해석하면 안 됩니다.
- 3D 시뮬레이션의 면별 표시색은 URFDLB 라벨을 구별하기 위한 시각화 색이며 인식된 실물 스티커 색상은 아닙니다.
