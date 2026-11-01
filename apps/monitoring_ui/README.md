# ROS 2 연결 점검 UI

이 앱은 rosbridge WebSocket에 연결해 ROS 2 토픽을 구독·발행하고 서비스를 호출하는 Tauri 진단용 UI입니다. 기본 주소는 `ws://127.0.0.1:9090`이며, 현재 카메라·손 모델·실제 하드웨어와는 연결하지 않습니다.

## 실행 준비

저장소 루트 PowerShell에서 rosbridge와 예제 노드를 각각 실행합니다.

```powershell
pixi run rosbridge
```

별도 PowerShell 창에서 토픽 발행 노드와 서비스 서버를 실행합니다.

```powershell
pixi run ros2 run demo_nodes_py talker
```

```powershell
pixi run ros2 run demo_nodes_cpp add_two_ints_server
```

Tauri 앱의 정적 프론트엔드 파일을 생성합니다.

```powershell
cd apps/monitoring_ui
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

## 브라우저에서 화면 미리보기

Tauri를 설치하기 전에도 정적 화면을 브라우저로 열어 볼 수 있습니다. 위의 빌드 명령을 실행한 같은 PowerShell 창에서 아래 명령을 이어서 실행합니다. `cd ..\..`가 저장소 루트로 돌아갑니다.

```powershell
cd ..\..
pixi run python -m http.server 8000 --directory apps/monitoring_ui/dist
```

브라우저에서 `http://127.0.0.1:8000`을 열면 화면을 볼 수 있습니다. 이 미리보기는 화면 확인용이며, Tauri WebView의 실제 실행과 보안 정책 검증을 대신하지 않습니다. 서버를 종료하려면 해당 PowerShell 창에서 `Ctrl+C`를 누릅니다.

그 다음 `src-tauri`에서 Tauri 2 CLI로 앱을 실행합니다. Rust, Windows C++ 빌드 도구, WebView2 및 Tauri CLI가 필요합니다.

```powershell
cd src-tauri
cargo tauri dev
```

정적 화면의 기본 연결 주소는 `ws://127.0.0.1:9090`입니다. 화면에서 `/chatter`를 `std_msgs/msg/String`으로 구독하고, `/add_two_ints` (`example_interfaces/srv/AddTwoInts`)에 두 정수를 전달해 응답을 확인할 수 있습니다. rosbridge 통신 정책은 `src-tauri/tauri.conf.json`의 WebSocket CSP에 로컬 주소만 허용하도록 설정했습니다.

## 확인 범위 및 미완료 항목

- `scripts/build.ps1`로 Tauri 정적 프론트엔드를 생성합니다. 별도 Node.js나 npm은 필요하지 않습니다.
- 저장소 루트에서 `powershell -ExecutionPolicy Bypass -File .\scripts\windows\test_rosbridge_ws.ps1`을 실행하면 rosbridge 연결, `/chatter` 수신·발행, `/add_two_ints` 서비스 호출을 확인합니다.
- 이 환경에는 Rust/Cargo와 Tauri CLI가 없어 Tauri 네이티브 창 실행 및 WebView 내부 WebSocket 정책은 아직 확인되지 않았습니다.
- 성공적인 rosbridge WebSocket 검증도 Tauri 실제 창의 확인을 대신하지 않습니다. Tauri 창 실행 검증은 Rust 도구체인을 갖춘 Windows 환경에서 이어서 진행해야 합니다.
