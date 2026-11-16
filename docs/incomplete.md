# 실물 구동 전 미완료 항목

## 현재 상태

실기 코드를 확인해 모터 모델 후보, 참조 포트·속도, motor ID 매핑과 정책 주기를 `hardware-setting.md`에 정리했습니다. 하지만 **middleware의 두 hand action server는 아직 dry-run 전용**이고 실제 motor write path가 없습니다. `dry_run=false` 요청은 계속 거부됩니다. 이번 변경은 하드웨어를 움직이지 않았으며, 실물 구동 준비 정보와 차단 사유를 정리한 단계입니다.

## 2026-11-16 추가로 확보한 오른손 기록

원래 PC의 COM7·1Mbps, ID1–16 모델1240/펌웨어53, 최신 대응과 실행·종료 기록을 [right-hand-status.md](right-hand-status.md)에 반영했다. 이 기록 확보와 현재 middleware PC 검증 완료는 구분한다. 원본 로그 기반 값과 최근 통신 중단은 [근거 JSON](evidence/right_hand_20261116.json)에 있다.

## 미완료 항목과 구동 차단 사유

| 우선순위 | 항목 | 확인된 참고 정보 | 완료에 필요한 자료·작업 |
|---|---|---|---|
| P0 | LEAP Windows 연결 정보 | 원래 PC의 COM7·1Mbps·ID1–16 실측 기록 확보 | 통합 PC의 COM 포트·USB 어댑터·현재 조립 inventory를 대조한다. 3Mbps 변경을 전제로 하지 않는다. 최근 -3002 불완전 응답의 원인과 장시간 통신 안정성은 검증이 남음 |
| P0 | LEAP 모터/control-table 일치 | 11/9 ID1–16 모델1240, 11/13 펌웨어53 응답 및 실제 실행 telemetry 기록 확보 | 현재 통합 rig에서도 식별하고 XC330 주소·단위·전류/속도 scale과 adapter 호환성을 대조. 과거 읽기 성공을 현재 전체 구동 승인으로 쓰지 않음 |
| P0 | LEAP 관절 매핑·부호 | 후속 실물 순서 `(8,6,7,5,12,10,11,9,16,14,15,13,4,3,2,1)` 및 사용자 확인 기록 확보 | 최신 대응을 adapter에 적용하고 현재 조립의 영점·방향·충돌 없는 범위 대조. 시뮬 범위를 실물 한계로 승인하지 않음 |
| P0 | Custom 손가락 calibration | 사용자는 참조 실기 코드의 실제 구동을 확인했다고 보고함. 코드에는 `COM8`/1 Mbps와 right/front/left/back → ID 4/1/2/3 후보가 있음. 참조 config의 mapping·limits 검증은 false이고 모델 번호는 null | middleware PC/현재 조립에서 실제 포트·ID·model number를 확인하고, 해당 rig에서 각 모터 영점, open/close tick, 방향, 기계 한계, 전류·온도·추종오차 한계와 검증 근거를 기록 |
| P0 | Custom 손목 구동 | 사용자 제공 모델은 Feetech STS3215. 참조 `sim2real`은 손목을 제외 | 실제 COM 포트, baud, protocol/SDK, motor ID, 축·부호·영점·범위, 속도/가속도·완료 feedback과 safe-stop 동작 확인 후 별도 adapter 구현 |
| P0 | 큐브와 손의 pose/frame | middleware에 실측 `/cube/pose`, `/leap_hand/palm_pose`, transform publisher 없음. 카메라 모델도 미정 | pose provider, 공통 `frame_id`, 카메라/robot extrinsics, 초기 URFDLB 면 대응, 갱신·stale 기준 및 LEAP palm-to-cube pose 구현·측정 |
| P0 | LEAP 실제 정책 입력 | 참조 `policy_runner.py`는 `--cams`를 요구하고 손 관절 측정, cube quaternion·palm 위치로 108차원 관측을 만듦. 무카메라 상태는 명령에 쓰지 말라고 코드에 명시 | 카메라/pose provider를 고르고 middleware 입력 토픽과 관측 이름·순서·단위·timestamp를 연결한 뒤 실측 shadow 비교 |
| P0 | Custom 정책 실측 observation | 참조 실기 코드는 모터 tick/velocity를 4개 policy position/velocity로 변환하지만 mapping과 endpoints는 provisional | 실측 tick↔policy 좌표·부호·영점·속도 변환 확인. middleware 입력 topic을 연결하고 참조 모델과 동일한 8차원 observation 및 4차원 action을 shadow 비교 |
| P0 | 정책 실행주기와 primitive 의미 | 원본 LEAP 정책50ms, 현재 오른손 저장 경로 재생75ms/최대2틱, Custom 기본30ms | backend별 주기·관측 이력·목표 의미를 분리. 도달 응답 이후 오른손 지지가 계속되도록 수명·완료/취소/timeout 규약을 결정 |
| P0 | Middleware motor driver | 현재 action servers는 validation 후 dry-run 결과를 반환. `pixi.toml` 및 ROS package manifests는 Dynamixel SDK, pyserial, Feetech SDK를 직접 의존성으로 선언하지 않음 | Windows ROS 환경에서 선택한 driver/SDK를 고정·설치하고 포트 권한·baud·실패 동작을 확인. port별 독립 I/O node, 상태 publisher, command adapter를 구현하고 calibration gate와 연결 |
| P0 | 완료 판정과 handoff | 현재 dry-run 성공은 adapter 응답이며 실물 관절 도달·grasp/support·큐브 회전 확인이 아님 | 관절 추종 오차·정착 시간, 큐브 방향/레이어 회전, LEAP 지지와 Custom grasp/release를 확인할 계측과 기준을 정의하고 실패 시 다음 primitive 차단 |
| P0 | 안전 정지·기계 한계 | `hardware_calibration.example.json`의 emergency stop, stop behavior, joint/workspace limits, completion feedback, handoff 검증이 모두 false | 독립 비상정지, torque-off/hold 동작, 작업공간·속도·전류 한계, 통신 단절·stale 상태 동작, 큐브 낙하·끼임 대응과 회수 절차를 실제 장치에서 검증·기록 |
| P1 | Custom 실기 코드와 middleware 모델 실행 호환성 | 현재 middleware Custom checkpoint hash는 참조 `.zip`과 일치. 참조 실기 앱은 Stable-Baselines3와 별도 bus/position-compensation 경로 사용 | Windows 환경의 SB3/모델 로딩과 실제 input/output 좌표를 비교하고, 보정 기능을 사용할지·어떤 제한을 둘지 결정. 참조 설정을 검증 없이 복사하지 않음 |
| P1 | LEAP bus/platform 차이 | 참조 `dynamixel_client.py`는 Linux deploy 경로와 3 Mbps 기본값 사용, `leap_hw.py`는 sysfs FTDI latency timer 확인 시도 | Windows native에서 Dynamixel SDK port handler, latency 설정, serial close 및 torque-off가 기대대로 작동하는지 검사. Linux 경로를 그대로 사용하지 않음 |

## 단계별 해제 조건

1. **Read-only 식별:** 각 독립 bus에서 포트, baud, model number, ID, mode, torque state와 hardware error를 읽고 설정표에 실제값을 기록합니다. 어떤 write도 하지 않습니다.
2. **관절별 무부하 확인:** 실제 비상정지 준비 후 torque-off에서 시작하고, 승인된 제한으로 한 motor/joint씩 방향과 zero를 측정합니다. 결과를 calibration 파일에 기록합니다.
3. **Policy shadow 비교:** 실측 관절·pose 입력을 ROS 토픽에 발행해 middleware와 reference observation/action을 같은 시점에서 비교합니다. motor output은 계속 끕니다.
4. **단일 actuator 구동:** 안전 검증이 끝난 뒤 한 손가락 또는 한 축만 낮은 제한으로 시험하고 command, feedback, stop을 확인합니다. 전 단계 통과 전에는 양손·손목을 함께 활성화하지 않습니다.
5. **Primitive·handoff 검증:** LEAP support, Custom grasp/rotate/release를 큐브 없는 조건부터 단일 큐브 조작까지 순서대로 검증합니다. 완료 feedback과 안전 정지가 확인된 뒤에만 전체 action을 고려합니다.

모든 `verified` 필드와 증거가 실제 측정·시험으로 채워지고 SDK·pose·safety 조건이 충족되기 전까지 middleware는 `dry_run=false`를 받아들이지 않아야 합니다. 저장된 참고 설정만 복사하거나 calibration 표시만 true로 바꾸는 것은 구동 허가 근거가 되지 않습니다.
