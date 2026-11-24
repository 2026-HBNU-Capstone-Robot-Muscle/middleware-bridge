# 오른손 ROS 상태·동작 어댑터

2026-11-16, `feature/hardware`. UI와 왼손 코드는 수정하지 않았다.

## 연결한 부분

- 확인한16관절 매핑을 적용한다. 시뮬 순서의 실제 motor ID는 `(8,6,7,5,12,10,11,9,16,14,15,13,4,3,2,1)`, 변환은 `(ticks-2048)*2π/4096`이다. 값은 자르거나 감싸지 않는다.
- `/leap_hand/joint_states`와 `/leap_hand/commanded_joint_states`에 실제 위치와 Goal Position 레지스터를 구분해 발행한다. 기존 `policy_input_bridge`의 기본 토픽과 관절 이름에 맞췄다. 전류를 관절 토크로, profile velocity를 측정 속도로 채우지 않는다.
- `/leap_hand/execute_primitive`의 검증을 재사용한다. 명령을 I/O 담당자에게 넘기고, backend 완료 뒤 응답한다. 성공 응답 뒤에도 상태 읽기와 지지 상태 발행이 계속된다.
- `/leap_hand/support_status`는 JSON `std_msgs/String`이다. `state`, `simulated`, `healthy`, `supporting`, `scan_id`, `execution_id`, `move_index`, `sample_age_s`, `error`를 발행한다. 상태가 오래됐거나 읽기 실패하면 supporting을 false로 두고 새 관절 상태로 위장하지 않는다.
- 한 I/O 담당자만 backend를 연다. ROS action callback은 요청을 큐에 넣는다. 실행 중 덮어쓰기, 다른 execution의 지지 소유권 탈취를 거부한다. 취소는 I/O 담당자가 backend stop을 처리한 뒤 결과를 돌려준다.

## 모드

| 모드 | 장치 접근 | 동작·지지 결과 |
|---|---|---|
| `mock` 기본값 | 없음 | 인터페이스 시험용. `simulated=true`, dry-run만 수락 |
| `read_only` | 지정 포트의 PING/READ만 | 실제16개 위치·목표·전류·전압·온도·토크 읽기. 동작 요청은 READ_ONLY로 거부 |
| `recorded` 명시적 선택 | 원본 PoseBus의 읽기·제한된 RAM 쓰기 | 별도 활성화와 직접 grip/horizontal/vertical 액션 필요. 완료 후 G 유지. [11/24 안내](recorded-motion.md) |

mock의 HOLDING은 실물 파지가 아니다. read_only는 토크나 목표를 쓰지 않으며 실제 지지력을 판정하지 않는다. 기본 서버·mock·read_only의 실제 구동 차단은 유지하며,11/24 추가한 recorded 모드의 명시적 세 액션만 별도 구동 경로를 제공한다. 관절 G 도달과 실제 큐브 지지력은 구분한다.

READ-only 통신은 Protocol2.0/1Mbps, ID1–16, 모델1240을 확인한다. 완전한16개 상태만 발행하며 부분 응답은 통째로 폐기한다. Snapshot150ms, 전압3.8–6.5V, 온도45°C 및 기존 측정 전류550mA 중단 기준을 확인한다. 550mA는 설정 전류450mA와 다른 측정 trip 기준이다. 이 reader는 원래 경로 실행기의 통신 코드를 변경하지 않는다.

## 실행

ROS 환경에서 먼저 `pixi run build-windows`로 새 entry point를 설치한다. READ-only 모드의 Python에는 `dynamixel-sdk==4.1.0`도 설치되어 있어야 한다. 이번 실제 읽기 검사에 사용한 버전이며 패키지의 hardware extra에도 기록했다. 현재 원래 PC의 별도 `.runtime`에는 SDK가 있으나 다른 PC의 ROS Python에 자동 설치됐다고 가정하지 않는다.

기존 `leap_hand_primitive_server`를 중지하고 아래 **하나만** 실행한다. 같은 action 이름으로 두 서버를 동시에 실행하지 않는다. 기존 GUI launcher는 기본 동작을 유지하므로 어댑터를 자동 선택하지 않는다.

```powershell
# 모터 없이 액션·지지 상태 흐름 확인
pixi run powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/run_leap_adapter.ps1 -Mode mock

# 실제 상태 읽기만: 현재 PC에서 확인한 포트를 명시
pixi run powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/run_leap_adapter.ps1 -Mode read_only -Port COM7
```

ROS CLI에서 `/leap_hand/joint_states`, `/leap_hand/commanded_joint_states`, `/leap_hand/support_status`를 확인한다. 원래 `.cmd` 프로그램과 이 reader가 동시에 같은 포트를 사용하게 하지 않는다.

mock에서 기존4단계 풀이를 한 execution으로 실행하면 오른손 action 완료 이후 왼손 단계 동안 HOLDING을 유지하고 같은 execution의 다음 오른손 요청을 수락한다. 다른 execution을 시작하기 전에는 `ros2 service call /leap_hand/clear_mock_support std_srvs/srv/Trigger '{}'`로 모의 지지를 정리한다. 이 서비스는 모의 상태에만 적용되며 물리 비상 정지가 아니다.

ROS가 없어도 `python -B scripts/check_execution_contract.py`로 코드 계약을 검사할 수 있다. `python -B scripts/read_leap_state.py`는 기본 CHECK ONLY다. 실제 읽기는 `python -B scripts/read_leap_state.py --read-only --port COM7`로 명시하며 결과는 `results/leap_adapter/`에 남는다.

## 확인한 결과

원래 PC COM7에서 실제 SDK로 ID1–16 모두 모델1240 응답과 완전한 상태2회를 읽었고 포트를 닫았다. 목표 쓰기·토크 변경은0회다. 근거: `results/leap_adapter/read_only_20261116_071155_761082.json`. 이 검사는 ROS/DDS 실행 시험과 구분한다.

## 마지막: 아직 남은 것

- 11/24 recorded backend에 원본 제어 루프와 경로의 실제 목표 전송·G 유지·취소/OFF/복구를 연결했다. 원래 `.cmd`를 자동으로 열지 않으며 SAC 출력도 적용하지 않는다. 코드·가상 모터 시험 완료와 실제 ROS/모터 구동 확인은 별개다. 실행·제한은 [recorded-motion.md](recorded-motion.md)를 따른다.
- 현재 환경에서는 실제 ROS를 실행하지 못했다. ROS callback, DDS, 설치된 메시지/entry point와 양손 action server 조합은 팀 ROS PC에서 확인한다.
- 상위 실행기가 지지 heartbeat를 받아 왼손 시작/진행 중 오류로 전파하는 연결은 다음 작업이다. 현재 지지 topic 발행 자체가 그 소비 로직까지 완료했다는 뜻은 아니다.
- 실제 cube/palm pose, 좌표 변환, 관절 부호·기계 한계와 실물 지지력·윗단 공간 검증은 남아 있다. TODO2 전체를 실물 검증 완료로 표시하지 않는다.
