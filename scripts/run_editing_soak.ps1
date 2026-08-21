param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [ValidateRange(10, 3600)]
    [int]$Seconds = 600,
    [string]$BuildDirectory = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) {
    $BuildDirectory = Join-Path $root "out\build\windows-msvc"
}
$application = Join-Path $BuildDirectory "$Configuration\ffmpegGUI-next.exe"
$mediaDirectory = Join-Path $root "out\test-media\ges-smoke"
$clipA = Join-Path $mediaDirectory "shot-a.mp4"
$clipB = Join-Path $mediaDirectory "shot-b.mkv"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$gstRoot = Join-Path $root ".tools\gstreamer"

foreach ($required in @($application, $clipA, $clipB, $qtRoot, $gstRoot)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "required editing-soak input is missing: $required"
    }
}

$env:PATH = "$qtRoot\bin;$gstRoot\bin;$env:PATH"
$env:QML2_IMPORT_PATH = "$qtRoot\qml"
$env:GST_PLUGIN_PATH = "$gstRoot\lib\gstreamer-1.0"
$env:GST_REGISTRY = Join-Path $root ".tools\gst-registry.bin"
$env:GIO_MODULE_DIR = Join-Path $root ".tools\empty-gio-modules"
$env:GST_PLUGIN_FEATURE_RANK =
    "avdec_h264:MAX,nvh264dec:NONE,d3d12h264dec:NONE,mfh264dec:NONE"

$process = Start-Process -FilePath $application `
    -ArgumentList @("--editing-soak", $Seconds, $clipA, $clipB) `
    -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "editing soak failed with exit code $($process.ExitCode)"
}
Write-Output "Editing soak passed: $Seconds seconds"
