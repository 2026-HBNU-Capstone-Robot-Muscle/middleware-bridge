# 큐브 조작 제어

`cube_execution`은 `/cube/solution`을 받아 실행 요청을 기다리고, 명시적인 ROS 2 액션 목표를 받으면 Kociemba 풀이 토큰을 두 손의 추상 동작으로 전개합니다. `leap_hand_control`과 `custom_hand_control`은 각각 손 primitive 액션 서버를 제공합니다.

현재 primitive 동작은 **dry-run 전용**입니다. LEAP와 Custom 정책의 ROS shadow subscriber 및 추론 출력 토픽을 추가했지만, 실제 카메라 pose·모터 상태 publisher는 아직 없습니다. 추론 출력도 모터 driver로 연결되지 않으므로 학습 정책으로 손을 움직이지 않습니다.

## ROS 인터페이스

| 이름 | 타입 | 방향·역할 |
|---|---|---|
| `/cube/solution` | `system_interfaces/msg/CubeSolution` | 인식·풀이에서 실행 노드로 상태와 `moves`를 전달합니다. 실행 노드는 메시지를 검증·저장하지만 수신만으로 손을 움직이지 않습니다. |
| `/cube/execute_solution` | `system_interfaces/action/ExecuteCubeSolution` | `scan_id`, `workflow_id`, `dry_run`을 받아 특정 풀이의 실행을 명시적으로 시작·취소합니다. |
| `/cube/execution_status` | `system_interfaces/msg/CubeExecutionStatus` | 풀이 수신, 대기, 검증, handoff, primitive 진행, 완료·실패·취소를 발행합니다. |
| `/leap_hand/execute_primitive` | `system_interfaces/action/ExecuteHandPrimitive` | 하단 LEAP Hand의 방향 조정·지지 primitive 요청을 받습니다. |
| `/custom_hand/execute_primitive` | `system_interfaces/action/ExecuteHandPrimitive` | 상단 Custom Hand의 파지·레이어 회전·해제 primitive 요청을 받습니다. |
| `/leap_hand/policy_input` → `/leap_hand/policy_action` | `LeapPolicyInput` → `HandPolicyAction` | LEAP 센서 입력을 조립해 108→16 shadow 추론을 수행합니다. |
| `/custom_hand/policy_input` → `/custom_hand/policy_action` | `CustomPolicyInput` → `HandPolicyAction` | 보정된 Custom 상태에서 8→4 shadow 추론을 수행합니다. |
| `/cube/policy_goal` | `system_interfaces/msg/CubePolicyGoal` | 보정된 face-to-frame 변환기가 현재 move의 목표 quaternion을 제공합니다. |
| `/cube/pose`, `/leap_hand/palm_pose`, `/leap_hand/joint_states`, `/leap_hand/commanded_joint_states`, `/custom_hand/policy_joint_states` | 각각 `PoseStamped` 또는 `JointState` | 외부 pose·driver 입력입니다. `system_bringup/policy_input_bridge`가 workflow 상태와 최신 입력을 정책 입력으로 묶습니다. |

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

## LEAP 정책 소프트웨어 어댑터

`leap_hand_control`에는 참조 배포물과 같은 NumPy MLP 추론 형식을 읽는 `LeapPolicyAdapter`가 있습니다. LEAP 정책 `policy_np.npz`는 참조 디렉토리에서 middleware-bridge의 `src/control/leap_hand_control/models/policy_np.npz`로 복사했고, SHA-256은 `DC220D146BC5532C4AE09907C6D6BBC887335389D215AFAAFB69EEAB679560E7`입니다. Windows 빌드 설치 시 패키지 share의 `models` 아래에도 포함됩니다.

어댑터는 108개 관측값을 정규화한 뒤 은닉층 ReLU와 마지막 층의 첫 16개 출력에 `tanh`를 적용합니다. 이 규약은 `right_rl_with_mujoco/deploy/policy_np.py`의 추론 경로를 따릅니다. 동작 중 모터 API나 Dynamixel SDK를 불러오지 않습니다.

기본 LEAP primitive 서버를 실행하면 설치된 정책 파일을 열어 네트워크 모양과 가중치가 유효한지 확인합니다.

```powershell
ros2 run leap_hand_control leap_hand_primitive_server
```

primitive 서버 로그에 `LEAP 정책 파일 형식과 108→16 추론기를 준비했습니다`가 나타나면 모델 로딩까지 된 것입니다. 이것은 모델 추론 결과나 하드웨어 동작 검증은 아닙니다. 추론 shadow node는 `LeapPolicyInput` subscriber를 갖지만 카메라 pose와 LEAP joint state를 해당 계약으로 발행하는 upstream node는 없습니다. primitive 액션 목표에도 관측 데이터가 없습니다. 그래서 `dry_run=false` 요청은 정책이 로드되어도 `POSE_SOURCE_UNAVAILABLE`로 거부됩니다. 상위 `cube_sequence_executor`도 실제 구동을 계속 차단합니다.

예시 calibration JSON의 `policies.leap.model_path`에는 비워 둔 경로에 사용자의 로컬 절대 경로를 기록하고, `sha256`은 파일을 교체할 때만 실제 값에 맞춰 갱신합니다. 모델 파일을 읽을 수 있어도 `verified`와 `observation_schema_verified`는 실측·입출력 검증 전까지 `false`로 둡니다.

## 정책 ROS 입력 계약과 Shadow 추론

두 정책의 센서·상태 입력을 ROS 메시지로 명시하고, 계산 결과는 모터 드라이버가 아닌 `HandPolicyAction` 토픽으로 발행합니다. 두 출력 메시지는 `shadow_only: true`입니다.

| 토픽 | 입력 타입 | 의미 |
|---|---|---|
| `/leap_hand/policy_input` | `system_interfaces/msg/LeapPolicyInput` | timestamp가 있는 큐브 pose, LEAP palm pose, 16개 LEAP 관절 상태, 직전 명령 관절각, 목표 quaternion을 한 샘플로 전달합니다. |
| `/leap_hand/policy_action` | `system_interfaces/msg/HandPolicyAction` | LEAP 시뮬 관절 순서 16개에 대한 정규화 정책 출력입니다. 모터에 전달되지 않습니다. |
| `/custom_hand/policy_input` | `system_interfaces/msg/CustomPolicyInput` | Custom 정책 좌표계의 손가락 4개 위치와 속도를 전달합니다. 순서는 `right, front, left, back`입니다. |
| `/custom_hand/policy_action` | `system_interfaces/msg/HandPolicyAction` | 손가락 순서의 정규화 출력 4개입니다. 손가락 위치 변환이나 손목 Feetech 제어를 수행하지 않습니다. |

LEAP 입력의 `cube_pose`, `palm_pose`와 `leap_joint_state` timestamp는 모두 유효하고 최근 값이어야 합니다. 입력 생산자는 구성요소 측정값을 같은 샘플로 동기화해야 합니다. 두 pose의 `header.frame_id`는 설정한 `world_frame`과 같아야 하며 pose 위치 단위는 m, quaternion 순서는 ROS 표준 x,y,z,w입니다. `joint_state.name`은 참조 배포 코드의 16개 이름을 포함해야 하고 위치는 rad 단위입니다. `commanded_joint_positions`는 같은 순서의 직전 명령각(rad)이며 `goal_orientation`은 목표 cube quaternion입니다. 입력 조립기는 참조 순서로 관절을 재배열하고 108차원 관측의 이력을 구성합니다. 입력 bridge는 기본 100 ms freshness를 적용하고, 원본 LEAP runner의 pose 기준은 150 ms입니다. 목표 quaternion과 Kociemba 면 문자의 대응은 아직 보정·연결되지 않았으므로 이 입력의 생산자가 검증된 변환을 제공해야 합니다.

108개 값의 순서는 관절각 16, 관절오차 이력 48, 손바닥-큐브 위치오차 이력 9, cube 자세오차 이력 18, 직전 행동 16, 자세오차 scalar 1입니다. 이력은 최근 샘플부터 저장합니다.

```powershell
ros2 interface show system_interfaces/msg/LeapPolicyInput
ros2 interface show system_interfaces/msg/CustomPolicyInput
ros2 interface show system_interfaces/msg/HandPolicyAction
ros2 interface show system_interfaces/msg/CubePolicyGoal
ros2 run leap_hand_control leap_policy_shadow --ros-args -p world_frame:=YOUR_MEASURED_FRAME
ros2 run custom_hand_control custom_hand_policy_shadow
```

`YOUR_MEASURED_FRAME`은 카메라/로봇 보정으로 실제 확인한 공통 프레임 이름으로 바꿉니다. `system_bringup/policy_input_bridge`는 외부 source topics를 구독합니다. LEAP 실행 단계의 `CubeExecutionStatus`와 scan/execution ID, `CubePolicyGoal`, pose frame, 각 센서 timestamp를 확인한 다음 `/leap_hand/policy_input`을 발행합니다. 실행 상태와 목표 quaternion은 해당 primitive 동안 유지되는 문맥값으로 다룹니다. 새 pose·joint 샘플 묶음마다 한 번만 발행하고, 정책 입력 구독 큐는 최신 샘플 하나만 보관합니다. Custom 실행 단계에서도 상태와 ID가 유지되는 동안 새 `/custom_hand/policy_joint_states` 샘플당 한 번만 `/custom_hand/policy_input`을 발행합니다. `leap_source_joint_names`, `leap_command_joint_names`, `custom_source_joint_names` 매개변수의 순서는 실제 source name을 정책 관절·손가락 순서에 대응하도록 지정해야 합니다.

현재 middleware에는 실측 `/cube/pose`, palm pose, LEAP joint/command state, Custom policy-coordinate state 또는 `CubePolicyGoal` publisher가 없습니다. YOLO의 2D OBB를 3D pose로 바꾸는 변환도 구현하지 않았습니다. Dynamixel joint feedback은 보정된 관절각과 link geometry가 있을 때 손가락/손의 순기구학에 쓸 수 있지만, 그 값만으로 큐브의 절대 위치·자세를 정하지는 못합니다. 큐브 pose를 joint feedback에서 추정하려면 손·큐브 기준 frame, 접촉/파지 관계, slip 판정과 object-to-hand calibration이 추가로 검증돼야 합니다. 따라서 실제 정책 입력을 내기 위해서는 보정된 pose provider, 손바닥 pose와 motor-state publisher, 목표면 quaternion 변환기가 필요합니다. Custom 입력은 motor tick이 아니라 참고 `core.observation`의 calibration 이후 policy position·velocity 좌표여야 합니다. 미검증 mapping으로 값을 임의 변환하지 않습니다.

Custom 모델은 Stable-Baselines3 PPO actor의 8→64→64→4 구조를 CPU에서 weights-only로 읽습니다. 기본 Tanh 은닉층과 action-space `[-1,1]` clipping을 적용합니다. 정책 후보 파일은 middleware 내부에 복사했지만 참조 설정의 hash와 일치하지 않으므로, 이 shadow 추론 결과는 선택 checkpoint를 확정하거나 실기 동작을 입증하지 않습니다. 네 hand policy 출력 토픽 모두 실제 모터 구동과 분리되어 있습니다.

## 빠른 Shadow 경로 확인

카메라와 모터 없이 bridge와 양쪽 정책 추론 경로를 확인할 수 있습니다. 아래 합성 publisher는 프로젝트 입력 토픽에 데이터를 발행하므로 실제 카메라·하드웨어 driver·`cube_sequence_executor`와 동시에 실행하지 않습니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi run build-windows
```

PowerShell 창 네 개를 열고, 각 창에서 프로젝트 환경과 overlay를 불러옵니다.

```powershell
cd C:\Users\jeonj\Desktop\middleware\middleware-bridge
pixi shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.colcon-win\install\local_setup.ps1
```

각 창에서 하나씩 실행합니다.

1. 입력 bridge

   ```powershell
   ros2 run system_bringup policy_input_bridge --ros-args -p world_frame:=policy_demo_world
   ```

2. LEAP shadow 추론

   ```powershell
   ros2 run leap_hand_control leap_policy_shadow --ros-args -p world_frame:=policy_demo_world
   ```

3. Custom shadow 추론

   ```powershell
   ros2 run custom_hand_control custom_hand_policy_shadow
   ```

4. 합성 입력 publisher

   ```powershell
   ros2 run system_bringup policy_input_demo_publisher --ros-args -p world_frame:=policy_demo_world
   ```

4번 창에 `leap_hand: shadow_only=True, elements=16`과 `custom_hand: shadow_only=True, elements=4`가 출력되면 양쪽 정책 출력이 발행된 것입니다. 출력 숫자는 모터로 전달되지 않습니다. 입력 속도와 중복 발행 여부는 별도 창에서 `ros2 topic hz /leap_hand/policy_input` 및 `ros2 topic hz /custom_hand/policy_input`으로 확인할 수 있습니다. 데모는 각 입력을 약 20 Hz로 발행합니다. 토픽 내용은 `ros2 topic echo /leap_hand/policy_action`, `ros2 topic echo /custom_hand/policy_action`으로 확인합니다. 합성 publisher는 `Ctrl+C`로 종료합니다.

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

아래는 참고 디렉토리와 현재 코드에서 파일·설정으로 확인한 내용입니다. 참고 설정에서 가져온 후보 값은 현재 조립 장치의 calibration으로 간주하지 않으며 검증 전까지 `verified: false`로 둡니다.

| 대상 | 확인된 자료 | 현재 판정 |
|---|---|---|
| Windows 카메라 | 이전 실험에서 `camera_index=0`, `dshow`, 1280×720, 30 FPS로 영상 취득과 여섯 면 풀이를 확인했습니다. 카메라 제조사·모델·장치 식별자는 기록되지 않았습니다. | 동작 설정은 확인됐지만 장치 식별과 6-DoF pose 출력은 미확인입니다. 현재 detector는 `/camera/image_raw`에서 OBB 검출 후 `/cube/face_detections`를 발행하며 pose topic은 발행하지 않습니다. |
| 큐브 YOLO | `src/perception/cube_detection/model/cube-detector.pt`가 존재합니다. SHA-256은 `C1403D43D654A37D21351A5F5124AABC07C1BDB921E54E5FBBC899304BB409FB`입니다. | OBB 검출용 모델입니다. 모델 존재와 검출 기능은 큐브 pose 보정 완료를 뜻하지 않습니다. |
| Custom Hand 정책 | `sim2real/finger_robot_ppo_best.zip`을 `src/control/custom_hand_control/models/finger_robot_ppo_best.zip`로 복사했습니다. 실제 파일 SHA-256은 `5B9A3F36B348FA7FCC16370432E9F5CE476091CBEE38431686166FFABABD426B`입니다. | ZIP 메타데이터는 observation(8), action(4), actor 층 크기 8→64→64→4를 확인합니다. 참고 설정에 기록된 해시 `be90522e32676f1e815267e8ce962eeb9e404ebef55d97d3fca37505a84478f9`와 달라 같은 checkpoint로 확정할 수 없습니다. 복사본은 후보이며 calibration은 미검증입니다. |
| Custom Hand 모터 설정 | `left-rl-with-mujoco/sim2real/config.provisional.json`에는 `COM8`, 1,000,000 baud, XL330 ID 1–4, 손가락 순서 right/front/left/back → ID 4/1/2/3이 적혀 있습니다. 사용자는 해당 코드로 실작동을 확인했다고 보고했습니다. | 예시 JSON에 포트·baud·ID를 참고 후보로 반영했습니다. 단, 참고 설정의 mapping, 모터별 calibration·limits, `hardware_validated` 표시는 여전히 미검증입니다. 손목 Feetech 설정은 이 디렉토리에 없습니다. |
| LEAP 실작동 코드 | `right_rl_with_mujoco/deploy/policy_runner.py`는 기본 실행에서 `LeapHW`를 만들고 제어 루프에서 `write_sim(q_cmd)`를 호출합니다. `leap_hw.py`는 Dynamixel 연결, 토크 활성화·해제, 상태 읽기와 위치 쓰기를 구현합니다. | **실제 모터를 쓰는 배포 코드가 있습니다.** 따라서 임의 motor ID를 만들지 않고 소스의 ID 1–16을 예시 JSON에 반영했습니다. 현재 middleware LEAP adapter 자체는 dry-run입니다. |
| LEAP 정책·모터·pose 설정 | 참고 정책은 `right_rl_with_mujoco/policy/policy_np.npz` (SHA-256 `DC220D146BC5532C4AE09907C6D6BBC887335389D215AFAAFB69EEAB679560E7`)이며 108차원 관측 조립기를 사용합니다. `leap_hw.py`의 기본 포트는 Linux `/dev/ttyUSB0`, baud는 3,000,000입니다. 회전 관절 ID 1, 5, 9의 부호는 미검증입니다. 정책 실행기는 `--cams`에 카메라 보정 파일을 요구합니다. | motor ID와 Linux 기준값을 참조로 기록했습니다. `/dev/ttyUSB0`는 Windows COM 포트로 사용할 수 없으므로 실제 Windows port·baud는 비워 두었습니다. 해당 camera calibration 파일도 middleware에 연결되어 있지 않습니다. |

따라서 현재 확정 가능한 실물 모터 포트/ID와 큐브 pose 입력은 없습니다. 추가 수집 항목은 카메라 제조사·모델 또는 pose provider, pose topic/type/frame, 실제 양손의 모터 응답 ID·model number·COM 포트·baud rate, 선택한 policy artifact 경로와 SHA-256, 조립 frame 및 정지 방식입니다. 현재 `target_face`와 회전량은 논리적 계약 값이며 실제 모터 명령으로 변환되지 않습니다.

## Calibration 설정 초안 및 구동 차단

`cube_execution/config/hardware_calibration.example.json`은 실제 calibration 데이터를 채우기 위한 JSON 형식 초안입니다. Custom 손가락과 LEAP 모터 ID, Custom COM8/baud 값은 참고 설정에서 가져온 후보로 미리 적고 `verified`는 `false`로 유지했습니다. LEAP의 Linux port는 `reference_port`에만 두고 실제 `port`는 비워 두었습니다. Custom 손목·frame·pose·모델 경로와 검증 결과 등 미확정 값은 빈 문자열, `null`, 빈 목록 또는 `false`입니다. 두 정책 후보 파일의 SHA-256을 기록했지만 `model_path`는 각 로컬 설정에 맞춰 채워야 합니다. Custom 파일은 참고 설정의 기록 해시와 다르므로 선택 checkpoint가 맞는지도 확인이 필요합니다. 이 파일은 현재 장치와 모델의 완료된 calibration이 아닙니다.

`cube_execution.calibration` 검증기는 다음 항목을 확인합니다.

- schema 버전과 문서 전체, pose, frame/transform, 손별 motor 그룹, 정책, 안전 항목의 명시적 `verified: true` 표시
- pose topic·type·frame·단위·quaternion 형식과 양수 pose age 한도
- 각 프레임 이름, motor model, port·양수 baud rate·중복 없는 motor ID 목록
- 각 motor ID와 1:1로 대응하는 joint mapping: 이름, ID, 방향(`-1` 또는 `1`), zero offset, 단위, 유효 범위
- LEAP/Custom 정책 파일 경로와 기록한 SHA-256의 실제 파일 일치, observation schema 확인 표시
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

위 계약을 실제 값으로 채우기 위한 자료는 카메라/pose provider의 선택, 양 손과 손목의 실물 조립 frame·motor ID·통신값, 정책별 실기 observation/action 보정, 하드웨어 정지 방식입니다. shadow input의 freshness·frame·배열 형식 검사는 구현했지만 실제 calibration 기록, upstream pose/joint publisher, pose 기반 목표 변환, motor driver 및 adapter 완료 판정은 아직 없습니다.
