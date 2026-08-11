param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [string]$BuildDirectory = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) {
    $BuildDirectory = Join-Path $root "out\build\windows-msvc"
}
$application = Join-Path $BuildDirectory "$Configuration\ffmpegGUI-next.exe"
$ffmpeg = Join-Path $root ".tools\ffmpeg\bin\ffmpeg.exe"
$fixtureDir = Join-Path $root "out\test-media\exr-incremental"
$firstFrame = Join-Path $fixtureDir "plate.0001.exr"
$changedFrame = Join-Path $fixtureDir "plate.0050.exr"
$firstProject = Join-Path $fixtureDir "first.ffguiproject"
$secondProject = Join-Path $fixtureDir "second.ffguiproject"

foreach ($required in @($application, $ffmpeg)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "required sequence-cache smoke dependency is missing: $required"
    }
}
New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null

& $ffmpeg -v error -y -f lavfi -i "testsrc2=s=64x48:r=24:d=4" `
    -frames:v 96 -compression zip1 (Join-Path $fixtureDir "plate.%04d.exr")
if ($LASTEXITCODE -ne 0) {
    throw "incremental EXR fixture generation failed"
}

function Invoke-SelectionSmoke([string]$project) {
    $run = Start-Process -FilePath $application `
        -ArgumentList @("--exr-selection-smoke", $project, $firstFrame) `
        -WindowStyle Hidden -Wait -PassThru
    if ($run.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $project -PathType Leaf)) {
        throw "EXR selection smoke failed with code $($run.ExitCode)"
    }
    $saved = Get-Content -LiteralPath $project -Raw | ConvertFrom-Json
    $cacheRoot = Split-Path $saved.assets[0].playbackPath
    return @{
        Preview = @(Get-Content -LiteralPath (Join-Path $cacheRoot "sequence-preview.ffconcat") |
            Where-Object { $_ -like "file *" })
        Export = @(Get-Content -LiteralPath (Join-Path $cacheRoot "sequence-export.ffconcat") |
            Where-Object { $_ -like "file *" })
    }
}

$before = Invoke-SelectionSmoke $firstProject
& $ffmpeg -v error -y -f lavfi -i "color=c=blue:s=64x48:d=1" `
    -frames:v 1 -compression zip1 $changedFrame
if ($LASTEXITCODE -ne 0) {
    throw "incremental EXR changed-frame generation failed"
}
$after = Invoke-SelectionSmoke $secondProject

foreach ($kind in @("Preview", "Export")) {
    if ($before[$kind].Count -ne 2 -or $after[$kind].Count -ne 2) {
        throw "$kind proxy must be split into two 48-frame chunks"
    }
    if ($before[$kind][0] -ne $after[$kind][0]) {
        throw "$kind unchanged first proxy chunk was not reused"
    }
    if ($before[$kind][1] -eq $after[$kind][1]) {
        throw "$kind changed second proxy chunk was not regenerated"
    }
}

Write-Output "Sequence cache passed: one changed frame regenerated only its 48-frame preview/export chunks"
