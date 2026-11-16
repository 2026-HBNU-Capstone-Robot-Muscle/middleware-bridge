# 하드웨어 연결 설정

이 문서는 `left-rl-with-mujoco/sim2real`과 `right_rl_with_mujoco/deploy`의 실기 코드를 확인해 기록한 하드웨어 설정 후보입니다. 소스 코드의 포트·게인·제한은 해당 실기 환경의 설정이며, 현재 middleware PC와 조립 상태에서 검증된 값이라고 간주하지 않습니다. 이 저장소의 ROS primitive server는 아직 하드웨어 출력을 연결하지 않으며 `dry_run=false`도 허용하지 않습니다.

## 2026-11-16 오른손 기록 반영

오른손 후속 실물 기록의 **COM7 / 1 Mbps / ID 1–16 / 모델 응답1240 / 펌웨어53 / 최신 관절 대응**을 반영했다.
기록은 원래 PC의 2026-11-09·13 조립 조건에서 얻은 것으로, 현재 middleware PC의 calibration 승인과 구분한다.
출처와 남은 연결 작업은 [오른손 상태](right-hand-status.md), 검사한 값·원본 해시는 [근거 JSON](evidence/right_hand_20261116.json)에 있다.

## 하드웨어 연결 요약

| 장치 | 모터/모델 | 참조 포트 | 통신 속도 | 모터 ID | 제어 및 소스 설정 | 현재 확인 상태 |
|---|---|---|---:|---|---|---|
| LEAP Hand 손가락 | 사용자 모델 XC330-M288, ID1–16 모델 응답1240·펌웨어53 기록 | 원래 Windows PC `COM7` | **1,000,000 bps (실물 기록)** | 1–16 | Protocol 2.0, 450mA, 최대2틱/75ms 경로 재생. 11/13 위치 PID 읽기값 P2100/I0/D1900을 기록; 적용 단위와 현재 PC 설정은 별도 대조 | 원래 PC inventory·매핑·실행 기록 확보. 현재 통합 PC의 연결·부호·기계 한계와 통신 안정성 검증은 남음 |
| Custom Hand 손가락 | Dynamixel XL330-M288-T | `COM8` (`sim2real/apply_policy.py`에 지정) | 1,000,000 bps | right=4, front=1, left=2, back=3 | Dynamixel Protocol 2.0, mode 5, Drive Mode 0. preflight는 watchdog=0, 토크 OFF, secondary ID=255, status return level=2 및 모델 번호 1200을 요구. 정책 주기 기본 30 ms | 사용자가 참조 실기 코드의 실제 구동을 확인했다고 보고. 다만 config의 mapping·timing·stop·단일 모터 검증 표시는 모두 false이며 모델 번호는 null |
| Custom Hand 손목 | Feetech STS3215 (사용자 제공 모델) | 미확인 | 미확인 | 미확인 | `left-rl-with-mujoco/sim2real`의 해당 실기 코드는 손가락 Dynamixel만 다루고 손목 제어를 제외 | 실기 드라이버·관절/회전축 매핑 없음 |
| 인식 카메라 | 현재 모델 미정 | 사용자가 시험한 OpenCV `camera_index=0`, `dshow` | 해당 없음 | 해당 없음 | 관측 로그의 영상 크기 1280×720, 30 FPS. 이 설정은 2D 검출 시험값이며 3D pose 보정값은 아님 | 카메라 제조사·모델·내부/외부 보정 및 로봇 frame 변환 미확인 |

## Custom Hand 손가락 매핑 후보

아래 ID·tick 값은 `left-rl-with-mujoco/sim2real/config.provisional.json`의 후보 설정입니다. 설정 파일 자체가 `mapping_verified=false`, 각 모터의 `model_number=null`, limits 항목 미기록 상태이므로 실기 보정값이나 안전 한계로 사용하지 않습니다.

| 손가락 | Dynamixel ID | 초기/open3 tick 후보 | close3 tick 후보 | 보정 상태 |
|---|---:|---:|---:|---|
| right | 4 | 2670 | 2273 | provisional, 미검증 |
| front | 1 | 778 | 339 | provisional, 미검증 |
| left | 2 | 2897 | 2365 | provisional, 미검증 |
| back | 3 | 2669 | 2190 | provisional, 미검증 |

실기 코드의 `apply_policy.py`는 `COM8`, 1 Mbps로 연결하고 모터 inventory와 운용 조건을 검사합니다. 목표 전류는 최대 700 mA와 장치 설정 한계 중 낮은 값으로 제한합니다. 위치 보정은 최대 200 tick 기본값을 갖지만, 이는 조립의 기계적 한계 검증을 대체하지 않습니다. README에 있는 P/I 게인·profile velocity/acceleration·보정 조합은 시험 예시이며 middleware의 확정 설정으로 복사하지 않았습니다.

middleware에 보관한 Custom PPO 파일과 참조 파일의 SHA-256은 모두 다음과 같이 일치합니다.

`5B9A3F36B348FA7FCC16370432E9F5CE476091CBEE38431686166FFABABD426B`

## LEAP Hand 후속 실물 관절 대응

아래 motor ID는 `hand_motor_mapping.py`와 11/13 실물 실행 기록의 최신 대응이다.
손끝→손바닥은 엄지1/2/3/4, 검지5/7/6/8, 중지9/11/10/12, 약지13/15/14/16이다.
시뮬레이션 좌표는 `qsim=(ticks-2048)*2π/4096`이며, 원본 정책 좌표·관측 계약과의 대조는 별도 수행한다.
기존 deploy 후보 순서 `(15,16,14,13,11,12,10,9,7,8,6,5,4,3,2,1)` 및3Mbps 기본값으로 되돌리지 않는다.
표의 각도 범위는 기존 시뮬레이션 후보 범위로 보존하며 실물 한계 승인을 뜻하지 않는다.

| 학습 관절 순서 | 후속 실물 motor ID | 기존 시뮬 후보 범위 (rad) | 통합 시 확인 |
|---|---:|---:|---|
| `if_mcp` | 8 | -0.314 .. 2.230 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `if_rot` | 6 | -1.047 .. 1.047 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `if_pip` | 7 | -0.200 .. 1.885 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `if_dip` | 5 | -0.200 .. 2.042 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `mf_mcp` | 12 | -0.314 .. 2.230 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `mf_rot` | 10 | -1.047 .. 1.047 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `mf_pip` | 11 | -0.200 .. 1.885 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `mf_dip` | 9 | -0.200 .. 2.042 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `rf_mcp` | 16 | -0.314 .. 2.230 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `rf_rot` | 14 | -1.047 .. 1.047 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `rf_pip` | 15 | -0.200 .. 1.885 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `rf_dip` | 13 | -0.200 .. 2.042 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `th_cmc` | 4 | -0.349 .. 2.094 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `th_axl` | 3 | -0.470 .. 2.443 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `th_mcp` | 2 | -1.200 .. 1.900 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |
| `th_ipl` | 1 | -1.340 .. 1.880 | 대응 기록 확보; 영점·부호·기계 한계는 통합 PC에서 대조 |

각도 범위는 `deploy/limits.py`의 학습·시뮬 안전 범위입니다. 실제 기구 한계나 충돌 없는 범위로 검증되지 않았습니다. 참조 hardware adapter는 mode 5를 설정하고 torque enable 전에 현재 위치를 목표로 써서 급격한 이전 목표 추종을 피하려 합니다. 이 초기화 동작만으로 실물의 안전이 입증되는 것은 아닙니다.

LEAP middleware 정책 파일 `policy_np.npz`와 `right_rl_with_mujoco/policy/policy_np.npz`의 SHA-256은 모두 다음과 같이 일치합니다.

`DC220D146BC5532C4AE09907C6D6BBC887335389D215AFAAFB69EEAB679560E7`

오른손 촬영 기록에는 별도 USB `Streaming Webcam`, DSHOW, 1280×720 영상이 있다. middleware 인식 카메라와 동일 장치·동일 보정이라고 가정하지 않는다.

## 참고 소스

- [Custom Hand 실기 README](../../left-rl-with-mujoco/sim2real/README.md)
- `left-rl-with-mujoco/sim2real/apply_policy.py`, `bus.py`, `core.py`, `config.provisional.json`
- `right_rl_with_mujoco/deploy/leap_hw.py`, `limits.py`, `policy_runner.py`, `check_joints.py`, `leap_hand_utils/dynamixel_client.py`
- middleware 설정: `src/control/cube_execution/config/hardware_calibration.example.json`

위 소스의 수치는 재현을 위한 참고값입니다. 실제 port·모터 모델 응답·ID·배선·frame을 확인하고 calibration을 기록하기 전에는 ROS에서 모터 출력을 활성화하지 않습니다.
