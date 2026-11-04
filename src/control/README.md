# 큐브 조작 제어

`cube_execution`은 `/cube/solution`을 받아 실행 요청을 기다리고, 명시적인 ROS 2 액션 목표를 받으면 Kociemba 풀이 토큰을 두 손의 추상 동작으로 전개합니다. `leap_hand_control`과 `custom_hand_control`은 각각 손 primitive 액션 서버를 제공합니다.

현재 구현은 **dry-run 전용**입니다. 액션 요청과 단계 전달은 검증하지만 LEAP Hand, Dynamixel, Feetech 모터나 학습 정책을 구동하지 않습니다.

## ROS 인터페이스

| 이름 | 타입 | 방향·역할 |
|---|---|---|
| `/cube/solution` | `system_interfaces/msg/CubeSolution` | 인식·풀이에서 실행 노드로 상태와 `moves`를 전달합니다. 실행 노드는 메시지를 검증·저장하지만 수신만으로 손을 움직이지 않습니다. |
| `/cube/execute_solution` | `system_interfaces/action/ExecuteCubeSolution` | `scan_id`, `workflow_id`, `dry_run`을 받아 특정 풀이의 실행을 명시적으로 시작·취소합니다. |
| `/cube/execution_status` | `system_interfaces/msg/CubeExecutionStatus` | 풀이 수신, 대기, 검증, handoff, primitive 진행, 완료·실패·취소를 발행합니다. |
| `/leap_hand/execute_primitive` | `system_interfaces/action/ExecuteHandPrimitive` | 하단 LEAP Hand의 방향 조정·지지 primitive 요청을 받습니다. |
| `/custom_hand/execute_primitive` | `system_interfaces/action/ExecuteHandPrimitive` | 상단 Custom Hand의 파지·레이어 회전·해제 primitive 요청을 받습니다. |

`ExecuteHandPrimitive` 목표에는 `scan_id`, `execution_id`, 이동·단계 인덱스, 원래의 `cube_move`, 논리 좌표계의 `target_face`, `clockwise_quarter_turns`, `primitive_id`, `dry_run`이 포함됩니다. 회전 방향은 `target_face` 바깥에서 면을 바라볼 때 시계 방향을 양수로 표현합니다. 회전 primitive의 값은 `1`, `-1`, `2`이며 그 외 primitive는 `0`입니다.

## 풀이 토큰과 손 primitive 순서

현재 workflow ID는 `two_hand_layer_turn_v1`입니다. 각 Kociemba 이동은 다음 네 단계로 전개되고, 앞 단계가 성공한 뒤 다음 액션을 보냅니다.

1. `leap_hand`: `orient_face_up_and_support` — 조작 대상 면을 위로 맞추고 큐브를 아래에서 지지합니다.
2. `custom_hand`: `grasp_upper_layer` — 위쪽 손으로 레이어를 파지합니다.
3. `custom_hand`: `rotate_upper_layer` — 요청된 방향과 1/2 회전량으로 상단 레이어를 회전합니다.
4. `custom_hand`: `release_upper_layer` — 파지를 해제합니다.

예를 들어 `R'`는 `target_face=R`, `clockwise_quarter_turns=-1`로, `F2`는 `target_face=F`, `clockwise_quarter_turns=2`로 전달됩니다. 각 이동의 대상 면은 Kociemba 논리 `URFDLB` 좌표계 값입니다.

실행 노드는 한 번에 하나의 풀이 실행만 받습니다. 각 단계의 진행은 액션 feedback과 `/cube/execution_status`에 기록합니다. 손 어댑터가 실패하거나 연결되지 않으면 이후 단계를 중단합니다. 취소 요청은 현재 손 primitive에 전달하며 primitive 경계에서 상위 액션의 취소 결과를 반환합니다.

## 현재 확인된 범위

- Windows 격리 빌드에서 `system_interfaces`, `cube_execution`, `custom_hand_control`, `leap_hand_control` 네 패키지가 빌드됐습니다.
- `ExecuteHandPrimitive` 생성 인터페이스와 세 패키지 실행 항목을 `ros2 interface show`, `ros2 pkg executables`로 확인했습니다.
- 구현상 두 손 서버는 입력 필드를 검증하고 `dry_run=true` 요청에 성공 응답을 보냅니다. `dry_run=false`는 실행 노드와 손 어댑터가 거부합니다.
- 첫 runtime dry-run에서 발생한 `no running event loop` 문제를 수정하고 네 패키지를 다시 빌드했습니다.
- 사용자가 Windows에서 세 노드와 액션 클라이언트를 실행해 `/cube/solution` 입력부터 두 손 액션 응답까지 확인했습니다. 3개 이동의 결과는 `success: true`, `completed_moves: 3`, `completed_steps: 12`였습니다. 확인 범위는 dry-run이며 실제 모터 구동은 아닙니다.

빌드 중 `system_interfaces`에서 CMake deprecation 및 policy 경고가 출력될 수 있습니다. 이는 경고이며 빌드가 `Finished`로 끝나면 그 경고만으로 패키지 실패를 의미하지 않습니다. 빌드 결과의 `Summary`에서 실패 패키지가 없는지도 확인합니다.

## Windows 빌드

프로젝트 루트에서 전체 워크스페이스를 빌드합니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi run build-windows
```

빌드가 끝난 뒤 각 PowerShell 창에서 ROS overlay를 불러옵니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
```

## Dry-run 연동 확인

PowerShell 창 네 개를 사용합니다. 먼저 각 창에서 위의 Pixi 환경과 ROS overlay를 불러온 뒤 다음 노드를 각각 실행합니다.

1. 창 1 — 풀이 실행 노드

   ```powershell
   ros2 run cube_execution cube_sequence_executor
   ```

2. 창 2 — LEAP Hand primitive 서버

   ```powershell
   ros2 run leap_hand_control leap_hand_primitive_server
   ```

3. 창 3 — Custom Hand primitive 서버

   ```powershell
   ros2 run custom_hand_control custom_hand_primitive_server
   ```

4. 창 4 — 실행 요청. 아래 예시는 색상 수가 맞는 solved facelets와 세 개의 형식상 유효한 Kociemba 토큰을 보내 dry-run 단계 전달을 확인합니다. 예시 입력은 실제 큐브 풀이를 검증하는 용도가 아닙니다.

   ```powershell
   ros2 topic pub --once /cube/solution system_interfaces/msg/CubeSolution "{scan_id: dryrun-001, facelets: UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB, moves: [R, `"U'`", F2]}"
   ```

   메시지를 발행한 다음 같은 창에서 실행 액션을 보냅니다.

   ```powershell
   ros2 action send_goal /cube/execute_solution system_interfaces/action/ExecuteCubeSolution "{scan_id: dryrun-001, workflow_id: two_hand_layer_turn_v1, dry_run: true}" --feedback
   ```

세 이동이 모두 전달되면 액션 결과에서 `success: true`, `completed_moves: 3`, `completed_steps: 12`를 확인합니다. feedback에는 각 이동의 네 primitive와 handoff 상태가 표시됩니다. 결과는 ROS 액션 요청과 dry-run 응답을 확인한 것이며 실제 큐브가 움직였다는 뜻은 아닙니다.

상태 토픽은 별도 창에서 확인할 수 있습니다.

```powershell
ros2 topic echo /cube/execution_status
```

액션 인터페이스와 실행 항목은 다음 명령으로 확인합니다.

```powershell
ros2 interface show system_interfaces/action/ExecuteCubeSolution
ros2 interface show system_interfaces/action/ExecuteHandPrimitive
ros2 pkg executables cube_execution
ros2 pkg executables leap_hand_control
ros2 pkg executables custom_hand_control
```

## 실제 구동 연결 전 미확정 항목

LEAP Hand는 큐브 아래에서 지지·방향 조정을 하고, Custom Hand는 위에서 학습된 손가락 파지와 손목 회전을 담당하는 구조입니다. 사용자가 제공한 모터 정보는 Custom 손가락 Dynamixel XL330-M288-T, Custom 손목 Feetech STS3215, LEAP Hand Dynamixel XC330-M288-T입니다.

아직 카메라와 pose 입력이 정해지지 않았고, 논리 면 `URFDLB`와 로봇 좌표계의 변환, 실제 조립 상태에 따른 관절·모터 매핑, 모델 입력으로 들어갈 pose, 손목 목표각·회전 부호, primitive 완료 판정과 handoff 안전 조건이 확정되지 않았습니다. 따라서 현재 `target_face`와 회전량은 논리적 계약 값이며 실제 모터 명령으로 변환되지 않습니다.

## Calibration 설정 초안 및 구동 차단

`cube_execution/config/hardware_calibration.example.json`은 실제 calibration 데이터를 채우기 위한 JSON 형식 초안입니다. 현재 알려지지 않은 포트·속도·motor ID·frame 이름·모델 경로·검증 결과는 빈 문자열, `null`, 빈 목록 또는 `false`로 남겨 두었습니다. 이 파일은 예시이며 현재 장치와 모델의 실제 calibration을 포함하지 않습니다.

`cube_execution.calibration` 검증기는 다음 항목을 확인합니다.

- schema 버전과 문서 전체, pose, frame/transform, 손별 motor 그룹, 정책, 안전 항목의 명시적 `verified: true` 표시
- pose topic·type·frame·단위·quaternion 형식과 양수 pose age 한도
- 각 프레임 이름, motor model, port·양수 baud rate·중복 없는 motor ID 목록
- 각 motor ID와 1:1로 대응하는 joint mapping: 이름, ID, 방향(`-1` 또는 `1`), zero offset, 단위, 유효 범위
- LEAP/Custom 정책 경로의 실제 존재와 observation schema 확인 표시
- 비상정지, 정지 방식, joint/workspace 한계, 완료 feedback, handoff 안전 검증 표시

검증기는 JSON 기록의 형식과 필수 표시를 검사합니다. 장치에 실제 연결하거나 pose 측정, 모델 입출력, 안전 동작을 실험하는 기능은 아닙니다. `verified` 표시와 근거를 채우는 책임은 실제 측정·시험을 수행한 사용자에게 있습니다.

검증하려면 예시를 사용자 로컬 설정 위치에 복사한 뒤 checker를 실행합니다. 미완성 예시에서 오류 목록이 출력되는 것이 정상입니다.

```powershell
$calibrationPath = Join-Path $env:LOCALAPPDATA 'middleware-bridge\hardware_calibration.json'
New-Item -ItemType Directory -Force (Split-Path $calibrationPath) | Out-Null
Copy-Item .\src\control\cube_execution\config\hardware_calibration.example.json $calibrationPath
ros2 run cube_execution cube_calibration_check $calibrationPath
```

executor는 시작 시 `calibration_file` ROS 매개변수를 읽습니다. 기본값은 비어 있으므로 실제 실행 목표는 `CALIBRATION_INCOMPLETE`로 거부됩니다. 파일을 지정해 calibration 검증이 통과하더라도 motor driver와 실제 adapter 동작이 아직 구현되지 않았으므로 `dry_run=false`는 `EXECUTION_DISABLED`로 계속 거부됩니다. calibration 파일만으로 실제 구동이 활성화되지는 않습니다.

```powershell
ros2 run cube_execution cube_sequence_executor --ros-args -p "calibration_file:=$calibrationPath"
```

실제 구동은 카메라·pose provider와 calibration을 측정·검증하고, 장치별 driver, pose 기반 목표 변환, 완료 feedback, 검증된 정지·복구 동작을 adapter에 구현한 뒤에만 별도 작업으로 활성화할 수 있습니다.

## Pose·좌표계·안전 계약

이 절은 실제 센서나 하드웨어의 값이 아니라, 각 입력과 동작을 실제 구동에 연결하기 전에 충족해야 할 계약입니다. 미정인 프레임 이름, 오차 한도, 시간 한도, 모터 ID 및 목표값은 임의로 채우지 않습니다.

### 큐브 pose 입력 계약

현재 detector는 큐브 면의 OBB·클래스·신뢰도를 발행하지만, 이 정보만으로 로봇 기준 큐브의 6자유도 pose를 제공한다고 간주하지 않습니다. 현재 `/cube/pose` publisher와 pose 좌표 보정은 구현·검증되지 않았습니다.

실제 구동에 연결할 pose provider는 다음을 제공해야 합니다.

- timestamp가 포함된 큐브 중심 위치와 방향. ROS 표준형을 사용할 경우 `geometry_msgs/msg/PoseStamped`가 후보이며, 실제 topic과 type은 provider 선정 시 확정합니다.
- pose의 `header.frame_id`, 단위(m), 오른손 좌표계 여부, quaternion 성분 순서와 정규화 규칙.
- 로봇 기준 좌표계까지의 정적·동적 transform과 transform의 timestamp. 각 손의 base frame 및 큐브 grasp 기준 frame을 함께 정의합니다.
- pose 신뢰도 또는 유효/무효 상태, 갱신 주기와 허용 가능한 최대 데이터 age. 이 기준은 센서 성능과 실제 동작 속도를 측정한 뒤 정합니다.
- 큐브를 다시 잡거나 손 간 인계 후 pose를 재확인하는 방법. 검증되지 않은 pose 또는 transform 누락·시간 초과는 실행 거부 조건입니다.

Kociemba 논리 면은 `U, R, F, D, L, B`로 식별합니다. calibration은 각 논리 면의 outward normal을 pose provider의 큐브 frame에 대응시키고, 큐브 frame을 LEAP·Custom Hand 기준 frame에 연결해야 합니다. LEAP의 face-up 성공 판정에는 어느 face normal이 위를 향하는지 정의하며, 면 법선 주위의 회전 자유도를 허용할지 별도 명시합니다. OBB 검출만으로 면의 의미 라벨이나 방향을 추정하는 규칙은 추가 검증 전까지 두지 않습니다.

### 회전과 관절 매핑 계약

`clockwise_quarter_turns`의 논리 회전량은 대상 면 바깥에서 볼 때 `+1 = +90°`, `-1 = -90°`, `2 = 180°`입니다. 이는 solver 기준의 의미만 고정합니다. 실제 Feetech 목표각·부호·영점·회전축은 Custom Hand wrist frame과 큐브 frame 사이의 보정으로 결정해야 하며 현재 값은 없습니다.

하드웨어 calibration record는 적어도 다음 항목을 갖추고 각 항목의 검증 근거를 남겨야 합니다.

| 항목 | 기록할 값 | 구동 허가 조건 |
|---|---|---|
| 장치 연결 | Dynamixel/Feetech 모델, 통신 포트·속도, motor ID | 실제 조립된 장치에서 ID 중복·통신 오류가 없음을 읽기 전용 확인 |
| 관절 대응 | ROS joint 이름 ↔ motor ID, 관절 순서, 부호, 영점, 단위, 허용 범위 | 관절별 방향·영점·범위를 저속 검증하고 기록 |
| 손 frame | LEAP base, Custom base, 손목 회전축, 큐브 grasp frame | 측정값·방향 정의 및 재현 가능한 calibration 절차 보유 |
| 학습 정책 | 모델 경로·식별값, observation 이름·순서·단위, action 범위·정규화 | 현재 학습 모델의 입출력이 실기 adapter 변환과 일치함을 검증 |
| 완료 판정 | 목표 대비 joint 상태, 큐브 pose 변화, grasp/support 상태의 기준 | 센서 feedback으로 성공·정지 조건을 구별할 수 있음 |

값마다 `verified`와 검증 기록을 남깁니다. 어떤 필수 항목이 미검증·누락·만료 상태이면 adapter는 실제 모드 목표를 거부해야 합니다. 참고용 학습 디렉토리에 있는 임시 motor mapping과 sign 값은 현재 조립에 대해 검증되지 않았으므로 calibration 값으로 복사하지 않습니다.

### Primitive 순서와 handoff 조건

현재 네 primitive 순서는 dry-run orchestration 계약입니다. 실제 동작에서 각 primitive의 성공 응답은 명령 전송만으로 반환하면 안 되며, 해당 동작의 완료 sensor feedback을 확인해야 합니다.

| 단계 | 성공으로 볼 조건 | 다음 단계 허용 조건 |
|---|---|---|
| LEAP `orient_face_up_and_support` | 목표 면 방향 오차가 검증된 허용범위에 들어오고 큐브 지지가 확인됨 | pose·지지 상태가 유효하고 Custom 파지 영역이 안전함 |
| Custom `grasp_upper_layer` | 손가락 상태와 grasp 확인 기준이 충족됨 | LEAP support 유지가 확인되고 wrist 회전 경로가 비어 있음 |
| Custom `rotate_upper_layer` | 목표 레이어 각도와 큐브 pose 변화가 검증된 범위에 도달함 | 회전 완료가 확인되며 LEAP가 큐브를 계속 지지함 |
| Custom `release_upper_layer` | 파지가 해제됐고 큐브가 LEAP에 안정적으로 남아 있음 | 다음 solver 이동 전에 pose 재측정·논리 상태 갱신 완료 |

목표 오차, 힘·전류, 속도, 정착 시간, timeout은 장치·센서 선택 뒤 실험으로 정합니다. 해당 값이 없으면 dry-run 이외의 동작을 허가하지 않습니다.

### 정지·실패·취소 조건

- pose 또는 transform 누락·오래된 값·유효성 실패, motor 통신/상태 이상, grasp/support 상실, 한계 초과, 완료 feedback 미수신 시 즉시 현재 실행을 중단하고 남은 primitive를 보내지 않습니다.
- adapter는 검증된 장치별 stop 동작을 수행하고, 실행 노드는 실패·취소 상태와 마지막으로 완료가 확인된 move/step을 발행합니다. 자동으로 손을 풀거나 큐브를 재배치하는 복구 동작은 현재 정의하지 않습니다.
- 현재 hardware API의 stop/hold 동작은 정해지지 않았습니다. 정지 명령이 실제로 어떤 자세를 유지하는지 검증하기 전까지 실패 시의 기계적 안전 상태를 보장한다고 간주하지 않습니다.
- 실패 뒤에는 operator 확인, 큐브 pose 재측정, 필요 시 새 `scan_id`로 재인식·재풀이를 거친 다음 별도 실행 목표를 받아야 합니다. 기존 action을 자동 재시도하거나 중단 지점부터 이어서 실행하지 않습니다.
- 비상정지 수단과 접근 위치, 토크·속도 제한, 작업 공간과 사람 접근 제한, 수동 회수 절차가 확인되지 않으면 실제 모터 구동을 시작하지 않습니다.

위 계약을 실제 값으로 채우기 위한 자료는 카메라/pose provider의 선택, 양 손과 손목의 실물 조립 frame·motor ID·통신값, 정책별 실기 observation/action 보정, 하드웨어 정지 방식입니다. 설정 파일과 형식 검증기는 준비됐지만 실제 calibration 기록, sensor freshness 검사, pose 기반 목표 변환, driver 및 adapter 완료 판정은 아직 구현되지 않았습니다.
