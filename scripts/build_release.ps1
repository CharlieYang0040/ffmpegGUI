param(
    [string]$Version = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pyinstallerPath = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "가상 환경을 찾을 수 없습니다: $pythonPath"
}

$configuredVersion = & $pythonPath -c "from app.config import APP_VERSION; print(APP_VERSION)"
if (-not $Version) {
    $Version = $configuredVersion
}
if ($Version -ne $configuredVersion) {
    throw "요청 버전 $Version 과 app.config 버전 $configuredVersion 이 다릅니다."
}

Push-Location $projectRoot
try {
    if (-not $SkipTests) {
        & $pythonPath -m compileall -q app tests
        if ($LASTEXITCODE -ne 0) { throw "compileall 실패" }
        & $pythonPath -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw "테스트 실패" }
        & $pythonPath -m pip check
        if ($LASTEXITCODE -ne 0) { throw "의존성 검사 실패" }
    }

    $stagingDist = Join-Path $projectRoot "artifacts\build\v$Version\dist"
    $stagingWork = Join-Path $projectRoot "artifacts\build\v$Version\work"
    New-Item -ItemType Directory -Force -Path $stagingDist, $stagingWork | Out-Null
    & $pyinstallerPath --noconfirm --clean `
        --distpath $stagingDist `
        --workpath $stagingWork `
        main.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드 실패" }

    $exePath = Join-Path $stagingDist "ffmpegGUI.exe"
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "실행 파일이 생성되지 않았습니다: $exePath"
    }

    $releaseDir = Join-Path $projectRoot "artifacts\release\v$Version"
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    $releaseExe = Join-Path $releaseDir "ffmpegGUI-v$Version-windows-x64.exe"
    Copy-Item -LiteralPath $exePath -Destination $releaseExe -Force

    $hash = (Get-FileHash -LiteralPath $releaseExe -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumPath = Join-Path $releaseDir "SHA256SUMS.txt"
    "$hash  $(Split-Path -Leaf $releaseExe)" | Set-Content -LiteralPath $checksumPath -Encoding ascii

    Write-Host "RELEASE_DIR=$releaseDir"
    Write-Host "EXECUTABLE=$releaseExe"
    Write-Host "SHA256=$hash"
}
finally {
    Pop-Location
}
