$ErrorActionPreference = 'Stop'

$uiRoot = Split-Path -Parent $PSScriptRoot
$output = Join-Path $uiRoot 'dist'
$outputSource = Join-Path $output 'src'

New-Item -ItemType Directory -Path $output -Force | Out-Null
New-Item -ItemType Directory -Path $outputSource -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $uiRoot 'index.html') -Destination $output -Force
Copy-Item -LiteralPath (Join-Path $uiRoot 'styles.css') -Destination $output -Force
Get-ChildItem -LiteralPath (Join-Path $uiRoot 'src') -Force |
    Copy-Item -Destination $outputSource -Recurse -Force

Write-Output "Static Tauri frontend written to $output"
