# 오른손 실물 기록과 미들웨어 연결 상태

갱신일2026-11-24. 저장된 코드·로그를 읽어 문서를 갱신했으며 이 업로드 작업에서 장치를 열지 않았다.

## 확보한 기록

| 항목 | 원래 PC에서 확인한 내용 | 근거 |
|---|---|---|
| 버스 | COM7 /1Mbps /Dynamixel Protocol2.0 | 11/9 읽기 전용 inventory와11/13 실행 기록 |
| 장치 | ID1–16 응답 모델1240, 펌웨어53 | inventory /fast_read_live_firmware |
| 관절 | 손끝→손바닥: TH1/2/3/4, IF5/7/6/8, MF9/11/10/12, RF13/15/14/16 | 사용자 확인·hand_motor_mapping.py·실행 기록 |
| 구동 계약 | 450mA, 기존 PID, 최대2틱/75ms, 목표 확인·건강/추종/통신 감시 | 검증한 저장 경로 실행기 |
| 위치 PID 기록 | 11/13 preflight 읽기값 P2100/I0/D1900, 16개 모두 동일 | 근거 JSON. 원본 deploy KP600/KD200과 단위·구현을 구분 |
| 영상 | 오른손 기록 장치 Streaming Webcam/DSHOW, 1280×720 | 실행 결과 camera_startup |
| 종료 | 최근 두 통신 중단 실행의 토크 OFF와 설정 복구 True | 근거 JSON recent_runs |

수치와 원본 SHA256은 [근거 JSON](evidence/right_hand_20261116.json)에 있다. 담당 범위는 오른손 기록이며 왼손·손목 검증 상태를 변경하지 않았다.

## 원본 코드와 자료 위치

- [공유 코드 기준본](https://github.com/2026-HBNU-Capstone-Robot-Muscle/right_rl_with_mujoco/tree/76a2438147207978ecf972d54a0904edb1180ea6/hardware/right_hand): 원본 코드·모델·학습/실험 기록 패키지22,022개 파일을 공유한 커밋.
- [모터 대응](https://github.com/2026-HBNU-Capstone-Robot-Muscle/right_rl_with_mujoco/blob/76a2438147207978ecf972d54a0904edb1180ea6/hardware/right_hand/hand_motor_mapping.py).
- [11/24 후속 공유본](https://github.com/2026-HBNU-Capstone-Robot-Muscle/right_rl_with_mujoco/tree/feature/hardware/hardware/right_hand)의 README와 저장소 루트 `RIGHT_HAND_UPDATE_20261124_MANIFEST.json`에서 이후 코드·실험 기록과 해시를 확인한다. 위11/12 고정 커밋은 당시 스냅샷이다.
- Windows 실행 쪽 의존성은 기준본의 requirements-leap.txt를 참고한다. 설치된 .runtime과 WSL 학습 환경은 저장소 자료와 별도로 준비한다.

## 미들웨어에 연결할 계약

1. 단일 I/O 소유자가 해당 COM 포트를 열고 최신 joint 상태·오류·timestamp를 발행한다.
2. 저장 경로 재생과 정책 추론을 명시적으로 구분한다. 원본108차원 정책과 로컬110차원 위상 포함 보정 정책의 입력을 섞지 않는다. 현재 실물 명령은 저장 경로 재생이다.
3. orient_face_up_and_support 완료 응답 이후에도 오른손 지지와 건강 감시가 살아 있어야 한다. 왼손 파지→회전→해제 중 유지하고, 다음 회전/종료 요청으로 상태를 전환한다.
4. 다음 primitive 진입은 실제 완료 판정 후 허용한다. 명령 발행만으로 큐브 자세·면 상태를 성공 값으로 갱신하지 않는다.
5. 중앙 칸 색 추출과 중앙 ArUco 마커가 겹치는 문제는 인식 팀과 배치·관측 계약을 합의한다. 초기 면 상태와 성공한 회전에 따른 논리 상태 갱신, 실제 cube pose 관측을 구분한다.

## 2026-11-16 ROS 어댑터 코드와 읽기 연결

- [오른손 어댑터](leap-adapter.md)에 실제 motor ID 변환, ROS 측정/목표 상태 발행, mock 동작 완료·취소·지지 유지 계약을 구현했다. 기존 primitive 검증을 재사용하며 `dry_run=false` 차단은 유지한다.
- 새 SDK READ-only backend로 원래 PC COM7/1Mbps의16개 모델1240 상태를2회 읽었고 포트를 닫았다. 목표 쓰기·토크 변경0회다. 근거는 `results/leap_adapter/read_only_20261116_071155_761082.json`이다.
- 실제 ROS/DDS 실행과 실제 모터 출력 backend 연결은 아직 완료하지 않았다. 어댑터·통합 실행기의 장치 없는 시험39개를 통과했다.

## 2026-11-24 실행파일과 검증 구분

- `leap_measured_grip_hold.cmd`: 사용자 실측 확정 파지 G로 이동·유지.
- `leap_grip_rotate_grip.cmd`: G→가로 회전→G. `leap_vertical_direct_grip.cmd`: G→세로 회전→G 계속 유지. 두 단독 동작에서 G 복귀 관찰을 확보했다.
- `leap_two_axis_cycle.cmd`: 한 제어기에서 G→가로→G약10초→세로→G계속유지. 중간 OFF/확인 SPACE 없이 원본 목표열을 연결했으며 소프트웨어10검사 통과. 두 회전 연속 실물 성공은 미확인이다.
- 현재 회전 실행은 1배75ms·최대2틱·450mA·기존PID와 건강/추종/통신 감시를 쓴다. 최신 세로 복귀는 불필요한 엄지 후퇴 없이 엄지 먼저 내림→기록한1번·2번→G다.
- 미들웨어의 어댑터·실행 계약·정책 입력·마커 없는 pose 모듈을 포함한 장치 없는 시험은11/24 전체103개 통과했다. ROS 메시지/전송 대역을 쓴 소프트웨어 시험이며 실제 ROS/DDS·모터 출력 backend·양손 통합을 검증한 수치가 아니다.

## 마지막: 남은 문제와 검증

- 통합 PC의 포트·USB 어댑터·전원·배선·영점/부호·기계 한계와 독립 비상 정지 검증이 남아 있다. 기록의 COM7을 다른 PC에 고정하지 않는다.
- 11/13 04:19 실행은 초기 파지에서, 04:27 실행은 큐브 배치 대기 중 통신 -3002로 중단됐다. 후자는356바이트 기대 응답 대신192/17/302바이트를 받았다. 특정 모터 고장이나 USB 단독 원인으로 단정하지 않는다.
- 초기 엄지 끝–검지 뿌리 모델 겹침의 제한적 처리 후 저장 자세3개 × 정적201/동적9, 실행기18/예외7시험을 통과했다. 이후 실물 통신 중단과는 다른 문제이며 전체 경로 성공 인증이 아니다.
- 최신 세로 `vertical_direct_grip_trial_20261124_081445_872143`은 G 유지에 도달한 뒤 상태 읽기 오류로 종료됐고 OFF·설정복구 확인도 실패했다. 앞선 정상 종료 기록과 구분하며 통신 원인을 확정하지 않는다.
- 가로→G→세로→G의 연속 실물 실행과 반복, 실제 윗단 회전 하중·양손 간섭 통합은 검증이 남아 있다. G 전용 실행파일 준비와 단독 복귀 관찰을 전체 연속 성공으로 표시하지 않는다.
- ROS 실제 목표 전송 backend·실측 policy shadow·cube/hand pose·상위 지지 heartbeat 감시와 실물 완료 판정이 남아 있다. 상태 읽기·발행 및 mock 완료/취소 계약은 위 항목을 참고한다. middleware의 dry-run 차단과 calibration verified 필드는 변경하지 않았다.
