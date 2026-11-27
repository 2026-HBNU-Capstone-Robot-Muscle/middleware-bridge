# 좌수 Custom Hand ROS 2 실행 및 실기 확인

`feature/hardware_left`는 미들웨어의 `custom_hand_primitive_server`에 좌수 실기 제어기를 연결합니다. 단독 시험에서는 `/custom_hand/execute_primitive` 액션으로 파지·회전·해제를 요청합니다. 기본 GUI에서 실행하는 두 손 큐브 풀이 경로는 dry-run입니다.

## 1. Windows 환경 설치

실기 코드가 포함된 미들웨어 브랜치의 저장소 루트에서 실행합니다. 새 환경은 설치 스크립트를 사용합니다.

```powershell
.\install.bat
```

기존 설치를 이번 브랜치의 의존성과 코드로 갱신할 때는 다음 두 명령을 사용합니다.

```powershell
pixi install --locked
pixi run --locked build-windows
```

`install.bat`은 Pixi 환경 설치와 ROS 패키지 빌드를 함께 수행합니다. `--locked`는 현재 `pixi.toml`과 `pixi.lock`이 일치할 때 해당 잠금 파일로 설치합니다. [Pixi 설치 옵션](https://pixi.sh/latest/reference/cli/pixi/install/)

## 2. 기본 GUI dry-run

저장소 루트에서 `./start.bat`을 실행해 GUI를 엽니다. 풀이가 준비되면 **DRY-RUN 실행**으로 단계 진행과 완료 또는 취소를 확인합니다. 종료는 `./stop.bat`으로 합니다.

## 3. 좌수 단독 실기 시험

GUI를 실행했다면 `./stop.bat`으로 종료합니다. 좌수 CLI나 별도 좌수 ROS 서버가 실행 중이면 종료해 COM8과 액션을 제어기 하나만 사용하게 합니다. 서버용과 요청용 PowerShell 창 두 개를 저장소 루트에서 엽니다. 각 창에서 `pixi shell` 실행 후 새 프롬프트가 뜨면 다음 줄을 실행합니다.

```powershell
pixi shell
. .\.colcon-win\install\local_setup.ps1
```

서버 창에서 실행합니다.

```powershell
ros2 run custom_hand_control custom_hand_primitive_server --ros-args -p hardware_enabled:=true -p allow_provisional:=true
```

`Ready: /custom_hand/execute_primitive hardware_enabled=True`가 표시되면 요청을 보낼 수 있습니다. 기본 모터 설정은 `config.provisional.json`의 COM8, 1 Mbps, 손가락 ID 1~4, 손목 ID 10입니다. `allow_provisional:=true`는 설치된 `primitive_calibration.local.json`의 `verified=false` 시험 보정값을 명시적으로 허용합니다. 별도 모터 설정이나 보정 파일이 필요하면 시작 명령에 각각 `-p "hardware_config:=절대경로"`, `-p "wrist_calibration:=절대경로"`를 추가합니다.

요청 창에서 한 줄씩 실행합니다. `$turns`는 `1`(시계 방향), `-1`(반시계 방향), `2`(반 바퀴) 중 하나를 선택합니다. 새 시험을 시작할 때는 이 블록을 다시 실행해 새 실행 ID를 만듭니다.

```powershell
$action = '/custom_hand/execute_primitive'
$actionType = 'system_interfaces/action/ExecuteHandPrimitive'
$execution = 'left-test-' + [guid]::NewGuid().ToString('N')
$turns = 1
$move = @{ '1' = 'U'; '-1' = "U'"; '2' = 'U2' }[[string]$turns]
$goal = "scan_id: bench, execution_id: $execution, move_index: 1, cube_move: $move, target_face: U, face_direction_order: URFDLB, target_face_direction_index: 0, dry_run: false"
ros2 action info $action
```

같은 실행 ID로 **파지 → 회전 → 해제**를 보냅니다. 각 명령의 결과가 `Goal finished with status: SUCCEEDED`이고 `success: true`일 때 다음 명령을 실행합니다.

```powershell
ros2 action send_goal $action $actionType "{$goal, step_index: 1, primitive_id: grasp_upper_layer, clockwise_quarter_turns: 0}" --feedback
ros2 action send_goal $action $actionType "{$goal, step_index: 2, primitive_id: rotate_upper_layer, clockwise_quarter_turns: $turns}" --feedback
ros2 action send_goal $action $actionType "{$goal, step_index: 3, primitive_id: release_upper_layer, clockwise_quarter_turns: 0}" --feedback
```

파지 성공을 응답한 뒤에도 Worker는 명목 30 ms 주기로 PPO 제어를 이어갑니다. 회전에서는 아래 손목 구간을 사용합니다. 각도는 손목에 명령하는 값입니다. 엔코더 성공 응답과 함께 실제 큐브의 파지 유지 및 레이어 회전도 확인합니다.

| 요청 | 손목 구간 | 중간 정지 |
| --- | --- | --- |
| `1` | 시계 방향 50° + 45° | 없음 |
| `-1` | 반시계 방향 50° + 50° | 없음 |
| `2` | 시계 방향 47.5° + 47.5° + 45° + 45° | 두 번째 구간 뒤 1초 |

해제는 손가락을 열고 손가락 토크 OFF를 확인한 뒤, 손목을 2400틱 기준 위치로 복귀시켜 손목 토크를 끕니다. 시험 종료는 서버 창에서 `Ctrl+C`를 누릅니다. `home`은 좌수 저장소의 CLI에서 실행하는 명령입니다.

### 로그 확인

기본 로그 폴더는 `~/.ros/log/custom_hand_control`입니다. `ROS_LOG_DIR`이나 `ROS_HOME`이 지정되어 있으면 해당 ROS 로그 위치를 사용합니다. `latest.json`에 적힌 세션 폴더의 `events.jsonl`과 `console.log`에서 실행 ID, 액션 결과, 제어기 오류를 확인합니다. `FAULT: restart required`는 서버가 오류 이후 새 실기 요청을 막았다는 뜻입니다. `STOP_UNCONFIRMED`가 뜨면 토크 OFF 확인이 실패한 장치를 로그에서 확인하고 실물 정지 상태를 확인합니다.

## 4. Pixi 두 파일을 함께 올리는 이유

두 파일 모두 이미 저장소에서 사용합니다. 이번 변경에서는 `pixi.toml`을 수정하고 `pixi.lock`을 함께 갱신합니다.

| 파일 | 변경 내용 |
| --- | --- |
| [`pixi.toml`](../pixi.toml) | 손가락·손목 시리얼 통신에 `pyserial==3.5`, 실기 PPO ZIP 로딩·추론에 `stable-baselines3==2.7.0`을 선언합니다. 기존 `torch==2.15.0`을 그대로 사용합니다. |
| [`pixi.lock`](../pixi.lock) | 위 두 라이브러리와 `gymnasium`, `cloudpickle`, `farama-notifications`, `pandas`의 버전 및 설치 파일을 기록합니다. 팀원이 같은 Windows 환경을 설치할 수 있도록 함께 커밋합니다. |

잠금 파일은 `pixi lock`으로 생성합니다. [Pixi 잠금 파일 안내](https://pixi.prefix.dev/latest/workspace/lock_file/#committing-your-lock-file)

실기 서버는 패키지에 설치된 `finger_robot_ppo_hardware.zip`을 설정에 기록된 SHA-256과 대조해 사용합니다. 기존 `finger_robot_ppo_best.zip`은 shadow 추론에 사용합니다. Pixi 명령은 실행에 필요한 환경을 준비하며, 실기 동작은 서버에 보낸 액션 요청으로 시작됩니다.

## 5. 확인 결과와 남은 보완

- **확인 완료** — 기존 Windows ROS 2/Pixi 환경에서 패키지 빌드, 설치 모델 해시와 PPO 추론, 좌수 dry-run 9개 요청 및 기본 모드의 실기 요청 거부를 확인했습니다. 두 손 풀이 dry-run은 13개 큐브 동작·52단계 완료, 실행 취소 및 없는 풀이 ID 거부를 확인했습니다. 모의 장치로 파지 성공 후 제어 지속과 같은 실행 ID의 회전·해제도 확인했습니다.
- **이식한 패키지의 실물 확인** — 기존 좌수 독립 ROS 서버 시험 결과를 기준으로, 미들웨어에 설치한 패키지에서 실제 파지 유지, 세 가지 회전 요청, 해제 후 손목 복귀 및 토크 OFF를 확인합니다. 다른 PC에서 처음 설치할 때는 `pixi install --locked`와 빌드도 확인합니다.
- **두 손 실기 연동** — LEAP Hand 실기 제어가 준비되면 좌수 오류가 발생했을 때 다음 단계 차단, 상대 손의 지지 유지 또는 정지, 재개 조건을 두 손 전체에서 검증합니다.

세부 모터·회전 설정은 [하드웨어 설정표](hardware-setting.md)에, 통합 시험과 남은 작업은 [미완료 목록](incomplete.md)과 [실물 통합 작업 지시](TODO.md)에 정리했습니다.
