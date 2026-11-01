middleware-bridge/                      # ROS 2 통합 프로젝트
├── .gitattributes
├── .gitignore
├── README.md
├── pixi.toml                         # Windows (win-64)용 ROS 2 Humble 환경 및 작업 정의
├── pixi.lock                         # 고정된 Pixi 환경 의존성
├── .pixi/                            # 로컬 Pixi 환경 생성물 (Git 제외)
├── .colcon-win/                      # Windows colcon 빌드·설치·로그 생성물 (Git 제외)
├── apps/
│   └── monitoring_ui/
│       ├── index.html                # ROS 2 연결 점검 화면
│       ├── styles.css                # 반응형 어두운 테마 스타일
│       ├── README.md                 # Tauri 실행 방법 및 검증 범위
│       ├── scripts/build.ps1         # PowerShell 기반 Tauri 정적 파일 생성기
│       ├── src/main.js               # rosbridge 토픽·서비스 WebSocket 통신
│       └── src-tauri/
│           ├── Cargo.toml            # Tauri 2 Rust 의존성
│           ├── build.rs
│           ├── icons/icon.ico        # Windows 큐브 아이콘
│           ├── tauri.conf.json       # 창 설정 및 localhost WebSocket CSP
│           └── src/main.rs           # Tauri 애플리케이션 시작점
├── docs/
│   ├── architect.md                  # 프로젝트 트리 및 아키텍처 현황
│   └── ros2_install_guideline.md     # Windows 설치 및 검증 안내
├── scripts/
│   └── windows/
│       ├── run_rosbridge.py          # Windows 호환 rosbridge 실행 스크립트
│       └── test_rosbridge_ws.ps1     # PowerShell 토픽 왕복·서비스 확인 스크립트
├── src/                              # colcon이 검색하는 ROS 2 패키지
│   ├── control/
│   │   ├── custom_hand_control/      # Custom Hand 제어 패키지 기본 구조
│   │   └── leap_hand_control/        # LEAP Hand 제어 패키지 기본 구조
│   ├── perception/
│   │   ├── README.md
│   │   └── cube_detection/           # 큐브 감지 패키지 기본 구조
│   ├── planning/
│   │   ├── README.md
│   │   └── cube_solver/              # 큐브 풀이 패키지 기본 구조
│   ├── policy/
│   │   ├── README.md
│   │   └── rl_policy/                # 강화학습 정책 패키지 기본 구조
│   ├── system_bringup/               # 시스템 실행·통합 패키지 기본 구조
│   └── system_interfaces/            # 사용자 정의 ROS 인터페이스 패키지 (세부 내용 미정)
└── log/                              # 현재 남아 있는 이전 colcon 로그

## 현재 단계: Tauri와 rosbridge 연결 검증 완료

- `apps/monitoring_ui`에 Tauri 2 Rust 앱 틀과 정적 HTML/CSS/JavaScript 진단 화면을 추가했습니다. `src`는 ROS 저장소 루트, UI JavaScript, Tauri Rust 코드 각각의 소스 폴더이므로 서로 다른 앱의 영역입니다.
- UI의 WebSocket 주소 기본값은 `ws://127.0.0.1:9090`이며, `/chatter` (`std_msgs/msg/String`) 구독·발행과 `/add_two_ints` (`example_interfaces/srv/AddTwoInts`) 호출 기능을 제공합니다.
- `src-tauri/tauri.conf.json`에는 로컬 rosbridge WebSocket 연결만 허용하는 CSP를 설정했습니다. `scripts/build.ps1`는 별도 Node.js 없이 PowerShell로 Tauri 정적 화면을 `dist/`에 생성합니다.
- rosbridge WebSocket 연결, talker의 `/chatter` 메시지 수신, 발행 메시지 왕복, `17 + 25 = 42` 서비스 응답을 확인했습니다. 이전에는 Node 기반 스크립트로, 현재는 `scripts/windows/test_rosbridge_ws.ps1`로 같은 검증을 통과했습니다. ROS 예제는 `demo_nodes_py talker`와 `demo_nodes_cpp add_two_ints_server`를 사용했습니다.
- Windows 개발 도구 확인 결과 Visual Studio 2026 C++ 빌드 구성 요소와 WebView2가 있고, Rust/Cargo 및 Tauri CLI는 `C:\Users\jeonj\.cargo\bin`에 설치되어 있습니다. PowerShell에서 `cargo`가 바로 인식되지 않으면 새 창을 열거나 Cargo 실행 파일의 전체 경로를 사용합니다.
- Tauri 빌드가 요구하는 `src-tauri/icons/icon.ico`를 추가했고 `cargo tauri dev` 빌드를 통과했습니다. Tauri WebView에서 한국어 진단 화면이 렌더링되는 것을 확인했습니다. 개발 창은 CLI가 제공하는 로컬 정적 서버를 사용하므로 `target/debug` 실행 파일을 따로 열지 말고 `cargo tauri dev`로 실행해야 합니다.
- 사용자가 실제 Tauri 창에서 rosbridge 연결, ROS 토픽, 서비스 통신 검증을 완료했습니다. 앞선 PowerShell WebSocket 검사에 더해 WebView 경로도 확인된 상태입니다.

## 확보 모델 및 입출력 조사

세 참조 디렉토리는 읽기 전용으로 확인했으며, 파일 복사나 모델 추론은 하지 않았습니다. 체크포인트의 해시·크기·직렬화 메타데이터와 배포 코드를 정적으로 확인한 결과입니다. `middleware-bridge` 안의 `src/perception/cube_detection/model` 및 `src/policy/rl_policy/models`에는 현재 `.gitkeep`만 있고 실제 가중치가 없습니다.

### 큐브 YOLO 모델 (`cube_3D_conversion`)

- `cube-detector.pt`는 약 5.9 MB인 Ultralytics YOLO OBB 체크포인트입니다. 참고 코드가 사용하는 클래스는 `side`이며 프레임에서 큐브 면의 사각형 네 꼭짓점, 중심, 신뢰도를 얻습니다. 모델 입력 크기는 코드에서 직접 지정하지 않아 라이브러리 기본값에 따릅니다.
- 이 모델은 스티커 색상 분류나 3D 큐브 자세 추정, 큐브 풀이를 하지 않습니다. 참고 파이프라인은 검출된 면을 원근 보정하고 3×3 스티커의 BGR 색을 추출한 다음, 여섯 면을 모아 검증된 54칸 큐브 상태를 구성합니다. 이후 Kociemba URFDLB 문자열로 바꾸고 풀이 결과를 생성·검증해 `cube_state.json`, `solution.json`으로 저장합니다.
- 따라서 ROS 데이터 흐름에서는 이미지 입력, OBB 검출 결과, 완성된 큐브 상태, 풀이 결과가 서로 다른 단계입니다. 카메라 해상도·모델 입력 크기·캡처 시퀀스는 아직 본 프로젝트에 확정되지 않았습니다.

### Custom Hand 정책 (`left-rl-with-mujoco`)

- 확인한 PPO 파일은 `model/finger_robot_ppo_best.zip`(673,505 학습 스텝), `model/finger_robot_ppo_final.zip`(1,001,472 스텝), `sim2real/finger_robot_ppo_best.zip`(197,306 스텝)입니다. 모두 SB3 PPO 체크포인트이며 정적 메타데이터상 관측 8차원, 행동 4차원입니다. 서로 다른 파일이며 해시도 다르므로 이 중 어느 것이 통합 대상인지는 선택되지 않았습니다.
- `sim2real` 배포 코드는 관측을 네 텐던 위치와 네 속도로 구성하고, 네 개의 정규화 행동값([-1, 1])을 네 모터의 목표 위치로 변환하는 흐름을 설명합니다. 명목 정책 주기는 30 ms입니다. 참고 설정의 모터 순서는 right/front/left/back 및 ID 4/1/2/3으로 되어 있지만, 실제 프로젝트의 손 하드웨어와 보정값으로 간주하지 않습니다.
- 이 정책은 4개 구동 입력을 사용하는 Custom Hand 모델입니다. LEAP Hand의 16관절 모델과 같은 인터페이스로 취급할 수 없습니다. 8차원 관측을 만드는 센서·보정 정의와 사용할 체크포인트를 먼저 확정해야 합니다.

### LEAP Hand 정책 (`right_rl_with_mujoco`)

- 배포 산출물 `policy/policy_np.npz`는 108개 평균·표준편차 값과 108→512→256→128→32 가중치를 포함하며, 정책 행동 크기는 16입니다. 정적 검사에서 정규화 통계는 유한값이었습니다. 배포 코드는 정규화 후 ReLU MLP와 tanh를 적용해 행동을 계산합니다. 별도 `policy/distilled_policy` 파일은 약 898 KB의 증류 정책 산출물입니다.
- 배포 관측 조립 코드는 16개 관절각, 관절 오차 이력, 큐브 위치 오차 이력, 큐브 방향 오차 이력, 직전 행동 및 방향 오차를 합쳐 108차원을 구성합니다. 행동은 16개 [-1, 1] 값이며, 참고 실행 코드는 이를 0.2 rad 스케일의 관절각 증분으로 누적합니다. 이는 큐브 면 방향을 재배치하는 정책이며, 큐브 풀이 수열을 수행하는 정책과는 역할이 다릅니다.
- 참고 실행 코드는 카메라 기반 큐브 자세를 요구하고 마커·카메라 보정 자료를 사용합니다. 현재 프로젝트의 카메라 정보와 LEAP Hand 하드웨어 세부사항은 미정이므로 이 관측을 실제 ROS 토픽으로 구성하거나 행동을 하드웨어에 전송하는 것은 아직 정할 수 없습니다. `BEST_sac_checkpoint.txt` 및 교사 체크포인트 표기 경로는 Windows 참조 디렉토리에 존재하지 않으며, 배포용 정책 파일은 별도로 존재합니다.

참고용 디렉토리 `cube_3D_conversion`, `left-rl-with-mujoco`,
`right_rl_with_mujoco`는 이 프로젝트 트리 외부에 있으며 빌드 입력으로
사용하지 않습니다. 실제 가중치도 현재 `middleware-bridge`에는 포함되어 있지
않습니다. 참조 코드에서 파악한 입력·출력은 통합 계약의 근거로 사용할 수 있지만,
실제 ROS 노드 연결 및 Windows 추론 동작은 아직 검증되지 않았습니다.

Pixi와 colcon 출력은 로컬에서 생성됩니다. `.pixi/`, `.colcon-win/`,
`install/`, `log/`는 Git 추적 대상에서 제외되며, Windows 빌드 출력 위치는
`.colcon-win/`입니다. 트리에 표시된 루트 `log/`는 작업 디렉토리에 남아 있는
이전 생성물입니다.
