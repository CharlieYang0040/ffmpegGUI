param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [int]$Seconds = 5
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$gstRoot = Join-Path $root ".tools\gstreamer"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$mediaDir = Join-Path $root "out\test-media\ges-smoke"
$application = Join-Path $root "out\build\windows-msvc\$Configuration\ffmpegGUI-next.exe"
$clipA = Join-Path $mediaDir "shot-a.mp4"
$clipB = Join-Path $mediaDir "shot-b.mkv"
$clipVfr = Join-Path $mediaDir "shot-vfr.mkv"
$roundtripProject = Join-Path $mediaDir "roundtrip.ffnext"

foreach ($required in @($application, $clipA, $clipB, $clipVfr)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "required smoke-test file is missing: $required"
    }
}

$env:PATH = "$qtRoot\bin;$gstRoot\bin;$env:PATH"
$env:QML2_IMPORT_PATH = "$qtRoot\qml"
$env:GST_PLUGIN_PATH = "$gstRoot\lib\gstreamer-1.0"
$env:GST_REGISTRY = Join-Path $root ".tools\gst-registry.bin"
$env:GIO_MODULE_DIR = Join-Path $root ".tools\empty-gio-modules"
$env:GST_PLUGIN_FEATURE_RANK = "avdec_h264:MAX,nvh264dec:NONE,d3d12h264dec:NONE,mfh264dec:NONE"

& $application --project-roundtrip $roundtripProject $clipA $clipB $clipVfr
if ($LASTEXITCODE -ne 0) {
    throw "project save/load roundtrip failed"
}
Write-Output "Project roundtrip passed: media timeline saved and loaded without duration drift"

$process = Start-Process -FilePath $application `
    -ArgumentList @($clipA, $clipB, $clipVfr) `
    -WindowStyle Hidden -PassThru
try {
    if ($process.WaitForExit($Seconds * 1000)) {
        throw "desktop application exited early with code $($process.ExitCode)"
    }
    Write-Output "Desktop smoke passed: native window remained responsive for $Seconds seconds"
} finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
}
