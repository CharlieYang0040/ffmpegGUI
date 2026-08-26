param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [ValidateRange(1, 100)]
    [int]$Iterations = 3,
    [switch]$SkipExport,
    [string]$BuildDirectory = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$gstRoot = Join-Path $root ".tools\gstreamer"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$ffmpegRoot = Join-Path $root ".tools\ffmpeg\bin"
$mediaDir = Join-Path $root "out\test-media\ges-smoke"
$resultDir = Join-Path $root "out\test-results\core-workflow"
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) {
    $BuildDirectory = Join-Path $root "out\build\windows-msvc"
}
$application = Join-Path $BuildDirectory "$Configuration\ffmpegGUI-next.exe"
$clipA = Join-Path $mediaDir "shot-a.mp4"
$clipB = Join-Path $mediaDir "shot-b.mkv"
$clipVfr = Join-Path $mediaDir "shot-vfr.mkv"
$ffprobe = Join-Path $ffmpegRoot "ffprobe.exe"

foreach ($required in @($application, $ffprobe)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "required core-workflow file is missing: $required"
    }
}
if (@($clipA, $clipB, $clipVfr) | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }) {
    & (Join-Path $PSScriptRoot "run_ges_smoke.ps1") -Configuration $Configuration
    if ($LASTEXITCODE -ne 0) { throw "failed to generate core-workflow media fixtures" }
}

New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
$env:PATH = "$qtRoot\bin;$gstRoot\bin;$env:PATH"
$env:QML2_IMPORT_PATH = "$qtRoot\qml"
$env:GST_PLUGIN_PATH = "$gstRoot\lib\gstreamer-1.0"
$env:GST_REGISTRY = Join-Path $root ".tools\gst-registry.bin"
$env:GIO_MODULE_DIR = Join-Path $root ".tools\empty-gio-modules"
$env:GST_PLUGIN_FEATURE_RANK = "avdec_h264:MAX,nvh264dec:NONE,d3d12h264dec:NONE,mfh264dec:NONE"

for ($iteration = 1; $iteration -le $Iterations; ++$iteration) {
    $project = Join-Path $resultDir ("roundtrip-{0:D2}.ffnext" -f $iteration)
    $output = Join-Path $resultDir ("export-{0:D2}.mp4" -f $iteration)
    foreach ($generated in @($project, "$project.srt", "$project.cube", $output)) {
        Remove-Item -LiteralPath $generated -Force -ErrorAction SilentlyContinue
    }

    $roundtrip = Start-Process -FilePath $application `
        -ArgumentList @("--project-roundtrip", $project, $clipA, $clipB, $clipVfr) `
        -WindowStyle Hidden -Wait -PassThru
    if ($roundtrip.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $project -PathType Leaf)) {
        throw "core workflow roundtrip failed at iteration $iteration with code $($roundtrip.ExitCode)"
    }

    if (-not $SkipExport) {
        $export = Start-Process -FilePath $application `
            -ArgumentList @("--export-smoke", $output, $clipA, $clipB, $clipVfr) `
            -WindowStyle Hidden -Wait -PassThru
        if ($export.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
            throw "core workflow export failed at iteration $iteration with code $($export.ExitCode)"
        }
        $probe = & $ffprobe -v error -show_entries stream=codec_type `
            -show_entries format=duration -of json $output | ConvertFrom-Json
        $types = @($probe.streams | ForEach-Object { $_.codec_type })
        $duration = [double]::Parse(
            $probe.format.duration, [Globalization.CultureInfo]::InvariantCulture)
        if ($types -notcontains "video" -or $types -notcontains "audio" -or
            $duration -lt 5.7 -or $duration -gt 6.1) {
            throw "core workflow export verification failed at iteration $iteration"
        }
    }

    $residual = Get-Process -Name "ffmpegGUI-next" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $application }
    if ($null -ne $residual) {
        throw "core workflow left a residual desktop process at iteration $iteration"
    }
    Write-Output "Core workflow iteration $iteration/$Iterations passed"
}

Write-Output "Core workflow passed $Iterations consecutive iterations"
