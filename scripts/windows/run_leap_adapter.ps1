param(
    [ValidateSet('mock', 'read_only', 'recorded')]
    [string]$Mode = 'mock',
    [string]$Port = '',
    [string]$SourceRoot = '',
    [switch]$EnableRecordedHardware
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$overlaySetup = Join-Path $repositoryRoot '.colcon-win\install\local_setup.ps1'
if (-not (Test-Path -LiteralPath $overlaySetup)) {
    throw "ROS overlay not found. Build the workspace first: $overlaySetup"
}
if ($Mode -eq 'read_only' -and [string]::IsNullOrWhiteSpace($Port)) {
    throw 'read_only requires an explicit -Port; the port depends on this PC.'
}
if ($Mode -eq 'recorded') {
    if (-not $EnableRecordedHardware -or [string]::IsNullOrWhiteSpace($SourceRoot)) {
        throw 'recorded requires -EnableRecordedHardware and -SourceRoot. This mode can move motors after an explicit action request.'
    }
    $SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
}
Set-Location -LiteralPath $repositoryRoot
. $overlaySetup
$rosArguments = @('--ros-args', '-p', "backend_mode:=$Mode")
if ($Port) {
    $rosArguments += @('-p', "port:=$Port")
}
if ($Mode -eq 'recorded') {
    $rosArguments += @('-p', "recorded_source_root:=$SourceRoot", '-p', 'recorded_hardware_enabled:=true')
}
Write-Output "LEAP adapter mode=$Mode. Stop the old leap_hand_primitive_server first."
& ros2 run leap_hand_control leap_hand_adapter @rosArguments
exit $LASTEXITCODE
