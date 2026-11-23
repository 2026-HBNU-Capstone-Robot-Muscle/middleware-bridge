$ErrorActionPreference = 'Stop'

try {
    if (-not $env:CONDA_PREFIX) {
        throw 'Pixi did not provide CONDA_PREFIX. Run this build through "pixi run build-windows".'
    }

    $pixiPython = Join-Path $env:CONDA_PREFIX 'python.exe'
    if (-not (Test-Path -LiteralPath $pixiPython)) {
        throw "Pixi Python was not found at the active environment path: $pixiPython"
    }

    $pythonInfo = & $pixiPython -c 'import sys; print(sys.executable); print(sys.version.split()[0])'
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the active Pixi Python interpreter.' }
    Write-Host "Using Pixi Python: $($pythonInfo[0]) (Python $($pythonInfo[1]))"

    $cmakePythonArgs = @(
        "-DPython3_EXECUTABLE=$pixiPython",
        "-DPython_EXECUTABLE=$pixiPython",
        "-DPYTHON_EXECUTABLE=$pixiPython"
    )
    & colcon `
        --log-base .colcon-win/log `
        build `
        --executor sequential `
        --merge-install `
        --base-paths src `
        --build-base .colcon-win/build `
        --install-base .colcon-win/install `
        --cmake-force-configure `
        --cmake-args @cmakePythonArgs

    if ($LASTEXITCODE -ne 0) {
        throw "ROS 2 package build failed (exit code $LASTEXITCODE)."
    }
}
catch {
    Write-Host "Build failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
