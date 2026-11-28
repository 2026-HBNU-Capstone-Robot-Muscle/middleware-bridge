# 실물 색 관찰을 반영한 목표 면 선택 — 2026-11-24

사용자가 기존 파일을 실행하며 보고한 **G 파지 전후 윗면/앞면/오른쪽면**을 사용했다. 관절값에서 큐브 방향을 추측하지 않았다.

| 상태 | 윗면 | 앞면 | 오른쪽면 |
|---|---|---|---|
| 가로 전 | 초록 | 노랑 | 빨강 |
| 가로 후 = 세로 전 | 초록 | 주황 | 노랑 |
| 세로 후 | 빨강 | 초록 | 노랑 |

가로는 **U고정·F→R**,세로는 **R고정·U→F**다. 공통으로 관찰한 두 면의 대응으로 각각 하나의 올바른 큐브 회전을 결정했다. 정확한 각도·허용 오차나 반복 성공률을 측정한 자료는 아니다. 고정한 같은 원본 경로를 사용한다. 근거·원본 후보 해시·144개 계획은 `results/recorded_orientation/calibration_20261124.json`에 보존했다.

## 입력과 상태

슬롯 순서는 `URFDLB`(위/오른쪽/앞/아래/왼쪽/뒤)이며 고정 G의 같은 손/관찰 좌표를 사용한다. `face_direction_order`의 각 글자는 **현재 그 슬롯에 놓인 원래 큐브 면 이름**이다. 큐브 스캔의 색→원래 면 이름 대응과 현재 G의 실제 위치를 맞춰서 전달해야 한다. 카메라 좌표나 다른 초기 자세 기준의 순서를 변환 없이 쓰지 않는다.

예를 들어 관찰 시작 G를 원래 URFDLB 기준으로 정의했다면,가로 뒤는 `UFLDBR`,이어서 세로 뒤는 `RFULBD`다. 이 기준에서는 원래 오른쪽 면(관찰의 빨강)이 위로 오는 `가로→세로`와 사용자의 최종 색 관찰이 일치한다. 스캔에서 다른 면 이름을 부여했다면 색 이름을 U/R/F에 임의로 고정하지 말고 해당 스캔 기준의 현재 순서를 사용한다.

처음 목표 면 요청에는 현재 순서가 반드시 필요하다. 이후 요청은 마지막 완료 순서와 일치해야 한다. 직접 가로/세로 명령의 옛 `target_face` 메타데이터는 초기 상태로 자동 채택하지 않는다. 목표 면 요청으로 상태를 정한 뒤에는 직접 회전도 그 순서를 갱신한다.

`/leap_hand/support_status`에는 다음을 발행한다.

- `face_direction_order`: 완료한 경로에 따른 논리 방향 상태. 이동 중·오류·정지 후에는 비운다.
- `orientation_state_known`: 같은 실행에서 위 논리 상태를 이어 쓸 수 있는지.
- `predicted_face_direction_order`, `planned_recorded_route`: 아직 실행 중일 수 있는 계획 결과와 경로.
- `orientation_basis`, `cube_orientation_sensor_verified=false`: 사용자 관찰의 분기와 완료한 관절 경로로 갱신한 추정이며 센서로 새 큐브 자세를 확인한 값이 아님.

복합 요청이 끝나기 전에는 완료 순서를 갱신하지 않는다. 중간 취소/오류는 남은 동작으로 진행하지 않으며 큐브를 처음부터 안 움직인 것으로 간주하지 않는다.

## 경로 선택

24개 올바른 큐브 방향에서 목표6면으로 가는144개 계획을 확인했다. 기존 정방향 가로·세로만 사용하며,목표 면이 위로 오는 조합 중 명목 이동 시간이 짧은 것을 고른다. 역방향 모터 경로는 새로 만들지 않았다.

| 현재 순서가 URFDLB일 때 목표 면 | 선택 경로 | 원본 목표열 명목 시간 |
|---|---|---:|
| U | 회전 없이 G 준비·유지 | 준비 시간만 |
| R | 가로→세로 | 약812초 |
| F | 가로→가로→세로 | 약1208초 |
| D | 세로→세로 | 약832초 |
| L | 가로→가로→가로→세로 | 약1604초 |
| B | 세로 | 약416초 |

준비·실제 추종/통신 대기·중간 G 정착은 추가된다. 복합 요청은 각 원본 목표열을 그대로 연결하고 구간 사이 G에서4회 기존 건강/추종 검사를 수행한다. 마지막 구간 뒤 G3표본까지 확인한 뒤 성공 응답하며 계속 G를 유지한다. 기존 공유 소스267개와 실제 모터 목표열·전류·PID·2틱/75ms는 바꾸지 않았다.

## ROS 요청 예시

기존 [recorded 모드 준비](recorded-motion.md)를 따른다. 다음은 **새 실행에서 현재 순서가 URFDLB로 확인된 경우**의 예시다. 실행하면 실제 모터가 움직인다.

```powershell
ros2 action send_goal /leap_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive "{scan_id: 'manual_02', execution_id: 'faceup_01', move_index: 1, step_index: 1, cube_move: 'R', target_face: 'R', face_direction_order: 'URFDLB', target_face_direction_index: 1, clockwise_quarter_turns: 0, primitive_id: 'orient_face_up_and_support', dry_run: false, policy_id: '', policy_action_values: []}" --feedback
```

다음 요청에는 같은 scan/execution과 새 step_index,실제 현재 슬롯 순서를 사용한다. 모터 단독 파일이나 카메라를 보며 손으로 큐브를 다시 배치했다면 이전 논리 상태를 그대로 이어 쓰지 않는다. 한 실행의 상태는 노드 재시작 뒤 자동으로 복원하지 않는다.

장치 없는 확인:

```powershell
python -B scripts/check_recorded_orientation.py
python -B scripts/check_execution_contract.py
```

상위 풀이 실행기의 실제 모터 실행 차단은 유지한다. 상위의 이상적인 정책 quaternion 갱신을 이 경로의 실제 완료 순서로 간주하지 않는다. 상위가 위 상태를 소비해 다음 요청의 순서와 시간 한도를 맞추고 오른손 지지를 감시하도록 연결하는 작업,실제 ROS/DDS의 복합 액션·반복 오차 확인은 남아 있다.
