# 양손 통합 실행 응답 계약

2026-11-16, `feature/hardware`. UI 및 Action/Message 형식은 바꾸지 않았다.

## 구현한 것

- 오른손 방향 변경/지지 → 왼손 윗단 파지 → 회전 → 해제의 기존4단계 순서를 유지한다.
- 오른손 요청에는 회전 **전** 현재 면 방향을 전달한다. 성공한 손 primitive 뒤에만 계획 관절·큐브 방향·마지막 정책 action과 완료한 단계 수를 반영한다. 실패한 동작을 완료한 것처럼 갱신하지 않는다.
- 정책 추론 결과는 추론 기록으로 남기고, 그 결과만으로 손 동작 성공을 판정하지 않는다. ROS의 성공 terminal status와 primitive 결과의 success가 모두 필요하다.
- 수락 응답부터 완료 결과까지 시간제한을 적용한다. 시간초과 뒤 늦게 수락된 child도 취소를 요청한다.
- 상위 취소 요청은 하위 액션에 전달하고, 하위 terminal 결과로 취소가 확인된 뒤 상위 취소 완료를 알린다. 마지막 단계에서 들어온 취소도 성공으로 바꾸지 않는다.
- 응답 유실·시간초과·취소 확인 실패로 손 상태가 불명확하면 `HAND_*` 또는 `POLICY_*` 오류를 반환하고 새 풀이 실행을 차단한다. 시간초과됐다고 다음 동작을 보내지 않는다.

오류 뒤 종료 상태가 불명확한 경우에는 실제 hand adapter의 상태/정지를 확인한 뒤 실행기 노드를 재시작한다. 노드 재시작이 물리 정지 명령을 대신하지 않는다. 일반적으로 완료가 확인된 primitive 실패나 거부는 이 불명확 상태 latch와 구분한다.

## 시간제한 설정

| ROS 파라미터 | 기본값 | 범위 |
|---|---:|---|
| `hand_timeout_s` | 520초 | 손 primitive 수락+실행 전체 |
| `policy_timeout_s` | 10초 | 정책 액션 수락+추론 전체 |
| `cancel_timeout_s` | 2초 | 취소 요청 뒤 terminal 결과 확인 |

값은 유한한 양수여야 한다. 손 액션520초는 기존 오른손 실행기의 전체500초 한도와 별도인 상위 응답 한도다. 모터 전류·PID·추종 기준을 변경하지 않는다. 이 타이머는 하위 드라이버의 실시간 정지와 건강 감시를 대신하지 않는다.

응답 감시는 ROS 시뮬레이션 시간이 멈춰도 동작하도록 steady clock을 사용한다.

## 장치 없이 검사

저장소 루트에서 `pixi run check-execution-contract` 또는 준비된 Python으로 `python -B scripts/check_execution_contract.py`를 실행한다. 표준 unittest와 기존 NumPy를 사용한다. 로봇·카메라·네트워크는 열지 않는다.

검사 결과는 `results/middleware_checks/execution_contract.json`에 저장된다. 성공/실패 순서, 현재 좌표 전달, 실패 시 상태 미갱신, 취소 확인/미확인, 마지막 단계 취소, 수락·결과 시간초과, 늦은 수락 취소, 상태 불명확 시 다음 실행 차단을 검사한다.

## 마지막: 남은 검증과 연결

- 이번 로컬 검사는 ROS transport/message stand-in으로 실제 executor 제어 흐름을 검사했다. 실제 rclpy executor·DDS·양손 action server에서 돌린 결과와 구분한다. ROS 환경에서는 기존 `scripts/ros2_dryrun_check.py`의 success/cancel/missing 경로도 확인한다.
- 실제 모터 adapter와 단일 포트 I/O 소유자, 실제 완료·건강 상태 및 오른손 지지 heartbeat는 아직 연결되지 않았다. `dry_run=false` 차단과 calibration의 verified 필드는 유지한다.
- 오른손 완료 이후 왼손 동작 중 지지 유지·감시와 고장 전파는 실제 adapter에 이어서 연결해야 한다. 이번 변경은 오른손의 실물 경로나 통신 드라이버를 고친 작업이 아니다.
- 큐브 상태 갱신은 여전히 성공 응답 뒤의 이상적인 dry-run 계획이다. 실제 큐브 pose 관측이나 회전 성공 측정을 구현했다고 해석하지 않는다.
