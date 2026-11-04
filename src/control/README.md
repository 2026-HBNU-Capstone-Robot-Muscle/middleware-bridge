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
- 첫 runtime dry-run에서 executor가 `asyncio.sleep()`을 호출하며 `no running event loop`로 실패했습니다. executor는 ROS future를 직접 기다리고 ROS timer로 취소를 전달하도록 수정했으며, 네 패키지를 다시 빌드했습니다. 수정 후 runtime 재확인은 아직 완료되지 않았습니다.
- 아래 절차는 `/cube/solution`부터 `/cube/execute_solution` 및 두 손 액션 서버까지 이어지는 runtime dry-run 확인 방법입니다. 액션 결과의 성공과 12단계 완료가 확인되기 전에는 runtime 연동 완료로 간주하지 않습니다.

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

아직 카메라와 pose 입력이 정해지지 않았고, 논리 면 `URFDLB`와 로봇 좌표계의 변환, 실제 조립 상태에 따른 관절·모터 매핑, 모델 입력으로 들어갈 pose, 손목 목표각·회전 부호, primitive 완료 판정과 handoff 안전 조건이 확정되지 않았습니다. 따라서 현재 `target_face`와 회전량은 논리적 계약 값이며 실제 모터 명령으로 변환되지 않습니다. 이 정보와 안전한 정지·실패 복구 절차를 확정하고 각 adapter에 연결하기 전까지 실제 구동을 활성화하지 않습니다.
