param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [ValidateRange(10, 86400)]
    [int]$Seconds = 60
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$gstRoot = Join-Path $root ".tools\gstreamer"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$mediaDir = Join-Path $root "out\test-media\4k-seek"
$h264 = Join-Path $mediaDir "4k-h264.mp4"
$hevc = Join-Path $mediaDir "4k-hevc.mp4"
$soak = Join-Path $root "out\build\windows-msvc\$Configuration\ffgui_ges_playback_soak.exe"

if (-not (Test-Path -LiteralPath $h264 -PathType Leaf) -or
    -not (Test-Path -LiteralPath $hevc -PathType Leaf)) {
    & (Join-Path $PSScriptRoot "run_4k_seek_benchmark.ps1") -Configuration $Configuration
    if ($LASTEXITCODE -ne 0) { throw "failed to prepare the 4K soak fixtures" }
}
if (-not (Test-Path -LiteralPath $soak -PathType Leaf)) {
    throw "soak executable is missing; build the $Configuration preset first"
}

$env:PATH = "$qtRoot\bin;$gstRoot\bin;$env:PATH"
$env:GST_PLUGIN_PATH = "$gstRoot\lib\gstreamer-1.0"
$env:GST_REGISTRY = Join-Path $root ".tools\gst-registry.bin"
$env:GIO_MODULE_DIR = Join-Path $root ".tools\empty-gio-modules"
$env:GST_PLUGIN_FEATURE_RANK = "d3d11h264dec:MAX,d3d11h265dec:MAX,nvh264dec:NONE,nvh265dec:NONE,d3d12h264dec:NONE,d3d12h265dec:NONE,mfh264dec:NONE,mfh265dec:NONE"
New-Item -ItemType Directory -Path $env:GIO_MODULE_DIR -Force | Out-Null

& $soak $h264 $hevc $Seconds
exit $LASTEXITCODE
