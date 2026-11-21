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

### 새 Windows PC에서 자동 설치

저장소를 복제하거나 압축 해제한 뒤 루트에서 `install.bat`을 실행하면 예상 추가 디스크 공간(약 15~25 GB)과 다운로드 용량(약 5~10 GB)을 안내하고 설치 여부를 묻습니다. 기존에 설치된 도구와 패키지 캐시에 따라 실제 사용량은 달라집니다. `Y`를 선택하면 아래 작업을 순서대로 진행하고, `N`을 선택하면 아무 설치 작업 없이 종료합니다.

1. Pixi가 없으면 winget으로 설치
2. Rustup/Cargo가 없으면 설치하고 `stable-msvc` toolchain 선택
3. Visual Studio 2022 C++ Build Tools의 `Desktop development with C++` workload가 없으면 설치
4. WebView2 Runtime이 없으면 Microsoft 공식 bootstrapper로 설치
5. Tauri CLI가 없으면 Cargo로 설치
6. `pixi install`, `pixi run build-windows`, 정적 Tauri frontend 생성 실행

저장소 경로에는 한글 등 비 ASCII 문자와 공백을 사용하지 마세요. Windows의 ROS 2 빌드 도구가 이런 경로를 안정적으로 처리하지 못할 수 있습니다. 노트북에서는 영문·숫자·하이픈만 사용하는 경로에 저장소를 새로 복제한 뒤 `install.bat`을 실행하세요. 설치기는 잘못된 경로를 감지하면 빌드 전에 중단합니다. 이미 설치한 작업 폴더를 옮기는 경우 `.pixi/`와 `.colcon-win/`에는 이전 위치가 기록될 수 있으므로 새 위치에서 다시 생성해야 합니다. 이 디렉토리들은 Git에 포함하지 않습니다.

필요 조건은 64비트 Windows, winget(App Installer), 인터넷 연결입니다. C++ Build Tools는 용량이 큰 구성 요소이며 설치 관리자에서 관리자 승인을 요구할 수 있습니다. 조직 PC의 winget 정책이나 권한으로 설치가 차단되면 아래 사전 준비 항목을 수동 설치한 후 `install.bat`을 다시 실행하면 됩니다. 설치 후 GUI는 저장소 루트의 `start.bat`으로 실행합니다.

자동 설치는 장치 드라이버, 카메라 권한, 실제 핸드 모터 연결을 구성하지 않습니다. 현재 `start.bat`은 실물 구동이 비활성화된 dry-run 실행기입니다.

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

## Tauri 진단 UI와 rosbridge 통신 확인

`apps/monitoring_ui`에는 Tauri 2 진단 화면과 정적 프론트엔드가 있습니다. 이 UI는 Tauri WebView의 기본 WebSocket API로 rosbridge에 직접 연결합니다. Windows C++ 빌드 도구, WebView2, Rust 및 Tauri CLI가 준비된 환경에서 저장소 루트의 PowerShell 창 두 개와 UI 실행용 창 하나를 사용합니다.

창 A — rosbridge 서버:

```powershell
pixi run rosbridge
```

창 B — 토픽 발행 노드와 서비스 서버:

```powershell
pixi run ros2 run demo_nodes_py talker
```

```powershell
pixi run ros2 run demo_nodes_cpp add_two_ints_server
```

창 C — Tauri 정적 UI 빌드 및 실행:

```powershell
cd apps/monitoring_ui
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
cd src-tauri
cargo tauri dev
```

UI에서 `ws://127.0.0.1:9090`에 연결하고 `/chatter` (`std_msgs/msg/String`)를 구독·발행합니다. `/add_two_ints` (`example_interfaces/srv/AddTwoInts`) 서비스에 숫자를 보내고 응답을 확인합니다. Tauri CSP는 loopback WebSocket 주소만 허용합니다.

PowerShell에서 Tauri 창과 분리해 rosbridge 프로토콜 경로를 재현하려면 다음 명령을 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\test_rosbridge_ws.ps1
```

이 스크립트는 rosbridge WebSocket 연결, `/chatter` talker 수신, 같은 토픽으로 발행한 문자열의 왕복 수신, `17 + 25 = 42` 서비스 응답을 확인합니다. Node.js를 설치할 필요가 없습니다. 별도로 Tauri 창에서 연결·토픽·서비스를 수동 검증했습니다.

## 남은 검증

- YOLO, Stable-Baselines3, PyTorch와 실제 모델 파일의 Windows 추론 호환성
- 실제 Dynamixel 및 Feetech 장치 연결과 안전 동작

모델과 하드웨어는 ROS 2 기본 환경 및 rosbridge 확인과 별도로 검증합니다.
