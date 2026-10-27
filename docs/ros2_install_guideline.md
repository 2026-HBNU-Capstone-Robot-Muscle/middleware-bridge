# Windows 네이티브 ROS 2 개발 환경 가이드

## 현재 검증 상태

- Windows 11의 Pixi 환경에서 ROS 2 Humble의 C++ 및 Python talker 노드 실행을 확인했습니다.
- 기본 `ros2 run rosbridge_server rosbridge_websocket`은 Windows에서 실행 파일 형식 및 asyncio signal handler 문제로 실패할 수 있습니다.
- 저장소의 `scripts/windows/run_rosbridge.py` 래퍼를 통해 rosbridge를 시작하고, WebSocket에서 ROS2 `/chatter` 메시지를 수신하는 것을 확인했습니다.
- 저장소 7개 패키지의 Windows `colcon` 빌드도 통과했습니다. `system_interfaces`에는 CMake 최소 버전 경고가 남아 있습니다.
- Tauri 앱 자체와 실제 UI 연결은 별도 검증 대상입니다.

## 사전 준비

1. Windows 11 x64
2. Visual Studio 2022의 **Desktop development with C++** 구성 요소
3. Pixi

Pixi는 PowerShell에서 설치할 수 있습니다.

```powershell
winget install prefix-dev.pixi
```

설치 후 새 PowerShell을 열고 저장소 루트에서 프로젝트 환경을 설치합니다.

```powershell
pixi --version
pixi install
```

저장소 루트의 `pixi.toml`은 `win-64`와 ROS 2 Humble을 대상으로 하며, `pixi.lock`은 설치된 정확한 패키지 버전을 기록합니다.

## ROS 2 노드 간 통신 확인

PowerShell 창 두 개를 열고 저장소 루트에서 실행합니다.

창 A:

```powershell
pixi run ros2 run demo_nodes_cpp talker
```

창 B:

```powershell
pixi run ros2 run demo_nodes_py listener
```

listener에 `/chatter` 메시지가 표시되면 ROS 2 노드 간 통신이 됩니다.

## 저장소 패키지 목록 및 빌드

패키지 검색 결과를 확인합니다.

```powershell
pixi run list-packages
```

기존 `install/`과 `log/`은 재생성 가능한 colcon 산출물이어서 작업 트리에서 제거했습니다. `.gitignore`는 이후 생성물을 제외하며, 저장소의 `.colcon-win/`은 Windows 빌드 결과를 보관하는 무시 대상 디렉토리입니다.

```powershell
pixi run build-windows
```

## rosbridge 실행

저장소 루트에서 실행합니다.

```powershell
pixi run rosbridge
```

정상 실행되면 `Rosbridge WebSocket server started on port 9090` 로그가 표시됩니다. 래퍼는 설치된 rosbridge 파일을 바꾸지 않고 Windows Proactor 이벤트 루프의 signal 처리를 Python `signal.signal()` 기반으로 연결합니다.

기본 `ros2 run rosbridge_server rosbridge_websocket` 대신 이 래퍼를 사용합니다.

## WebSocket 통신 확인

rosbridge를 실행한 상태에서 별도 PowerShell 창에서 talker를 실행합니다.

```powershell
pixi run ros2 run demo_nodes_py talker
```

WebSocket 클라이언트가 `ws://127.0.0.1:9090`에 연결하고 다음 JSON을 보내면 `/chatter` 구독을 시작합니다.

```json
{"op":"subscribe","topic":"/chatter","type":"std_msgs/msg/String"}
```

정상 연결 시 `{"op":"publish","topic":"/chatter","msg":{"data":"Hello World: ..."}}` 형식의 메시지가 수신됩니다.

## 이후 검증

- Tauri WebSocket 플러그인으로 rosbridge 연결 및 ROS 토픽/서비스 통신
- YOLO, Stable-Baselines3, PyTorch와 실제 모델 파일의 Windows 추론 호환성
- 실제 Dynamixel 및 Feetech 장치 연결과 안전 동작

모델과 하드웨어는 ROS 2 기본 환경 및 rosbridge 확인과 별도로 검증합니다.
