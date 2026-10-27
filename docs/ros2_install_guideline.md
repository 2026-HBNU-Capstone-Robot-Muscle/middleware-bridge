# Windows 네이티브 ROS 2 개발 환경 가이드

## 현재 검증 상태

- Windows 11의 Pixi 환경에서 ROS 2 Humble의 C++ 및 Python talker 노드 실행을 확인했습니다.
- `ros-humble-rosbridge-suite`는 Windows용 패키지가 제공되지만, 기본 `ros2 run rosbridge_server rosbridge_websocket`은 실행 스크립트를 Windows 실행 파일로 처리하지 못해 `WinError 193`이 발생할 수 있습니다.
- 저장소의 `scripts/windows/run_rosbridge.py` 실행 래퍼로 Windows asyncio signal 처리 문제를 우회하고, WebSocket으로 `/chatter` 메시지를 받는 것까지 확인했습니다.
- Tauri 앱 자체와 실제 UI 연결은 아직 별도로 검증해야 합니다.

## 사전 준비

1. Windows 11 x64
2. Visual Studio 2022의 **Desktop development with C++** 구성 요소
3. Pixi

Pixi는 PowerShell에서 설치할 수 있습니다.

```powershell
winget install prefix-dev.pixi
```

설치 뒤 새 PowerShell을 열고 확인합니다.

```powershell
pixi --version
```

기존 ROS 설치가 환경 변수에 섞이지 않도록 별도 Pixi 환경에서 진행합니다. 새 시험 환경을 만들 때는 다음을 실행합니다.

```powershell
mkdir "$env:TEMP\ros2-humble-win-check"
cd "$env:TEMP\ros2-humble-win-check"
pixi init --channel https://prefix.dev/robostack-humble
pixi add ros-humble-desktop ros-dev-tools ros-humble-rosbridge-suite
```

## ROS 2 기본 통신 확인

PowerShell 창 두 개를 열고 각 창에서 시험 환경 디렉토리로 이동합니다.

창 A:

```powershell
pixi run ros2 run demo_nodes_cpp talker
```

창 B:

```powershell
pixi run ros2 run demo_nodes_py listener
```

listener에 `/chatter` 메시지가 표시되면 ROS 2 노드 간 통신이 됩니다.

## rosbridge 실행

현재 저장소에는 아직 프로젝트용 `pixi.toml`이 없습니다. 시험용 Pixi 환경을 사용하려면 저장소 루트에서 다음을 실행합니다.

```powershell
$rosEnv = Join-Path $env:TEMP 'ros2-humble-win-check\pixi.toml'
$repoRoot = (Get-Location).Path
pixi run --manifest-path $rosEnv python (Join-Path $repoRoot 'scripts\windows\run_rosbridge.py')
```

정상 실행되면 `Rosbridge WebSocket server started on port 9090` 로그가 표시됩니다. 이 래퍼는 설치된 rosbridge 패키지를 수정하지 않고, Windows Proactor 이벤트 루프의 `add_signal_handler()` 동작만 Python `signal.signal()` 기반으로 연결합니다.

`ros2 run rosbridge_server rosbridge_websocket` 대신 래퍼를 사용해야 합니다. 기본 실행 명령은 현재 Windows에서 `WinError 193` 또는 `NotImplementedError`로 실패할 수 있습니다.

## WebSocket 통신 확인

rosbridge를 실행한 상태에서 별도 PowerShell 창에서 talker를 실행합니다.

```powershell
pixi run --manifest-path (Join-Path $env:TEMP 'ros2-humble-win-check\pixi.toml') ros2 run demo_nodes_py talker
```

WebSocket 클라이언트가 `ws://127.0.0.1:9090`에 연결하고 다음 JSON을 보내면 `/chatter` 구독을 시작합니다.

```json
{"op":"subscribe","topic":"/chatter","type":"std_msgs/msg/String"}
```

정상 연결 시 `{"op":"publish","topic":"/chatter","msg":{"data":"Hello World: ..."}}` 형식의 메시지가 수신됩니다.

## 다음 검증 항목

- 저장소용 Pixi 설정을 추가하고 7개 ROS 2 패키지를 Windows에서 빌드
- Tauri WebSocket 플러그인으로 `ws://127.0.0.1:9090` 연결 및 ROS 토픽/서비스 통신
- YOLO, Stable-Baselines3, PyTorch 및 실제 모델 파일의 Windows 추론 호환성
- 실제 Dynamixel 및 Feetech 장치 연결과 안전 동작

모델과 하드웨어 검증은 ROS 2 및 rosbridge 검증과 별도로 진행합니다.
