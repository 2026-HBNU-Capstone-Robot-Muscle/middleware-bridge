# middleware-bridge

Windows 기반 ROS 2 Humble 미들웨어 프로젝트입니다. 카메라로 큐브 면을 수집해 URFDLB 상태를 만들고 Kociemba 풀이를 생성한 뒤, ROS 2 action으로 LEAP Hand와 Custom Hand의 동작 순서를 실행하는 구조입니다. GUI의 두 손 큐브 풀이 경로는 dry-run입니다. 좌수 Custom Hand는 별도로 실기 모드를 켜면 ROS 2 action으로 파지·회전·해제를 실행할 수 있습니다.

## 실행 방법

#### 실행환경 준비
> `install.bat`을 실행하여 실행에 필요한 패키지를 설치합니다
> 설치 목록
> - Pixi
> - Rust/Tauri CLI
> - Visual Studio C++ Build Tools
> - WebViews2 Runtime

```powershell
./install.bat
```

#### 프로그램 실행
> 기존 4개의 창을 활성화해야 한 것을 하나의 실행파일로 축소

```powershell
./start.bat
```

#### 프로그램 정지
> 프로그램을 정지하지 않을 경우 컴퓨터 전원을 껐다 켜지 않는 이상 위의 스크립트가 작동되지 않음

```powershell
./stop.bat
```

## 처리 흐름

```text
카메라 이미지
  → YOLO 큐브 면 검출 및 6면 색상 수집
  → URFDLB 54자 facelet 검증
  → /cube/solve (Kociemba)
  → /cube/solution + JSON 저장
  → 명시적 /cube/execute_solution 요청
  → LEAP 정렬·지지
  → Custom Hand 파지·레이어 회전·해제
```

`cube_sequence_executor`는 풀이 토큰을 네 hand primitive로 전개하고 ROS 2 action으로 순서대로 전달합니다. 고정된 사전학습 정책은 요청 시 shadow 추론에 사용할 수 있습니다. 현재 실행은 센서로 상태를 추정하거나 모터를 구동하지 않으며, 정책 action을 계획 상태로 반영하는 부분도 open-loop dry-run 가정입니다.

## 저장소 구성

| 경로 | 역할 |
|---|---|
| `src/perception/cube_detection` | YOLO OBB 검출, 카메라 캡처, 색 분류와 큐브 상태 검증 |
| `src/planning/cube_solver` | `/cube/solve` Kociemba 풀이 서비스 |
| `src/control/cube_execution` | 풀이 실행 action, workflow 전개, 방향 순열 trace, calibration gate |
| `src/control/leap_hand_control` | LEAP 정책 추론기와 hand primitive dry-run action server |
| `src/control/custom_hand_control` | Custom Hand shadow 정책 추론기와 dry-run·좌수 실기 겸용 primitive action server |
| `src/policy/rl_policy` | 정책 관련 ROS 패키지 |
| `src/system_bringup` | 정책 입력 bridge 및 통합 실행 구성 |
| `src/system_interfaces` | 프로젝트 ROS 메시지·서비스·action 정의 |
| `apps/monitoring_ui` | 큐브 풀이 3D 시뮬레이션·ROS 상태 모니터링 및 dry-run 제어용 Tauri UI |
| `scripts` | Windows 원클릭 GUI dry-run 실행기, rosbridge 도우미 및 풀이 검사 도구 |
| `results/cube_solutions` | 카메라 인식에서 생성한 풀이 JSON |
| `docs` | 설치, 아키텍처, ROS 계약 및 개발 기록 |

## 개발 환경 준비

이 저장소는 `pixi.toml`에서 Windows `win-64`와 ROS 2 Humble 환경을 관리합니다. 설치·환경 진단 절차는 [Windows ROS 2 설치 안내](docs/ros2_install_guideline.md)를 참고하세요.

새 Windows PC에서는 저장소를 내려받은 뒤 루트의 `install.bat`을 실행하면 Pixi 환경, Rust/Tauri 도구, 필요한 Windows 빌드 구성 요소 설치를 확인하고 ROS 패키지 빌드와 정적 GUI 준비까지 진행합니다. 네트워크 연결이 필요하고 Visual Studio C++ Build Tools 설치 과정에서 관리자 승인 창이 표시될 수 있습니다. 설치가 끝나면 `start.bat`으로 GUI를 실행합니다.

```powershell
.\install.bat
```

빌드 후 ROS 명령을 사용하는 각 PowerShell 창에서 환경을 준비합니다.

```powershell
pixi shell
. .\.colcon-win\install\local_setup.ps1
```

저장소 경로에는 한글이나 공백을 포함하지 마세요. 노트북에서는 영문·숫자·하이픈만 사용하는 경로에 저장소를 새로 복제한 뒤 설치해야 합니다.

ROS 2 도구가 인식되지 않으면 해당 PowerShell에서 overlay가 적용됐는지 확인합니다. 카메라 검증 명령과 키 입력은 [인식 README](src/perception/README.md)에 있습니다.

## 주요 ROS 인터페이스

| 인터페이스 | 역할 |
|---|---|
| `/cube/solve` — `system_interfaces/srv/SolveCube` | URFDLB facelet 입력의 유효성을 검사하고 풀이 수열을 반환 |
| `/cube/solution` — `system_interfaces/msg/CubeSolution` | 인식된 큐브 상태와 풀이 수열 전달 |
| `/cube/list_cameras` — `system_interfaces/srv/ListCameras` | 인덱스 0~2에서 사용 가능한 카메라를 검색 |
| `/cube/set_camera_enabled` — `system_interfaces/srv/SetCameraEnabled` | GUI에서 선택한 카메라 인덱스의 캡처 노드 시작·중지 |
| `/cube/camera_active` — `std_msgs/msg/Bool` | 카메라 캡처 활성 상태 전달 |
| `/cube/execute_solution` — `system_interfaces/action/ExecuteCubeSolution` | 저장된 풀이를 두 손 primitive workflow로 dry-run 실행 |
| `/cube/execution_status` — `system_interfaces/msg/CubeExecutionStatus` | 실행 단계·완료·실패·취소 상태 발행 |
| `/leap_hand/execute_primitive` | LEAP 방향 정렬·지지 primitive action |
| `/custom_hand/execute_primitive` — `system_interfaces/action/ExecuteHandPrimitive` | Custom 파지·레이어 회전·해제 primitive action |
| `/policy/infer` — `system_interfaces/action/InferHandPolicy` | 고정된 사전학습 모델의 shadow 추론 요청 |

ROS 인터페이스와 workflow 설명은 [제어 README](src/control/README.md), solver 설명은 [planning README](src/planning/README.md)에 있습니다.

## 저장된 풀이 dry-run 확인

저장된 최신 JSON을 읽어 입력 형식과 `/cube/solve` 검증을 거친 뒤 두 손 action 경로를 dry-run 합니다. 구조 검사만 하려면 ROS 노드 없이 다음을 실행합니다.

```powershell
python scripts\ros2_dryrun_check.py --validate-only
```

success·missing·cancel action 모드에는 `cube_solver`, `cube_sequence_executor`, `leap_hand_primitive_server`, `custom_hand_primitive_server`가 각각 실행 중이어야 합니다.

```powershell
python scripts\ros2_dryrun_check.py --mode success
python scripts\ros2_dryrun_check.py --mode missing
python scripts\ros2_dryrun_check.py --mode cancel
```

현재 저장된 카메라 풀이로 정상 완료 20 moves·80 steps, 없는 `scan_id` 거부, action 취소를 확인했습니다. 각 JSON은 `/cube/solution` 발행 전에 기존 solver 서비스로 facelet solvability를 검사합니다. 성공 결과는 코드 경로 검증이며 물리적 큐브 동작의 증거가 아닙니다. 상세 실행 순서와 기대 결과는 [제어 README](src/control/README.md)에 기록되어 있습니다.

## 구현 상태와 미완료 범위

**확인된 부분:** 카메라 facelet 수집·검증, Kociemba 풀이와 JSON 저장, ROS 2 토픽·서비스·action 연결, 저장 풀이 dry-run, 고정 모델 shadow 추론 및 방향 순열 계획 trace, 저장 JSON 구조·물리 상태 사전 검증.

**미완료:** LEAP Hand 실기 제어, 실제 큐브 pose·좌표계 입력, 두 손 협동 실행의 완료 판정과 오류 복구. 좌수 단독 실기는 아래 방법으로 확인할 수 있습니다.

실기 코드에서 찾은 포트·모터·제어 설정은 [하드웨어 설정표](docs/hardware-setting.md)에, 실물 전 남은 입력·보정·안전 항목은 [미완료 목록](docs/incomplete.md)에 기록했습니다.

Tauri 큐브 조작 GUI는 기본 `ws://127.0.0.1:9090` rosbridge에 연결해 풀이와 실행 피드백을 표시합니다. 실행 모드는 dry-run이 기본이며 `/cube/real_mode_ready` 준비 신호가 없으면 실물 모드 전환이 잠깁니다. GUI 실행 방법은 [모니터링 UI README](apps/monitoring_ui/README.md)를 참고하세요.


## 좌수 Custom Hand 단독 실기 시험

`install.bat`으로 빌드한 뒤, 저장소 루트에서 서버와 요청용 PowerShell 창을 각각 준비합니다. 두 창에서 `pixi shell`을 먼저 실행한 다음 overlay를 적용합니다. GUI가 실행 중이면 `stop.bat`으로 종료하고, 좌수 CLI가 열려 있으면 종료해 COM8과 action을 한 서버만 사용하게 합니다.

```powershell
pixi shell
. .\.colcon-win\install\local_setup.ps1
```

서버 창에서 실기 제어를 켭니다.

```powershell
ros2 run custom_hand_control custom_hand_primitive_server --ros-args -p hardware_enabled:=true -p allow_provisional:=true
```

서버는 패키지에 설치된 `config/config.provisional.json`과 `config/primitive_calibration.local.json`을 읽습니다. 기본 연결은 COM8, 1 Mbps, 손가락 ID 1~4, 손목 ID 10입니다. 다른 설정 파일은 `hardware_config`와 `wrist_calibration`에 절대 경로를 지정합니다. `allow_provisional:=true`는 `verified=false`로 기록된 시험 보정값을 명시적으로 허용합니다.

요청 창에서 아래 명령을 한 줄씩 실행합니다. 파지와 회전의 결과가 각각 `SUCCEEDED`이고 `success: true`인 것을 확인한 뒤 다음 명령을 보냅니다. 각 시험은 새 실행 ID를 만들고, 같은 시험의 세 요청은 ID를 공유합니다.

```powershell
$execution = 'left-test-' + [guid]::NewGuid().ToString('N')
$goal = "scan_id: bench, execution_id: $execution, move_index: 1, cube_move: U, target_face: U, face_direction_order: URFDLB, target_face_direction_index: 0, dry_run: false"
ros2 action send_goal /custom_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive "{$goal, step_index: 1, primitive_id: grasp_upper_layer, clockwise_quarter_turns: 0}" --feedback
ros2 action send_goal /custom_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive "{$goal, step_index: 2, primitive_id: rotate_upper_layer, clockwise_quarter_turns: 1}" --feedback
ros2 action send_goal /custom_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive "{$goal, step_index: 3, primitive_id: release_upper_layer, clockwise_quarter_turns: 0}" --feedback
```

회전 요청 값은 시계 방향 `1`, 반시계 방향 `-1`, 반 바퀴 `2`입니다. 반시계 방향이나 반 바퀴를 시험할 때는 `cube_move`도 각각 `"U'"` 또는 `U2`로 맞춥니다. 파지 결과를 반환한 뒤에도 Worker가 PPO 제어를 유지합니다. 파지와 회전의 성공 판정은 모터 피드백을 기준으로 하므로 큐브를 실제로 잡았는지와 회전이 완료됐는지는 실물을 보고 확인합니다.

실기에는 `finger_robot_ppo_hardware.zip`을 사용하며 설정의 SHA-256과 대조합니다. 기존 `finger_robot_ppo_best.zip`은 shadow 추론에 사용합니다. 실기 서버를 종료할 때는 서버 창에서 `Ctrl+C`를 누릅니다. 자동 수집 로그는 `ROS_LOG_DIR/custom_hand_control` 또는 기본 `~/.ros/log/custom_hand_control`에서 확인합니다.
