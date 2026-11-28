# 마커 없는 큐브 위치·방향 입력부

2026-11-16. `feature/hardware`에 구현했다. 큐브 중앙 마커는 사용하지 않으며 손목 ID41은 손 좌표를 관측할 때만 사용한다. 이 노드는 모터 명령·토크·PID를 쓰지 않는다.

## 처리 경로

1. 기존6면 촬영·색상/큐브 상태 검증에 성공하면 `/cube/color_reference`로 URFDLB 순서의 중심색을 발행한다. 새 촬영을 시작하거나 검증이 실패하면 이전 색 기준을 무효화한다.
2. 기존 YOLO OBB는 탐색 영역으로만 쓴다. 영상의 색 경계와 스티커 중심7개 이상으로3×3 격자의 원근 변환을 맞춘다. 스티커 폭이나 OBB 직사각형을 실제55mm 면으로 간주하지 않는다.
3. 두 면 이상을 중심색으로 식별하고, 각 면의 네 모서리 대응을 모두 비교해 큐브 중심과 방향을 계산한다. 한 면만 보이면90도 방향 모호성을 이유로 거부한다.
4. 재투영 오차·깊이·가려진 면 방향·복수 해를 검사한다. 노출 시각이 정확히 같은 영상/검출 결과만 짝지으며 기존150ms 신선도 내에서 계산을 끝내야 한다. 실패한 표본이나 이전 pose를 새 시각으로 다시 발행하지 않는다.

현재 색 면 좌표는 중심 원점, R=+X, U=+Y, F=+Z이다. 카메라 광학 좌표는 +X오른쪽,+Y아래,+Z전방이다. 색 면 좌표와 학습 큐브 축은 명시적인 변환으로 연결한다.

## 토픽

| 토픽 | 의미 |
|---|---|
| `/camera/image_raw` | 기존 카메라 소유 노드가 발행하는 Image |
| `/cube/face_detections` | 같은 원본 시각의 기존 YOLO FaceDetectionArray |
| `/cube/color_reference` | 새 CubeColorReference, 유효한6면 촬영에서 얻은 중심색 |
| `/cube/pose_camera_candidate` | 카메라 좌표의 색 면 큐브 자세 후보. 정책 입력이 아님 |
| `/cube/pose_wrist_candidate` | 현재 손목 마커 기준 큐브 상대 자세 후보. 고정된 외부 좌표 없이 비교 가능하며 정책 입력은 아님 |
| `/cube/pose_status` | 후보/정책 좌표 유효성, 오차, 시각, 거부 이유 |
| `/cube/pose` | 등록을 검증한 경우의 학습 큐브 좌표 |
| `/leap_hand/palm_pose` | 같은 노출 시각의 학습 손바닥 센서 위치·방향 |

정책용 두 pose는 다음 조건을 전부 충족할 때만 발행한다.

- 현재 물리 카메라에 대응하는 내부 보정, 영상 해상도, 보정 파일 SHA256 확인
- `world_from_camera`: 카메라에서 학습 world로의 좌표 등록
- `wrist_from_palm_sensor`: 손목 마커에서 학습의 **palm_position 센서**로의 변환
- `color_cube_from_policy_cube`: 색으로 정의한 큐브 축과 학습 큐브 축의 대응
- 손목 마커가 보이고 그 자세에 모호성이 없음

변환의 길이 단위는 m다. `wrist_from_palm_sensor`에 손 본체 원점이나 옛 grasp_site 후보를 대신 넣지 않는다. 중앙 마커를 없애는 것은 실제 위치·미끄러짐 관측을 없애는 것과 다르다.

## 실행

새 메시지 `CubeColorReference`가 있으므로 기존 Pixi/ROS 빌드를 다시 수행하고 overlay를 불러온다. 기존 카메라 노드와 detector를 사용하며 새 노드는 카메라를 직접 열지 않는다.

```powershell
ros2 run cube_detection markerless_cube_pose --ros-args -p camera_calibration_path:=C:/path/camera_intrinsics.npz -p registration_path:=C:/path/markerless_registration.json -p setup_id:=temporary_20261116
```

설정 예시는 `src/perception/cube_detection/config/markerless_registration.example.json`이다. 초기 예시는 미검증/변환null이므로 후보만 발행한다. 검증 표시를 바꾸기 전에 각 실제 변환과 카메라 지정 기록을 채운다. 손목 검출에는 `cv2.aruco`가 필요하다.

## 임시 배치와 이동

현재 배치는 임시라는 사용자 요청에 따라 `results/markerless_pose_20261116/temporary_20261116.json`을 준비했다. 내부 보정은 저장 후보 `camera1_720.npz`를 참조하지만 현재 카메라에 대한 지정은 미검증이다. `placement.temporary=true`와 `registration.diagnostic_only=true`에서는 다른 검증 표시와 무관하게 정책 pose를 발행하지 않는다.

```powershell
python scripts/create_markerless_profile.py --calibration C:/path/camera.npz --setup-id temporary_20261116 --output results/my_temporary_setup.json
python scripts/create_markerless_profile.py --calibration C:/path/camera.npz --from-profile results/my_temporary_setup.json --setup-id relocated_01 --output results/relocated_01.json
```

두 번째 명령은 기존 파일을 보존하고 새 프로필을 만든다. `world_from_camera`와 그 검증을 비우고 새 촬영의 색 면 축 확인을 요구한다. 같은 카메라 보정 해시와 손목의 고정 장착 변환은 유지할 수 있다. 초점/줌/해상도·크롭이 바뀌면 `--camera-settings-changed`, 손목 마커 장착을 바꾸면 `--wrist-remounted`를 추가한다.

| 변경 | 재사용/재확인 |
|---|---|
| 카메라 위치·각도만 이동 | 같은 광학 설정이면 내부 보정은 재사용 가능. 카메라↔손/world 관계는 재확인 |
| 손 전체 위치 이동 | 마커가 손에 고정돼 있으면 손목↔손바닥 센서 변환은 재사용 가능. 외부 좌표 관계는 재확인 |
| 카메라·손을 강체로 함께 이동 | 상대 관계가 유지됐는지 확인. world 정의에 따라 기존 변환을 재사용할 수 있으며 코드 수정은 불필요 |
| 카메라 설정/해상도 변경 | 해당 설정의 내부 보정과 카메라 지정 확인 |
| 새6면 촬영 | URFDLB 물리 색의 대응 확인. 이전 scan_id의 학습 큐브 축 등록을 자동 재사용하지 않음 |

소프트웨어가 물리적인 이동 자체를 자동 감지하는 것은 아니다. 이동했을 때 새 setup_id로 프로필을 만들어야 한다. 정식 정책 좌표 발행은 임시 모드를 해제한 검증 프로필, 실행 파라미터의 같은 setup_id, 등록한 색 기준 scan_id가 모두 필요하다. 예전/ID없는 프로필은 후보 전용으로 취급한다.

`/cube/pose_wrist_candidate`는 같은 노출에서 계산한 카메라→손목과 카메라→큐브로부터 상대 자세를 구한다. 따라서 고정 카메라→world 변환은 필요하지 않다. 카메라 내부 보정·마커 크기가 미검증이면 상대 좌표의 실제 mm 정확도도 미검증이다.

카메라 스캔을 완료하면 중심색 기준을 자동으로 전달한다. 현재 카메라 스캔의 YOLO 미리보기는 기본5FPS여서 기존100/150ms 정책 입력에 연속 공급하기에는 부족할 수 있다. 실제 추론 지연을 측정해 `detection_preview_fps`와 처리 장치를 선택한다. 코드만으로 더 높은 실물 FPS를 보장하지 않는다.

## 저장 영상 진단과 시험

```powershell
python scripts/replay_markerless_pose.py --image C:/path/frame.jpg --calibration C:/path/camera.npz --detections C:/path/detections.json --output results/markerless_pose/replay
python scripts/check_execution_contract.py
```

`detections.json`의 `detections`는 `corners_px`4개와 confidence를 가진 OBB 목록이다. 수동 탐색 상자를 사용했다면 source에 명시한다. `--color-reference`가 없으면 영상 특징만 확인하고3D pose를 만들지 않는다. 추가 JSON은 `{scan_id,center_bgr:[18개 URFDLB BGR]}` 형식이다. Windows 한글 경로의 이미지도 byte decode/encode로 처리한다.

현재 장치 없는 전체 시험103개를 통과했다. 새 시험은 여러 큐브 방향의 PnP,90도 모호성·잘못된 좌표·노출 시각·오래된 입력 거부, 등록 전 정책 발행 차단, 색 기준 무효화와 영상부터 후보까지의 경로, 이동 후 프로필 무효화 및 카메라 이동에 대한 상대 좌표 불변성을 포함한다. 실제 그림자 사진에서 앞면 복원, 반사로 사라진 흰 칸의 추측 금지, 같은 스티커의 중복 경계를 별도 칸으로 세지 않는 회귀 시험을 추가했다.

합성 영상 한 조건에서 중심 오차 약0.49mm·방향 오차0.19도를 확인했다. **이는 실제 사진의 측정 오차가 아니다.** 저장된 실물 사진3장을 수동 탐색 ROI로 재생했고 선명한 큐브 사진은2면 중1면의 격자를 복원했다. 가림 사진과 빈손 사진에서는 유효한 격자를 발행하지 않았다. 실제3D 정답·유효한 마커 없는6면 색 기준이 없어 실물 pose 성공으로 판정하지 않았다.

그림과 원본 해시: `results/markerless_pose_20261116/index.html`, `assets.json`, `summary.json`.

PnP 계산과 해 모호성은 [OpenCV 공식 설명](https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html)을 참고했다.

## 임시 자리의 실제 화면 확인 — 21:57 촬영

사용자가 카메라 방향을 바꾼 뒤 같은 큐브를 원래 노출 -5와 비교 노출 -6/-7에서 각각3장 촬영했다. 방 조명·로봇은 조작하지 않았고 카메라 초점·줌도 바꾸지 않았다. 자동 노출 속성은 드라이버가 -1을 반환해 건드리지 않았으며, 비교 후 노출 -5 복구를 읽기로 확인하고 카메라를 닫았다.

검출 수정은 그림자 속에서 색이 물든 흰 몸체와 스티커 경계를 분리하는 채도 마스크를 추가하고, 같은 칸의 여러 경계 관측을 보존하되 격자에는 한 번만 세도록 했다. 가까이 촬영한 큰 칸의 경계 오차에 맞춰 영상 격자 적합 범위를 `min(3px,max(1.5px,칸 간격의3.5%))`로 제한한다. **이 값은 영상 특징 후보용이다.** 서로 다른7칸·3행/3열 조건, 두 면 이상 요구, 기존 PnP 재투영2px/최대4px, 시간/등록 조건은 유지했다. 톤 보정과 별도 이웃 중심 초기화는 실제 결과를 개선하지 않아 제외했다.

| 노출 | 수정 전 두 면 동시 검출 | 수정 후 앞면 | 수정 후 윗면 | 수정 후 두 면 동시 검출 |
|---|---:|---:|---:|---:|
| -5 | 0/3 | 3/3 | 0/3 | 0/3 |
| -6 | 0/3 | 3/3 | 0/3 | 0/3 |
| -7 | 0/3 | 1/3 | 1/3 | 1/3 |

수동으로 지정한 대략적인 OBB 탐색 영역으로 평가했다. YOLO 실행이나 실제3D 정답 비교가 아니다. 유효한6면 색 기준이 없으므로 두 면의 격자가 잡힌 한 장도 절대3D 정책 자세로 발행하지 않았다. 현재 카메라 각도의 새 임시 프로필은 `temporary_20261116_camera_reaimed_215542.json`이다.

상세: `results/markerless_pose_20261116/exposure_215747_final/review.json`. 시험용 NPZ에는 원본 사진 전체 대신 큐브 주변만 잘라 넣었으며 출처 해시와 크롭 영역을 함께 기록했다.

## 남은 확인

윗면 반사와 앞면 그림자 때문에 두 면 동시 검출은 아직 안정적이지 않다. 밝기만 바꾸면 해결됐다고 판정하지 않는다. 유효한 마커 없는6면 색 기준 수집도 남았다. 현재 보정3개는 원래 PC의 후보이며, 지금 미들웨어 카메라에 대한 지정·외부 좌표·손목 센서 변환은 미검증이다. 실제 YOLO/ROS 전체 실행과 현재 보정으로의 실물 정확도 측정은 아직 하지 않았다. 이번 결과를 SAC 실물 제어 또는 전체 로봇 작업 완료로 부르지 않는다.
