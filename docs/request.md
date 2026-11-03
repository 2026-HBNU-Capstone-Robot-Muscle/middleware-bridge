# 큐브 조작 실행 노드 데이터 계약 제안

## 목적과 현재 경계

인식·풀이 경로는 유효한 큐브 상태를 `/cube/state`로 발행하고, 풀이 성공 시
`system_interfaces/msg/CubeSolution`을 `/cube/solution`으로 발행합니다. 현재
`CubeSolution`은 `header`, `scan_id`, Kociemba URFDLB `facelets`, `moves`를 담습니다.

이 문서는 `/cube/solution`을 받아 큐브 조작 시퀀스를 실행할 ROS 2 노드의 입출력 계약을
제안합니다. 사용자가 확인한 하드웨어 배치는 LEAP Hand가 큐브 하단에서 고정·지지와 상단
레이어 노출을 담당하고, Custom Hand가 상단에서 큐브를 파지하며 손목 회전으로 해당 레이어를
돌리는 구조입니다. Custom Hand 손가락은 학습 모델, 손목은 하드코딩 제어를 사용합니다.
참고용 `right_rl_with_mujoco` 자료는 LEAP 손 관절 16개와 Dynamixel XC330-M288-T 실기 제어를,
`left-rl-with-mujoco/sim2real` 자료는 Custom Hand 손가락 4개와 XL330-M288 계열 실기 제어를
기술합니다. 사용자가 확정한 세부 모델은 Custom Hand 손가락 `Dynamixel XL330-M288-T`, 손목
`Feetech STS3215`, LEAP Hand 전체 모터 `Dynamixel XC330-M288-T`입니다. 구체적 ID, 버스·포트,
관절/좌표 매핑, 손목 회전 각도와 완료 판정은 아직 계약 문서에서 확정하지 않습니다.

이 문서는 데이터 계약 제안만 담습니다. ROS 메시지·액션 정의나 실행 노드는 아직
`src/system_interfaces` 또는 다른 소스에 추가하지 않았습니다.

## 제안 노드와 데이터 흐름

실행 노드 이름은 `cube_sequence_executor`로 제안합니다.

| 인터페이스 | 방향 | ROS 타입 | 역할 |
|---|---|---|---|
| `/cube/solution` | 인식·풀이 → 실행 노드 | `system_interfaces/msg/CubeSolution` | 실행할 큐브 상태와 이동 토큰 배열을 전달합니다. |
| `/cube/execute_solution` | 제어 UI·상위 노드 → 실행 노드 | `system_interfaces/action/ExecuteCubeSolution` | 특정 `scan_id`의 실행을 명시적으로 시작하고 취소합니다. |
| `/cube/execution_status` | 실행 노드 → UI·진단 | `system_interfaces/msg/CubeExecutionStatus` | 대기·진행·완료·실패·취소 상태를 발행합니다. |
| `/leap_hand/execute_primitive` | 실행 노드 → LEAP Hand 어댑터 | `system_interfaces/action/ExecuteHandPrimitive` | 하단 고정·지지 및 목표 레이어가 위로 오도록 큐브 방향을 조정합니다. |
| `/custom_hand/execute_primitive` | 실행 노드 → Custom Hand 어댑터 | `system_interfaces/action/ExecuteHandPrimitive` | 학습된 손가락 모델로 파지하고 Feetech 손목 모터로 상단 레이어를 회전합니다. |

`/cube/solution`을 받았다는 사실만으로 하드웨어를 움직이지 않습니다. 풀이 토픽은 실행할
계획으로 저장하고, `/cube/execute_solution` 액션 목표에 해당 `scan_id`가 명시적으로
들어온 뒤 실행합니다. 현재 토픽 publisher는 transient-local QoS를 사용하므로 실행 노드가
늦게 시작하면 이전 풀이를 받을 수 있습니다. 수신과 실제 실행을 분리해 이 재전달만으로
손이 움직이지 않도록 합니다. `/cube/execute_solution`은 한 번의 큐브 풀이 전체를 나타내는
상위 액션입니다. 실행 노드는 액션 내부에서 LEAP Hand·Custom Hand 어댑터를 여러 차례
번갈아 호출할 수 있습니다. 손을 바꾸는 횟수는 액션 수가 아니라 진행 중인 단계 수로
표현합니다.

### `CubeSolution` 입력 검증

실행 노드는 수신한 풀이를 대기 목록에 넣기 전에 다음을 확인합니다.

- `scan_id`가 비어 있지 않은지 확인합니다.
- `facelets`가 54자이고, `URFDLB`만 포함하며, 각 기호가 9회씩 있는지 확인합니다.
- `moves`의 각 항목이 `R`, `U'`, `F2` 등 허용된 표준 토큰인지 확인합니다.
- 이미 완료 또는 거부된 같은 `scan_id`가 다시 들어오면 중복으로 기록하고 자동 재실행하지 않습니다.

입력 검증 실패는 `CubeExecutionStatus`에 `FAILED`와 오류 코드를 기록합니다. 실제 하드웨어
실행 여부를 식별하려면 프로세스 재시작 뒤에도 중복 여부를 보존할 저장 정책이 필요합니다.
그 지속성 방식은 구현 단계에서 별도로 결정합니다.

## 제안 메시지

### `CubeExecutionStatus.msg`

```text
uint8 STATE_RECEIVED=0
uint8 STATE_WAITING_FOR_EXECUTION=1
uint8 STATE_VALIDATING=2
uint8 STATE_HANDOFF=3
uint8 STATE_EXECUTING=4
uint8 STATE_COMPLETED=5
uint8 STATE_FAILED=6
uint8 STATE_CANCELLED=7

std_msgs/Header header
string scan_id
string execution_id
string workflow_id
uint8 state
uint32 move_index
uint32 total_moves
string current_move
uint32 step_index
uint32 total_steps
string hand_id
string primitive_id
string error_code
string message
```

- `move_index`는 1부터 시작하며, 실행 전·대기 중에는 0입니다.
- `total_moves`는 수신된 `moves` 배열의 길이입니다.
- `current_move`는 현재 처리 중인 큐브 이동 토큰입니다. 처리 중인 이동이 없으면 빈 문자열입니다.
- `step_index`, `total_steps`는 전체 실행 단계에서의 1 기반 현재 단계와 총 단계 수입니다. 단계가
  준비되기 전에는 0입니다. 큐브 이동 하나가 여러 hand primitive로 나뉠 수 있으므로
  `move_index`와 별도로 둡니다.
- `hand_id`는 현재 단계를 수행하는 `leap_hand` 또는 `custom_hand`입니다. hand 전환 중이거나
  활성 동작이 없으면 빈 문자열입니다.
- `workflow_id`는 현재 실행에서 선택된 반복 동작 흐름입니다. workflow 선택 전이면 빈 문자열입니다.
- `primitive_id`는 해당 어댑터가 수행할 추상 조작 primitive 식별자입니다. 구체적인 이름과
  파라미터는 하드웨어 사양 및 실제 동작 분석 후 정합니다.
- `error_code`는 성공 및 일반 진행 상태에서 빈 문자열이며, 실패 시 기계 판독 가능한 코드입니다.
- `message`는 사람이 읽을 상태 설명입니다.
- `header.stamp`는 상태 변경 시각, `header.frame_id`는 사용하지 않으며 빈 문자열로 둡니다.

권장 오류 코드는 `INVALID_SOLUTION`, `SOLUTION_NOT_FOUND`, `DUPLICATE_EXECUTION`,
`EXECUTION_DISABLED`, `HAND_NOT_READY`, `MOTION_FAILED`, `FEEDBACK_TIMEOUT`,
`CANCELLED`입니다. 실제 드라이버가 정해지면 드라이버별 오류를 추가하되 기존 의미를
바꾸지 않습니다.

## 제안 액션

### `ExecuteCubeSolution.action`

```text
# Goal
string scan_id
string workflow_id
bool dry_run
---
# Result
bool success
bool dry_run
string scan_id
string execution_id
uint32 completed_moves
uint32 completed_steps
string error_code
string error_message
---
# Feedback
system_interfaces/CubeExecutionStatus status
```

- 목표의 `scan_id`는 `/cube/solution`에서 수신해 보관 중인 풀이를 지정합니다. 풀이가
  없으면 `SOLUTION_NOT_FOUND`로 종료합니다.
- `dry_run=true`는 하드웨어를 구동하지 않고 이동 순서·검증·피드백 경로만 확인합니다.
- `dry_run=false`는 실제 조작을 요청합니다. 하드웨어 실행 허가가 꺼져 있거나 손 드라이버가
  준비되지 않았으면 움직이지 않고 `EXECUTION_DISABLED` 또는 `HAND_NOT_READY`로 끝냅니다.
- 액션의 취소는 현재 동작을 안전하게 멈출 수 있는 지점에서 반영합니다. 어느 지점에서
  안전하게 멈출 수 있는지는 손 드라이버와 조작 primitive가 정해진 뒤 확정합니다.
- `completed_moves`는 완료 확인을 받은 큐브 이동 수입니다. 이동 도중 실패한 동작은
  완료 수에 포함하지 않습니다.
- `completed_steps`는 hand 어댑터로부터 완료 확인을 받은 primitive 수입니다.
- `workflow_id`는 solver 이동을 LEAP Hand와 Custom Hand의 순차·반복 동작으로 바꾸는
  확정된 workflow를 선택합니다. 실제 역할 분담이 한 가지로 확정되기 전에는 값의 열거를
  고정하지 않습니다.
- `execution_id`는 액션 실행마다 노드가 생성하는 식별자이며, 피드백·상태·결과를 연결합니다.

### `ExecuteHandPrimitive.action`

```text
# Goal
string scan_id
string execution_id
uint32 move_index
uint32 step_index
string cube_move
string primitive_id
bool dry_run
---
# Result
bool success
string error_code
string error_message
---
# Feedback
uint8 state
string message
```

각 손 어댑터는 이 액션 한 번에 하나의 추상 primitive를 수행합니다. `scan_id`,
`execution_id`, `move_index`, `step_index`로 상위 실행과 단계를 연결합니다. `primitive_id`와
`cube_move`는 요청의 의미를 전달하며, 관절·모터 명령값은 손 어댑터 내부에 둡니다. `dry_run`이면
하드웨어를 움직이지 않고 요청 수신과 완료 경로만 검증합니다. 두 어댑터는 같은 액션 타입을
사용하되 각자 별도의 action endpoint를 제공합니다.

실행 허가는 기본적으로 비활성화하고, `dry_run` 검증과 하드웨어 준비 확인이 끝나기 전까지
실제 구동을 시작하지 않는 정책을 제안합니다. 허가 설정의 ROS 매개변수 이름은 구현 시
정합니다.

## 상태 전이와 처리 규칙

1. 풀이 토픽을 수신하고 검증한 뒤 `RECEIVED`, `WAITING_FOR_EXECUTION` 상태를 발행합니다.
2. 액션 목표가 오면 해당 풀이를 찾아 `VALIDATING` 상태를 발행합니다.
3. `dry_run`이면 하드웨어 명령 없이 각 이동 토큰과 전체 순서를 순회해 `COMPLETED` 결과를 반환합니다.
4. 실제 실행이 허가되고 두 어댑터가 준비되면 각 Kociemba 이동을 상호작용 단계로 풉니다.
   LEAP Hand가 목표 레이어를 위로 향하게 큐브를 재배치하고 하단에서 고정·지지합니다.
   Custom Hand는 학습 정책으로 큐브를 파지한 뒤 손목 모터를 하드코딩 경로로 제어해 상단
   레이어를 회전합니다. 다음 이동을 위해 필요한 경우 이 전환을 반복합니다.
5. 각 primitive를 해당 hand action에 보내고 완료·실패 결과를 기다립니다. 성공하면
   `/cube/execution_status`와 액션 피드백에 `move_index`, `step_index`, `hand_id`,
   `primitive_id`를 발행하고 다음 단계를 진행합니다. 따라서 LEAP Hand와 Custom Hand 사이의
   반복 전환은 하나의 `/cube/execute_solution` 액션 안에서 처리됩니다.
6. hand 어댑터 하나가 실패하면 다음 단계를 실행하지 않고 `FAILED` 상태와 완료 수, 오류를 반환합니다.
7. 액션 취소가 요청되면 현재 hand primitive의 안전 정지 지점에 도달한 뒤 `CANCELLED` 상태와
   완료 수를 반환합니다.

동일한 `execution_id`는 한 번만 처리합니다. `dry_run`은 실제 큐브 상태를 바꾸지 않으므로
같은 풀이에 대해 반복할 수 있습니다. 실제 동작이 시작된 뒤 완료·실패·취소된 `scan_id`는
재실행하지 않고, 큐브를 다시 인식해 새 풀이를 만들도록 합니다. 노드 재시작 후에도 이
중복 방지 규칙을 보장하려면 실행 기록을 지속 저장해야 하며, 저장 방식은 미정입니다.

노드는 새 풀이를 받으면 상태 토픽에 최신 상태를 발행합니다. `/cube/execution_status`에는
`RELIABLE` QoS를 사용하고, UI가 늦게 연결되어도 마지막 상태를 조회할 수 있도록
`TRANSIENT_LOCAL` 내구성을 우선 제안합니다. 큐 깊이와 재시작 후 상태 복원 정책은 실행 빈도와
중복 방지 설계가 정해진 뒤 확정합니다.

## 하드웨어 계약과 분리할 항목

실행 노드의 입력은 solver가 생성한 큐브 이동 토큰입니다. 실행 노드는 이를 손 모델의
관측 벡터나 정책 행동값으로 직접 바꾸지 않습니다. LEAP Hand adapter는 하단의 지지·고정과
큐브 재배치를 담당하며 16개 Dynamixel XC330-M288-T 구동부의 학습 정책/손 드라이버 경계를
캡슐화합니다. Custom Hand adapter는 4개 손가락 Dynamixel XL330-M288-T를 학습 모델로 제어하고,
별도의 Feetech STS3215 손목 모터를 하드코딩 제어합니다. 두 adapter는 공통
`ExecuteHandPrimitive` action을 제공하고 상위 노드는 hand, primitive, 순서, 성공 결과를
관리합니다. 모터별 명령값은 각 adapter 내부에 둡니다.

다음 항목은 현재 자료만으로 정할 수 없어 이 계약에서 확정하지 않습니다.

- 모터 ID, 버스·포트 및 ROS 드라이버 명령·상태 계약
- 각 `R`, `U'`, `F2` 이동에 필요한 LEAP 재배치·지지와 Custom 파지·손목 회전의 primitive 순서
- 두 hand adapter의 준비 상태, 실행 완료 신호, 오류 코드 및 handoff 안전 조건
- 동작 완료를 확인할 관절·큐브 자세 피드백 및 카메라 보정
- 동작 시간 제한, 재시도, 안전 정지, 중단 후 큐브 상태 재인식 절차

따라서 이 데이터 계약만으로 실제 큐브를 조작할 수 있다고 보장하지 않습니다. 손별 드라이버
입출력, 기구학적 회전 방향, primitive별 성공 조건과 안전한 handoff를 구체화해야 합니다.

## QoS 제안

| 인터페이스 | 신뢰성 | 내구성 | 근거 |
|---|---|---|---|
| `/cube/solution` 구독 | `RELIABLE` | `TRANSIENT_LOCAL` | 최신 풀이를 늦게 시작한 실행 노드가 받을 수 있습니다. 수신만으로 실행하지 않고 액션 목표를 요구합니다. |
| `/cube/execute_solution` 액션 | `RELIABLE` | 액션 기본 QoS | 장시간 실행 요청, 취소, 완료 결과의 신뢰성 있는 교환이 필요합니다. |
| `/cube/execution_status` | `RELIABLE` | `TRANSIENT_LOCAL` | UI 연결 전 마지막 실행 상태와 진행 결과를 확인할 수 있습니다. |
| `/leap_hand/execute_primitive`, `/custom_hand/execute_primitive` 액션 | `RELIABLE` | 액션 기본 QoS | 각 hand adapter에 primitive 실행을 요청하고 완료·실패·취소 결과를 받습니다. |

## 구현 전 확인 항목

1. 손별 모터 ID, 통신 버스·포트, joint/좌표 매핑과 ROS 드라이버 입출력 계약을 기록합니다.
2. LEAP 고정·재배치와 Custom 파지·손목 회전 primitive 및 완료 조건을 정의합니다.
3. 각 hand adapter의 준비 상태, primitive 완료·오류 피드백과 안전한 handoff를 정합니다.
4. 카메라·자세 피드백, 실패 시 안전 정지와 큐브 상태 재인식 경로를 정의합니다.
5. 이 제안의 상태 메시지, 상위 action, hand primitive action, QoS와 중복 방지 정책을 검토한 뒤 `src/system_interfaces`에 반영합니다.
