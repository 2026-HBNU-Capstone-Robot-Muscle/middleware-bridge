# 큐브 풀이

`cube_solver` 패키지는 `/cube/solve`
(`system_interfaces/srv/SolveCube`) 서비스를 제공합니다. 요청 facelets가
URFDLB 문자 54개이고 각 문자가 9회씩 포함되는지 확인한 뒤,
`rubik-solver-py`의 Kociemba Two-Phase 풀이 결과를 이동 토큰 배열로 반환합니다.

```powershell
pixi run build-windows
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.colcon-win\install\local_setup.ps1
ros2 run cube_solver cube_solver
```

서비스 응답의 `success`와 `error_message`로 성공 및 실패를 확인합니다.
