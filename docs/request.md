# ROS 데이터 계약 제안

## ROS 데이터 계약 초안

아래는 ROS 그래프의 노드 간 데이터 경계를 정하기 위한 제안이며, 현재 `src/system_interfaces`에 메시지·서비스 정의로 반영했습니다. 이 문서는 제안된 계약의 근거와 의미를 보존합니다. 카메라 종류와 해상도, 실제 손 드라이버 및 관절 이름이 정해지지 않아 장치별 세부 필드는 고정하지 않았습니다.

### 제안하는 데이터 흐름

| 인터페이스 | 방향 | ROS 타입 제안 | 핵심 데이터 |
|---|---|---|---|
| `/camera/image_raw` | 카메라 → perception | `sensor_msgs/msg/Image` | 원본 이미지, 표준 `Header`의 시각·프레임 ID, encoding |
| `/cube/face_detections` | perception → 큐브 상태 조립/UI | `system_interfaces/msg/FaceDetectionArray` | 이미지 헤더, 검출 항목 배열. 항목은 클래스, confidence, 이미지 픽셀 좌표의 OBB 네 꼭짓점 및 중심을 포함 |
| `/cube/state` | 상태 조립 → solver/UI | `system_interfaces/msg/CubeState` | 유효 상태의 `facelets` 54자(URFDLB 순서), 유효 여부, 관측한 면 목록, 검증 오류 목록, 생성 시각 |
| `/cube/solve` | UI/상위 노드 → solver | `system_interfaces/srv/SolveCube` | 요청은 54자 facelets. 응답은 성공 여부, 표준 큐브 이동 표기 문자열 배열, 실패 사유 |
| `/system/status` | 각 노드 → UI | `diagnostic_msgs/msg/DiagnosticArray` | 노드 연결·준비 상태, 오류 수준, 사람이 읽을 수 있는 상태 메시지 |

`FaceDetectionArray`는 YOLO 결과를 투명하게 관찰하기 위한 진단 계약입니다. OBB 꼭짓점 좌표 단위는 픽셀로 하고, 정점 순서는 원본 검출기가 제공하는 순서를 유지하며 좌표계는 이미지 좌상단 원점으로 명시하는 안을 제안합니다. 이 메시지는 색상이나 3D 자세를 의미하지 않습니다. 카메라 intrinsics가 확보된 뒤 3D 자세가 필요하면 별도의 `PoseStamped` 기반 계약으로 추가합니다.

제안 필드 형태는 다음과 같습니다. `FaceDetection`은 같은 패키지 안의 보조 메시지입니다.

```text
# FaceDetection.msg
string class_name
float32 confidence
geometry_msgs/Point32[4] corners_px
geometry_msgs/Point32 center_px

# FaceDetectionArray.msg
std_msgs/Header header
system_interfaces/FaceDetection[] detections

# CubeState.msg
std_msgs/Header header
string facelets
bool valid
string[] observed_faces
string[] validation_errors

# SolveCube.srv
string facelets
---
bool success
string[] moves
string error_message
```

`corners_px`는 이미지 좌상단을 원점으로 하는 픽셀 좌표이며, ROS 메시지 형식이 지원하는 고정 길이 4점 배열을 사용합니다. 실제 구현 전에 검출기가 내놓는 네 점의 순서를 확인하고 순서 규칙을 명시합니다. `CubeState`가 유효하지 않을 때 `facelets`를 비워두는 규칙을 두어 미완성 문자열이 풀이 요청으로 넘어가지 않게 합니다.

`CubeState.facelets`는 길이 54, 문자 집합 `URFDLB`로 제한하고, 순서는 Kociemba 표준 URFDLB facelet 순서로 고정합니다. 큐브 상태 조립 노드는 여섯 면 캡처, 색 분류, 물리적 상태 검증을 통과한 경우에만 `valid=true`로 발행합니다. `observed_faces` 원소는 `U`, `R`, `F`, `D`, `L`, `B` 중 관측한 면을 나타내며, 유효하지 않은 상태의 `facelets`는 빈 문자열로 둡니다. 풀이 응답의 `moves`는 예를 들어 `R`, `U'`, `F2` 같은 토큰 배열이며, 빈 배열과 성공 여부를 혼동하지 않도록 `success`와 `error_message`를 함께 둡니다.

### 손 정책과 제어 경계

- 정책의 고정 길이 벡터(Custom Hand 8→4, LEAP Hand 108→16)를 시스템 전체 ROS 계약으로 노출하지 않는 안을 제안합니다. 이는 체크포인트 내부 입력 표현이며, 모델 선택과 관측 조립 방식이 바뀌면 ROS 계약까지 깨지기 때문입니다.
- 하드웨어 측정 상태에는 표준 `sensor_msgs/msg/JointState`를 우선 검토합니다. Custom Hand와 LEAP Hand는 서로 다른 제어 패키지에서 각자의 관측을 조립하고 정책 출력을 장치 단위 목표값으로 변환합니다. 관절 이름, 단위, command 토픽은 실제 드라이버·하드웨어 사양을 확인한 뒤 정합니다.
- 풀이 문자열을 실제 손 동작으로 바꾸는 시퀀스 실행 인터페이스는 보류합니다. 현재 자료로는 큐브 이동 표기와 각 손의 동작 시퀀스, 정책 간 역할 분담을 검증할 수 없습니다. 이를 확인한 뒤 장시간 실행·취소·피드백이 필요한 경우 ROS 2 action으로 정의합니다. 단일 계산인 큐브 풀이는 service로 충분합니다.

### 공통 규칙 제안

- 대용량 `/camera/image_raw`와 빠르게 갱신되는 검출 진단 토픽은 최신 값 우선의 `BEST_EFFORT`를 검토합니다. 완성된 `/cube/state`, 풀이 응답, 상태 및 향후 명령 경계는 `RELIABLE`을 우선합니다. 큐 깊이와 내구성은 실제 발행 주기·재접속 동작을 확인해 확정합니다.
- 메시지에는 시간 의미가 있는 경우 표준 `Header`를 포함하고, 단위와 좌표계는 필드 주석에 명시합니다. 성공 여부와 오류 설명을 분리해 빈 데이터만으로 실패를 추론하지 않도록 합니다.
- Tauri UI에는 ROS 메시지 정의를 복제하지 않습니다. UI는 rosbridge를 통해 위 ROS 토픽을 구독하고 `/cube/solve` 서비스를 호출하는 방식으로 연결합니다.

### 확정 전에 필요한 확인

1. 고정된 샘플 이미지로 YOLO OBB 결과의 꼭짓점 순서와 confidence 표현을 검증합니다.
2. Custom Hand PPO 세 파일 중 배포 체크포인트를 선택하고 8개 관측 요소의 순서·단위와 모터 드라이버를 확인합니다.
3. LEAP Hand 관절 피드백 이름·단위·주기, 카메라 자세 추정 공급원 및 108차원 관측 구성 가능성을 확인합니다.
4. 큐브 이동 토큰을 실제 조작 단계로 변환하는 절차와 각 손 정책의 역할 분담을 정합니다.

이 확인 전에는 위 메시지 필드와 QoS를 제안 상태로 유지합니다. 특히 손 제어 계약은 하드웨어를 추정해 만들지 않습니다.

