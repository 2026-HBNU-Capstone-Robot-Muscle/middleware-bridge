# ROS2 개발 환경 세팅 가이드

> 대상 환경: Windows 11 → WSL2 → Ubuntu 22.04 → ROS2 Humble
> 최종 목표: `middleware-bridge` 레포지토리를 `colcon`으로 빌드/실행할 수 있는 상태

> ROS2는 로컬에 설치, numpy와 같은 무거운 라이브러리는 가상환경에 설치하는 것을 일단 계획하고 있음
---

## 0. 사전 결정 사항

| 항목 | 선택 |
|---|---|
| OS | Windows 11 |
| 가상화 방식 | WSL2 |
| Linux 배포판 | Ubuntu 22.04 (Jammy) |
| ROS2 배포판 | Humble |
| Python 가상환경 | conda 또는 venv (역할 분리형 전략, 3장 참고) |

> 캡스톤디자인 중간보고서 토대로 ROS2는 안정적이고 많은 자료가 있는 ROS2 Humble을 채택

---

## 1. WSL2 및 Ubuntu 22.04 설치

Windows PowerShell을 **관리자 권한**으로 열고 실행합니다.

```powershell
wsl --install -d Ubuntu-22.04
```

이미 WSL이 설치되어 있다면 버전 확인:

```powershell
wsl --set-default-version 2
wsl --list --verbose
```

`Ubuntu-22.04`가 `VERSION 2`로 표시되는지 확인합니다. 설치 후 재부팅이 필요할 수 있습니다.

재부팅 후 시작 메뉴에서 **Ubuntu 22.04**를 실행하면 사용자 이름/비밀번호 설정 창이 뜹니다.

### 이후 우분투 접속 방법
- 시작 메뉴 검색 → "Ubuntu 22.04" 클릭
- 또는 PowerShell/Windows Terminal에서 `wsl -d Ubuntu-22.04`

---

## 2. Ubuntu 초기 설정

```bash
sudo apt update && sudo apt upgrade -y
```

### 로케일(locale) 설정 (ROS2는 UTF-8 로케일 필요)

```bash
sudo apt install locales -y
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
```

설정 후 터미널을 재시작합니다.

---

## 3. Python 가상환경 전략 (conda / venv 공통)

> **핵심 문제**: ROS2(rclpy)는 시스템 Python을 기준으로 빌드되어 있어서, conda나 venv를 항상 켜둔 채로 `colcon build`를 하면 Python 경로 충돌로 빌드가 실패하거나 `ModuleNotFoundError`가 발생할 수 있습니다. 이는 conda든 venv든 동일하게 적용되는 문제입니다.

### 채택한 전략: 역할 분리형

- **ROS2 노드 실행/빌드(`colcon build`, `ros2 run` 등)** → 시스템 Python, 가상환경 비활성 상태
- **`cube_detection`, `rl_policy` 등 YOLO/SB3처럼 무거운 라이브러리가 필요한 노드** → 해당 노드를 실행하는 시점에만 가상환경을 activate하거나, 서브프로세스로 분리 호출

venv는 conda보다 가볍고 시스템 패키지 매니저(apt)와의 충돌 가능성이 상대적으로 적어, ROS2 커뮤니티에서 더 흔히 쓰이는 조합입니다. 다만 conda로 진행해도 동일한 전략을 적용하면 무방합니다.

> ⚠️ 아직 확정되지 않은 부분: 가상환경을 노드별로 어떻게 activate/서브프로세스 호출할지 구체적 방식은 실제 노드 코드 작성 시점에 결정 필요.

---

## 4. ROS2 Humble 설치 (apt)

### 4-1. universe 저장소 활성화

```bash
sudo apt install software-properties-common -y
sudo add-apt-repository universe
```

### 4-2. ROS2 GPG 키 등록

```bash
sudo apt update && sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
```

### 4-3. ROS2 apt 저장소 추가

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
```

> ⚠️ **주의(트러블슈팅)**: WSL 환경에서는 `$UBUNTU_CODENAME`이 비어 있는 경우가 있습니다. 다음 단계에서 문제가 생기면 아래로 확인:
> ```bash
> cat /etc/apt/sources.list.d/ros2.list
> ```
> 결과에 `jammy` 문자열이 정상적으로 들어가 있는지 확인합니다. 비어 있다면 `jammy`를 직접 넣어 재작성합니다.

### 4-4. 저장소 반영 확인

```bash
sudo apt update
```

`Hit` 목록에 `packages.ros.org` 관련 주소가 추가되었는지 확인합니다. (실제로 이 단계가 빠져서 최초 설치 시 `E: Unable to locate package ros-humble-desktop` 에러가 발생했던 이력 있음)

### 4-5. ros-humble-desktop 설치

```bash
sudo apt install ros-humble-desktop -y
```

용량이 커서(수 GB) 설치에 시간이 걸릴 수 있습니다.

---

## 5. ROS2 환경 변수 설정 및 확인

매 터미널마다 아래 명령을 실행해야 ROS2 명령어를 사용할 수 있습니다.

```bash
source /opt/ros/humble/setup.bash
```

매번 입력하지 않도록 `~/.bashrc`에 추가:

```bash
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
source ~/.bashrc
```

### 설치 확인

```bash
ros2 doctor
ros2 topic list
```

정상적으로 명령이 동작하면 설치 완료입니다.

---

## 6. colcon 빌드 도구 설치

```bash
sudo apt install python3-colcon-common-extensions -y
```

워크스페이스 루트(`cube_manipulation_ws`)에서 빌드:

```bash
cd ~/cube_manipulation_ws
colcon build
```

---

## 진행 상태 체크리스트

- [ ] WSL2 + Ubuntu 22.04 설치
- [ ] 로케일 설정
- [ ] 가상환경 전략 결정 (conda vs venv)
- [ ] ROS2 GPG 키 및 저장소 등록
- [ ] ros-humble-desktop 설치
- [ ] 환경 변수(.bashrc) 설정
- [ ] colcon 설치 및 빌드 테스트

---

## 참고: 이후 미확정 사항 (진행하며 채워야 할 것)

- 가상환경(conda/venv) 최종 선택 및 노드별 activate 방식
- `custom_hand_control`, `leap_hand_control`의 Python/C++ 여부
- monitoring_ui(Tauri) ↔ ROS2 간 통신 방식 (rosbridge / 별도 브릿지 노드 등)