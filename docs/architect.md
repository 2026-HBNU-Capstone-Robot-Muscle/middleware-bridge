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

## 현재 단계: Tauri와 rosbridge 통신 경로 준비

- `apps/monitoring_ui`에 Tauri 2 Rust 앱 틀과 정적 HTML/CSS/JavaScript 진단 화면을 추가했습니다. `src`는 ROS 저장소 루트, UI JavaScript, Tauri Rust 코드 각각의 소스 폴더이므로 서로 다른 앱의 영역입니다.
- UI의 WebSocket 주소 기본값은 `ws://127.0.0.1:9090`이며, `/chatter` (`std_msgs/msg/String`) 구독·발행과 `/add_two_ints` (`example_interfaces/srv/AddTwoInts`) 호출 기능을 제공합니다.
- `src-tauri/tauri.conf.json`에는 로컬 rosbridge WebSocket 연결만 허용하는 CSP를 설정했습니다. `scripts/build.ps1`는 별도 Node.js 없이 PowerShell로 Tauri 정적 화면을 `dist/`에 생성합니다.
- rosbridge WebSocket 연결, talker의 `/chatter` 메시지 수신, 발행 메시지 왕복, `17 + 25 = 42` 서비스 응답을 확인했습니다. 이전에는 Node 기반 스크립트로, 현재는 `scripts/windows/test_rosbridge_ws.ps1`로 같은 검증을 통과했습니다. ROS 예제는 `demo_nodes_py talker`와 `demo_nodes_cpp add_two_ints_server`를 사용했습니다.
- PowerShell 정적 프론트엔드 생성, PowerShell 검증 스크립트 구문, JavaScript 구문, Tauri 설정 JSON과 `git diff --check`를 확인했습니다. 검증 뒤 rosbridge와 예제 노드를 종료했습니다.
- Rust/Cargo와 Tauri CLI가 없어 Tauri 네이티브 창은 아직 빌드하거나 실행하지 않았습니다. 따라서 WebView 내부 WebSocket 연결, Tauri CSP의 실제 적용 및 화면 동작은 아직 확인 전입니다. 다음 구현 검증은 Windows Rust/Cargo 및 Tauri CLI 환경에서 실제 창을 실행하는 것입니다.

참고용 디렉토리 `cube_3D_conversion`, `left-rl-with-mujoco`,
`right_rl_with_mujoco`는 이 프로젝트 트리 외부에 있으며 빌드 입력으로
사용하지 않습니다. 학습된 Custom Hand 모델, LEAP Hand 모델, 파인튜닝된 YOLO
모델을 확보했지만, 이 저장소에서의 통합 경로와 실행 의존성은 아직 정해지지
않았습니다. 카메라 정보와 LEAP Hand 하드웨어 정보 일부도 미정입니다.

Pixi와 colcon 출력은 로컬에서 생성됩니다. `.pixi/`, `.colcon-win/`,
`install/`, `log/`는 Git 추적 대상에서 제외되며, Windows 빌드 출력 위치는
`.colcon-win/`입니다. 트리에 표시된 루트 `log/`는 작업 디렉토리에 남아 있는
이전 생성물입니다.
