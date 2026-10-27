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
│       └── empty.md                  # UI 구현은 아직 없음
├── docs/
│   ├── architect.md                  # 프로젝트 트리 및 아키텍처 현황
│   └── ros2_install_guideline.md     # Windows 설치 및 검증 안내
├── scripts/
│   └── windows/
│       └── run_rosbridge.py          # Windows 호환 rosbridge 실행 스크립트
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

참고용 디렉토리 `cube_3D_conversion`, `left-rl-with-mujoco`,
`right_rl_with_mujoco`는 이 프로젝트 트리 외부에 있으며 빌드 입력으로
사용하지 않습니다. 학습된 Custom Hand 모델, LEAP Hand 모델, 파인튜닝된 YOLO
모델을 확보했지만, 이 저장소에서의 통합 경로와 실행 의존성은 아직 정해지지
않았습니다. 카메라 정보와 LEAP Hand 하드웨어 정보 일부도 미정입니다.

Pixi와 colcon 출력은 로컬에서 생성됩니다. `.pixi/`, `.colcon-win/`,
`install/`, `log/`는 Git 추적 대상에서 제외되며, Windows 빌드 출력 위치는
`.colcon-win/`입니다. 트리에 표시된 루트 `log/`는 작업 디렉토리에 남아 있는
이전 생성물입니다.
