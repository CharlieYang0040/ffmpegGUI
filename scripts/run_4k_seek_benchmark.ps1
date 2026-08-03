param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ffmpeg = Join-Path $root ".tools\ffmpeg\bin\ffmpeg.exe"
$gstRoot = Join-Path $root ".tools\gstreamer"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$mediaDir = Join-Path $root "out\test-media\4k-seek"
$benchmark = Join-Path $root "out\build\windows-msvc\$Configuration\ffgui_ges_seek_benchmark.exe"
$h264 = Join-Path $mediaDir "4k-h264.mp4"
$hevc = Join-Path $mediaDir "4k-hevc.mp4"
$ffprobe = Join-Path $root ".tools\ffmpeg\bin\ffprobe.exe"

New-Item -ItemType Directory -Path $mediaDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $h264 -PathType Leaf)) {
    & $ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i "testsrc2=size=3840x2160:rate=30:duration=4" `
        -c:v h264_nvenc -preset p4 -tune ll -g 30 -pix_fmt yuv420p $h264
    if ($LASTEXITCODE -ne 0) { throw "failed to generate the 4K H.264 fixture with NVENC" }
}
if (-not (Test-Path -LiteralPath $hevc -PathType Leaf)) {
    & $ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i "testsrc2=size=3840x2160:rate=30:duration=4" `
        -c:v hevc_nvenc -preset p4 -tune ll -g 30 -pix_fmt yuv420p $hevc
    if ($LASTEXITCODE -ne 0) { throw "failed to generate the 4K HEVC fixture with NVENC" }
}

foreach ($fixture in @($h264, $hevc)) {
    $size = & $ffprobe -v error -select_streams v:0 `
        -show_entries stream=width,height -of csv=p=0:s=x $fixture
    if ($LASTEXITCODE -ne 0 -or $size.Trim() -ne "3840x2160") {
        throw "4K fixture has an unexpected resolution: $fixture ($size)"
    }
}

$env:PATH = "$qtRoot\bin;$gstRoot\bin;$env:PATH"
$env:GST_PLUGIN_PATH = "$gstRoot\lib\gstreamer-1.0"
$env:GST_REGISTRY = Join-Path $root ".tools\gst-registry.bin"
$env:GIO_MODULE_DIR = Join-Path $root ".tools\empty-gio-modules"
$env:GST_PLUGIN_FEATURE_RANK = "d3d11h264dec:MAX,d3d11h265dec:MAX,nvh264dec:NONE,nvh265dec:NONE,d3d12h264dec:NONE,d3d12h265dec:NONE,mfh264dec:NONE,mfh265dec:NONE"
New-Item -ItemType Directory -Path $env:GIO_MODULE_DIR -Force | Out-Null

& $benchmark $h264 $hevc
exit $LASTEXITCODE
