# 오른손 표준 ROS 노드 실기 실행

`leap_hand_primitive_server`에서 기존 가로·세로 경로를 직접 실행한다. 기본값은 기존과 같은 `dry_run`이며 장치를 열지 않는다. `hardware_enabled:=true`와 오른손 자료 경로를 명시하면 같은 `/leap_hand/execute_primitive` 액션에 `recorded` backend를 연결한다. 기존 `leap_hand_adapter` 실행기도 호환용으로 남아 있다. 두 실행기를 동시에 켜지 않는다.

## 준비

두 저장소의 `feature/hardware`를 받는다. 오른손 자료 기준 커밋은 `fe0bdc001802b6cd8fd4d63eb4b0812accd72efc`이며 경로는 저장소 루트가 아닌 **`right_rl_with_mujoco/hardware/right_hand`**다. 이 경로의 원본 해시는 첫 실행 전에 검사한다. 11/26 로컬 SAC·간결화·떨림 완화 시험판은 이번 이식에 포함하지 않았다.

팀의 Windows 설치 절차로 환경을 설치한 뒤 다음을 실행한다. `pixi.toml`과 잠금 파일에는 `dynamixel-sdk==4.1.0`, `pyserial==3.5`가 포함돼 있다. 다른 PC에 원래 COM7을 그대로 적용하지 말고 실제 포트를 지정한다.

```powershell
pixi install --locked
pixi run build-windows
pixi shell
. .\.colcon-win\install\local_setup.ps1
```

기본 dry-run은 기존 명령과 같다.

```powershell
ros2 run leap_hand_control leap_hand_primitive_server
```

## 오른손 단독 실기 노드

기존 로봇 CMD와 GUI가 실행한 LEAP 서버를 정상 종료한다. 모터 포트 소유자는 하나여야 한다. 다음 예제의 자료 경로와 포트를 현재 PC에 맞춘다.

```powershell
.\scripts\windows\run_leap_adapter.ps1 `
  -Mode recorded `
  -SourceRoot 'C:\robot\right_rl_with_mujoco\hardware\right_hand' `
  -Port COM7 `
  -EnableRecordedHardware
```

동일한 노드를 직접 실행할 수도 있다.

```powershell
ros2 run leap_hand_control leap_hand_primitive_server --ros-args `
  -p hardware_enabled:=true `
  -p 'recorded_source_root:=C:\robot\right_rl_with_mujoco\hardware\right_hand' `
  -p port:=COM7
```

명시적 하드웨어 활성화만으로 경로를 재생하지 않는다. 기존 상태 확인 뒤 **`dry_run=false` 액션 요청이 들어왔을 때** G 준비와 모터 출력을 시작한다. 정상 완료 뒤에도 같은 포트·제어 루프에서 G를 유지한다. 다음 요청을 위해 OPEN/OFF를 끼우지 않는다.

## G 준비 → 가로 → 세로

큐브는 기존 단독 실기와 같은 방법으로 올리고, 다른 PowerShell 창에도 같은 Pixi/ROS overlay를 적용한다. 아래 명령은 실제 모터 동작을 요청한다.

```powershell
ros2 action send_goal /leap_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive '{scan_id: manual, execution_id: right_test, move_index: 1, step_index: 1, cube_move: U, target_face: U, primitive_id: prepare_grip_and_support, clockwise_quarter_turns: 0, dry_run: false}' --feedback
```

성공 응답과 G 유지를 확인한 뒤, 같은 `scan_id`/`execution_id`로 다음 요청을 보낸다. `step_index`는 증가시킨다.

```powershell
ros2 action send_goal /leap_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive '{scan_id: manual, execution_id: right_test, move_index: 1, step_index: 2, cube_move: U, target_face: U, primitive_id: rotate_horizontal_and_support, clockwise_quarter_turns: 0, dry_run: false}' --feedback
ros2 action send_goal /leap_hand/execute_primitive system_interfaces/action/ExecuteHandPrimitive '{scan_id: manual, execution_id: right_test, move_index: 1, step_index: 3, cube_move: U, target_face: U, primitive_id: rotate_vertical_and_support, clockwise_quarter_turns: 0, dry_run: false}' --feedback
```

직접 가로·세로 요청의 `target_face`는 메타데이터이며 원하는 큐브 면 방향을 보증하지 않는다. 목표 면 선택인 `orient_face_up_and_support`는 현재 면 순서를 명시해야 한다. [방향 대응](recorded-orientation.md)을 따른다. 저장 경로에 SAC/shadow action을 섞으면 거부한다.

75ms, 준비·가로 최종 받침2틱/허용 구간 최대6틱, 450mA·현재 PID와 기존 건강·추종·고정관절 검사를 재사용한다. 첫 준비와 요청 사이 G 유지를 포함해 최대10초 READ 복구를 사용한다. 로봇 CMD의 SPACE/A/B는 ROS 실행에 필요하지 않다.

## 상태와 정지

```powershell
ros2 topic echo /leap_hand/support_status
ros2 service call /leap_hand/stop_recorded_motion std_srvs/srv/Trigger '{}'
```

정지 서비스 응답은 접수 확인이다. 상태와 `results/recorded_motion/recorded_motion_*/result.json`에서 `all_torque_off_verified`·`settings_restored`를 확인한다. 종료 전 큐브를 받친다. 정지 후에는 노드를 재시작한다. `/leap_hand/joint_states`와 `/leap_hand/commanded_joint_states`로 실제/목표 관절을 확인할 수 있다.

`Invalid single-turn encoder value`는 경로 시작 전에 모터의 누적 위치가0~4095 밖으로 읽힌 경우다. 최근 원래 PC 기록에는 토크OFF 상태의 ID3=-1980틱이 있었다. 전원 재인가 후 시작 상태를 다시 확인하며, 자동으로4096을 더하거나 모드·한계를 바꾸지 않는다.

## 검증 범위와 남은 일

표준 노드 기본 무출력, 실기 플래그·자료 경로 검증, 실제 production 콜백의 완료/G 유지·오류·취소, 원래 가로/세로 목표열과 READ 복구는 장치 없는 시험으로 확인한다. 상위 GUI의 `dry_run=false` 전체 풀이 차단은 그대로이며 이 작업이 양손 실물 통합 완료를 뜻하지 않는다.

통합 PC의 ROS 빌드·실제 DDS 통신·모터 출력, 실제 큐브 회전/지지, 양손 간섭·하중·정지 시험은 결과를 별도로 기록한다. 관절 G 도달과 큐브 접촉/회전 성공은 구분한다. 기존 경로와 구현 상세는 [recorded-motion.md](recorded-motion.md)를 참고한다.
