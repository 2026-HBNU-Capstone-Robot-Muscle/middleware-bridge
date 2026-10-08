cube_manipulation_ws/
├── README.md
├── .gitignore
├── .gitattributes                 # Git LFS 설정 (models/ 하위 대형 파일 추적)
│
├── src/                            # colcon 빌드 대상 (ROS2 패키지)
│   ├── perception/
│   │   └── cube_detection/
│   │       ├── cube_detection/        # 추론 노드 (이미지 구독 → OBB 추론 → publish)
│   │       ├── models/                # yolo26n-obb 파인튜닝 가중치 (.pt, LFS)
│   │       ├── launch/
│   │       └── package.xml / setup.py
│   │
│   ├── policy/
│   │   └── rl_policy/
│   │       ├── rl_policy/
│   │       │   ├── custom_hand_policy/  # SB3 PPO 모델 로드 및 추론 노드
│   │       │   └── leap_hand_policy/    # SB3 SAC 모델 로드 및 추론 노드
│   │       ├── models/                  # 학습 완료된 .zip 정책 파일 (LFS)
│   │       ├── launch/
│   │       └── package.xml / setup.py
│   │
│   ├── control/
│   │   ├── custom_hand_control/       # Custom Hand 텐던 구동 제어 인터페이스
│   │   └── leap_hand_control/         # LEAP Hand 직구동 제어 인터페이스
│   │
│   ├── system_interfaces/             # 커스텀 msg/srv/action (미확정, 추후 채움)
│   └── system_bringup/                # 전체 시스템 통합 launch/파라미터
│
├── apps/                           # colcon 빌드 대상이 아닌 독립 애플리케이션
│   └── monitoring_ui/                 # Tauri(React + Rust) 데스크톱 앱
│       ├── src/                       # React 프론트엔드
│       ├── src-tauri/                 # Rust 백엔드
│       └── package.json / Cargo.toml
│
└── docs/
    └── architecture.md