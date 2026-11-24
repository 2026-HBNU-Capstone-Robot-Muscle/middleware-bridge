# 기존 오른손 경로를 ROS 액션으로 실행 — 2026-11-24

`feature/hardware`의 별도 `recorded` 모드다. 기본 `mock`/`read_only`, 기존 상위 실행기·UI·왼손 코드는 그대로다. 이번 작업에서는 장치를 열거나 모터를 구동하지 않았다.

## 연결한 범위

| primitive_id | 동작 |
|---|---|
| `prepare_grip_and_support` | 기존 엄지 선행 준비를 거쳐 확정 G로 이동·유지 |
| `rotate_horizontal_and_support` | G 준비 → 기존 가로 목표5278개 → G 유지 |
| `rotate_vertical_and_support` | G 준비 → 최신 세로 목표5549개 → G 유지 |

첫 요청에만 기존 준비·토크 설정을 수행한다. 성공 응답 뒤에도 같은 제어 루프와 포트를 유지한다. 같은 `scan_id`/`execution_id`의 다음 요청을 G 경계에서 받아 이어 실행한다. 동작 사이에 OFF/OPEN/초기화를 넣지 않는다. `step_index`는 증가시켜야 하며, 중복·이전 요청은 다시 움직이지 않고 거부한다.

완료는 원본 경로를 모두 발행하고, 원본 건강·추종 검사를 통과한 G 표본3개를 추가로 확인한 시점이다. 이는 관절 경로 도달 판정이다. 실제 큐브 회전각·접촉력·미끄러짐이나 목표 면 방향을 측정했다는 뜻은 아니다. `/leap_hand/support_status`의 `support_basis`도 이 구분을 표시한다.

한 작업 스레드만 원본 `PoseBus`를 연다. ROS 콜백은 요청을 큐에 넣고 완전한16모터 표본을 받아 발행한다. 캐시의 원래 취득 시각을 유지하며 오래된 상태를 새로 읽은 것으로 처리하지 않는다. 기존75ms·최대2틱·450mA·PID·건강/추종/진행/통신 검사와 OFF·RAM 복구 코드를 재사용한다. 가로의 기존 기록 범위는 가로 구간에서만 적용한다. 한 요청의 어댑터 시간제한은900초이며 요청 사이 G 유지는 시간 종료가 없다.

## 소스 준비와 장치 없는 검사

오른손 저장소의 커밋 `28e495c34628e6074f6faa0a5c3038d4e8ef8d61`에 있는 `hardware/right_hand`를 사용한다. 미들웨어 Python에 NumPy가 필요하며 실제 구동 환경에는 패키지의 `hardware` extra에 고정한 `dynamixel-sdk==4.1.0`도 준비한다. 설치된 원래 PC의 `.runtime`을 복사할 필요는 없다.

```powershell
python -B scripts/check_recorded_motion.py --source-root 'C:/path/right_rl_with_mujoco/hardware/right_hand'
python -B scripts/check_execution_contract.py
```

첫 명령은 장치를 열지 않는다. 고정한 manifest SHA256,267개 참조 원본, 후보와 같은 G 끝점을 확인한다. 소스가 바뀌면 거부한다. 소스 버전을 갱신할 때는 경로·범위·검사를 다시 검토해 pin을 갱신해야 한다.

기존 코드의 import가 원래 PC의 `../work/Leap_Test/deploy`를 참조했으므로, 그곳의 `leap_hw.py`/`limits.py` 두 파일을 `leap_hand_control/recorded_compat`에 바이트 그대로 보존했다. 각각 SHA256 `bcac41f9ab95a406c3ad571a84c7bdb4a98ff44f420759f204b266b627c452eb`, `4852b466d90023519fc941622ae31e20457bad8518dbb201abb934232d685299`를 확인한 뒤 역사적 import에만 제공한다. 이 파일의 `LeapHW`,3Mbps 기본값·옛 매핑은 새 모터 출력에 쓰지 않는다. 실제 출력은 고정한 기존 `PoseBus`, 현재 ROS 관절 발행은 최신 `joint_mapping`을 사용한다.

## 실제 ROS 환경에서 시험할 때

아래 명령은 담당자가 직접 실행한다. 기존 `.cmd`와 다른 포트 소유 프로그램을 종료하고, 기존 빌드 절차로 `pixi run build-windows`를 수행해 overlay와 새 모듈을 설치한다. 실제 로봇과 큐브 배치를 확인한 다음 명시적으로 모드를 선택한다.

```powershell
pixi run powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/run_leap_adapter.ps1 -Mode recorded -SourceRoot 'C:/path/right_rl_with_mujoco/hardware/right_hand' -EnableRecordedHardware
```

시작은 기존 식별/사전검사와 읽기만 수행한다. 물리 액션 요청 전에는 새 목표·설정·토크를 쓰지 않는다. 원본이 식별하는 FTDI 어댑터를 사용하며 포트는 원본 USB 식별로 찾는다. 필요하면 현재 확인한 `-Port`를 추가해 자동 검출 결과와 일치하는지도 검사한다.

별도 overlay 터미널에서 예를 들어 가로 동작을 한 번 요청한다. 이 명령은 모터를 움직인다.

```powershell
ros2 action send_goal /leap_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive "{scan_id: 'manual_01', execution_id: 'recorded_01', move_index: 1, step_index: 1, cube_move: 'U', target_face: 'U', face_direction_order: 'URFDLB', target_face_direction_index: 0, clockwise_quarter_turns: 0, primitive_id: 'rotate_horizontal_and_support', dry_run: false, policy_id: '', policy_action_values: []}" --feedback
```

이 직접 요청의 `cube_move`/`target_face`는 명령 선택에 쓰지 않는 문맥 필드다. 수행 경로는 명시한 `primitive_id`가 고른다. 위 요청이 U면을 위로 보냈다고 해석하지 않는다. 세로는 같은 scan/execution과 **새 step_index**로 `rotate_vertical_and_support`를 요청한다. 다른 execution은 지지 소유권을 가져갈 수 없다. 클라이언트가 결과를 받고 끝나도 서버는 G를 계속 유지한다.

이동 중 액션 취소는 원본 제어 루프 중단 → OFF 확인·설정 복구 → 종료를 기다린 뒤 응답한다. 성공 응답 후 유지 중에는 다음 별도 정지 서비스를 사용한다.

```powershell
ros2 service call /leap_hand/stop_recorded_motion std_srvs/srv/Trigger "{}"
```

서비스 응답은 **정지 요청 접수**다. 이후 `/leap_hand/support_status`와 `results/recorded_motion/recorded_motion_*/result.json`의 종료 결과를 확인한다. `STOPPED`는 작업 스레드 종료 상태이고, 실제 OFF·설정 복구는 `all_torque_off_verified`/`settings_restored` 필드로 구분한다. 첫 동작 전 읽기만 하다 닫은 경우에는 다른 프로그램이 남긴 ON을 OFF 처리했다고 표시하지 않는다. `FAULT`/`STOP_UNCONFIRMED` 또는 OFF 미확인은 기존 절차대로 담당자가 전원을 확인한다. 정지 후 새 동작을 시작하려면 노드를 다시 연다.

## 검사 결과와 남은 연결

전체 장치 없는 시험124개 통과(건너뜀0). 원본 가로→세로 목표열 완전 보존,800초를 넘는 한 루프 진행,한 번 ON·중간 OFF 없음,가로 범위의 세로 적용 방지,G3표본 이전 성공 금지,전류/읽기 실패,중복 요청 거부,취소·종료 확인,production ROS 콜백 흐름을 검사한다. 실제 ROS/DDS와 모터를 사용한 시험은 아직 수행하지 않았다.

기존 상위 실행기의 `orient_face_up_and_support`는 자동으로 이 세 명령에 대응시키지 않는다. 실제 가로·세로 회전과 큐브 면 방향 대응이 아직 등록되지 않았으므로 해당 요청은 `ORIENTATION_ROUTE_UNCONFIGURED`로 거부한다. 기존 SAC/shadow 출력도 저장 경로 명령으로 섞지 않는다. 다음 단계는 팀 ROS PC의 단독 액션 구동 확인,실제 면 방향에 따른 경로 선택,상위 오른손 지지 heartbeat 소비·왼손 차단 연결이다. GUI 전체 풀이의 `dry_run=false` 차단은 유지한다.
