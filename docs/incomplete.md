# 실물 구동 전 미완료 항목

## 현재 상태

기본 양손 서버와 상위 실행기는 dry-run을 유지합니다.11/24 별도 `recorded` 오른손 backend에 원본 경로 구동과 사용자 색 관찰 기반 목표 면 선택을 연결했습니다. 명시적 활성화 후 G/가로/세로 및 현재 방향을 명시한 목표 면 액션을 처리하며,기존 GUI 전체 실기 실행은 계속 차단합니다. [recorded-motion.md](recorded-motion.md)와 [방향 대응](recorded-orientation.md)에 코드·가상 모터 검사와 남은 실제 ROS/실물 검증을 구분했습니다. 이번 보조자 작업에서 실제 장치를 움직이지 않았습니다.

## 2026-11-16 추가로 확보한 오른손 기록

원래 PC의 COM7·1Mbps, ID1–16 모델1240/펌웨어53, 최신 대응과 실행·종료 기록을 [right-hand-status.md](right-hand-status.md)에 반영했다. 이 기록 확보와 현재 middleware PC 검증 완료는 구분한다. 원본 로그 기반 값과 최근 통신 중단은 [근거 JSON](evidence/right_hand_20261116.json)에 있다.

## 2026-11-17 Custom Hand 실기 기록 반영

좌수 `develop/chu`의 CLI 파지·손목 회전·해제·초기 복귀를 사용자가 실기 확인했다. 현재 모터 설정과 손목 기준은 [hardware-setting.md](hardware-setting.md)와 [좌수 실기 문서](https://github.com/2026-HBNU-Capstone-Robot-Muscle/left-rl-with-mujoco/blob/develop/chu/docs/primitive_README.md)에 정리했다. 이 결과는 ROS 액션 또는 양손 통합 실기 성공을 뜻하지 않는다.

## 미완료 항목과 구동 차단 사유

| 우선순위 | 항목 | 확인된 참고 정보 | 완료에 필요한 자료·작업 |
|---|---|---|---|
| P0 | LEAP Windows 연결 정보 | 원래 PC의 COM7·1Mbps·ID1–16 실측 기록 확보 | 통합 PC의 COM 포트·USB 어댑터·현재 조립 inventory를 대조한다. 3Mbps 변경을 전제로 하지 않는다. 최근 -3002 불완전 응답의 원인과 장시간 통신 안정성은 검증이 남음 |
| P0 | LEAP 모터/control-table 일치 | 11/9 ID1–16 모델1240, 11/13 펌웨어53 응답 및 실제 실행 telemetry 기록 확보 | 현재 통합 rig에서도 식별하고 XC330 주소·단위·전류/속도 scale과 adapter 호환성을 대조. 과거 읽기 성공을 현재 전체 구동 승인으로 쓰지 않음 |
| P0 | LEAP 관절 매핑·부호 | 후속 실물 순서 `(8,6,7,5,12,10,11,9,16,14,15,13,4,3,2,1)` 및 사용자 확인 기록 확보 | 최신 대응을 adapter에 적용하고 현재 조립의 영점·방향·충돌 없는 범위 대조. 시뮬 범위를 실물 한계로 승인하지 않음 |
| P0 | Custom 손가락 calibration | 좌수 CLI 실기 구동 사용자 확인. COM8/1Mbps, 초기 위치 ID1=1299·ID2=2749·ID3=2378·ID4=2292와 접힘 설정 705/2000/1700/1700틱 기록 | 통합 PC 포트·ID·모델/펌웨어, ID3 손가락 대응, 영점·변환 및 기계적 한계·정지 동작을 확인한다. 접힘 설정을 기계적 한계로 간주하지 않는다 |
| P0 | Custom 손목 구동 | 좌수 CLI에 STS3215 ID10 제어 구현. 기준 2400틱·시계 방향 틱 감소·구간 회전 및 재파지 실기 사용자 확인 | 통합 PC의 포트·통신·완료/정지 동작을 확인하고 ROS action에 제어기를 연결해 실기 시험한다 |
| P0 | 큐브와 손의 pose/frame | middleware에 실측 `/cube/pose`, `/leap_hand/palm_pose`, transform publisher 없음. 카메라 모델도 미정 | pose provider, 공통 `frame_id`, 카메라/robot extrinsics, 초기 URFDLB 면 대응, 갱신·stale 기준 및 LEAP palm-to-cube pose 구현·측정 |
| P0 | LEAP 실제 정책 입력 | 참조 `policy_runner.py`는 `--cams`를 요구하고 손 관절 측정, cube quaternion·palm 위치로 108차원 관측을 만듦. 무카메라 상태는 명령에 쓰지 말라고 코드에 명시 | 카메라/pose provider를 고르고 middleware 입력 토픽과 관측 이름·순서·단위·timestamp를 연결한 뒤 실측 shadow 비교 |
| P0 | Custom 정책 실측 observation | 좌수 CLI에서 모터 위치·속도를 정책 입력 8개로 변환하고 정책 출력 4개를 위치 명령으로 사용 | 통합 환경에서 변환 순서·부호·단위와 실측 입력을 대조하고, 참조 모델과 middleware shadow 결과를 비교한다 |
| P0 | 정책 실행주기와 primitive 의미 | 원본 LEAP 정책50ms, 현재 오른손 저장 경로 재생75ms/최대2틱, Custom 기본30ms | backend별 주기·관측 이력·목표 의미를 분리. 도달 응답 이후 오른손 지지가 계속되도록 수명·완료/취소/timeout 규약을 결정 |
| P0 | Middleware motor driver | 오른손 READ-only 및 별도 recorded backend·목표 면 경로 선택·단일 I/O 소유자·상태 발행을 구현. hardware extra에 SDK4.1.0 고정. 기본 서버/상위 풀이와 왼손은 dry-run | 팀 ROS 환경에서 설치·포트·모터 동작을 확인. 상위의 완료 방향 상태 소비/실제 지지 감시,왼손 backend와 전체 calibration 조건 연결은 남음 |
| P0 | 완료 판정과 handoff | 현재 dry-run 성공은 adapter 응답이며 실물 관절 도달·grasp/support·큐브 회전 확인이 아님 | 관절 추종 오차·정착 시간, 큐브 방향/레이어 회전, LEAP 지지와 Custom grasp/release를 확인할 계측과 기준을 정의하고 실패 시 다음 primitive 차단 |
| P0 | 안전 정지·기계 한계 | `hardware_calibration.example.json`의 emergency stop, stop behavior, joint/workspace limits, completion feedback, handoff 검증이 모두 false | 독립 비상정지, torque-off/hold 동작, 작업공간·속도·전류 한계, 통신 단절·stale 상태 동작, 큐브 낙하·끼임 대응과 회수 절차를 실제 장치에서 검증·기록 |
| P1 | Custom 실기 코드와 middleware 모델 실행 호환성 | 현재 실기 ZIP 해시 BE90522E…와 middleware ZIP 해시 5B9A3F36…는 다름 | 실기 모델·설정 해시를 맞추고 Windows ROS 환경의 SB3 로딩, 입출력 좌표 및 기존 shadow 경로 호환성을 검증한다 |
| P1 | LEAP bus/platform 차이 | 참조 `dynamixel_client.py`는 Linux deploy 경로와 3 Mbps 기본값 사용, `leap_hw.py`는 sysfs FTDI latency timer 확인 시도 | Windows native에서 Dynamixel SDK port handler, latency 설정, serial close 및 torque-off가 기대대로 작동하는지 검사. Linux 경로를 그대로 사용하지 않음 |

## 단계별 해제 조건

1. **Read-only 식별:** 각 독립 bus에서 포트, baud, model number, ID, mode, torque state와 hardware error를 읽고 설정표에 실제값을 기록합니다. 어떤 write도 하지 않습니다.
2. **관절별 무부하 확인:** 실제 비상정지 준비 후 torque-off에서 시작하고, 승인된 제한으로 한 motor/joint씩 방향과 zero를 측정합니다. 결과를 calibration 파일에 기록합니다.
3. **Policy shadow 비교:** 실측 관절·pose 입력을 ROS 토픽에 발행해 middleware와 reference observation/action을 같은 시점에서 비교합니다. motor output은 계속 끕니다.
4. **단일 actuator 구동:** 안전 검증이 끝난 뒤 한 손가락 또는 한 축만 낮은 제한으로 시험하고 command, feedback, stop을 확인합니다. 전 단계 통과 전에는 양손·손목을 함께 활성화하지 않습니다.
5. **Primitive·handoff 검증:** LEAP support, Custom grasp/rotate/release를 큐브 없는 조건부터 단일 큐브 조작까지 순서대로 검증합니다. 완료 feedback과 안전 정지가 확인된 뒤에만 전체 action을 고려합니다.

모든 `verified` 필드와 증거가 실제 측정·시험으로 채워지고 SDK·pose·safety 조건이 충족되기 전까지 middleware는 `dry_run=false`를 받아들이지 않아야 합니다. 저장된 참고 설정만 복사하거나 calibration 표시만 true로 바꾸는 것은 구동 허가 근거가 되지 않습니다.
