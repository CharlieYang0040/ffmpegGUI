param(
    [string]$FFmpegPath,
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($FFmpegPath)) {
    $FFmpegPath = Join-Path $root ".tools\ffmpeg\bin\ffmpeg.exe"
}
$ffmpeg = (Resolve-Path -LiteralPath $FFmpegPath).Path
$mediaDir = Join-Path $root "out\test-media\ges-smoke"
$gstRoot = Join-Path $root ".tools\gstreamer"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$smokeExe = Join-Path $root "out\build\windows-msvc\$Configuration\ffgui_ges_smoke.exe"

New-Item -ItemType Directory -Path $mediaDir -Force | Out-Null
$clipA = Join-Path $mediaDir "shot-a.mp4"
$clipB = Join-Path $mediaDir "shot-b.mkv"
$clipVfr = Join-Path $mediaDir "shot-vfr.mkv"

if (-not (Test-Path -LiteralPath $clipA)) {
    & $ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i "testsrc2=size=640x360:rate=30:duration=2" `
        -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=2" `
        -c:v libx264 -pix_fmt yuv420p -g 30 -c:a aac -shortest $clipA
    if ($LASTEXITCODE -ne 0) { throw "failed to generate MP4 fixture" }
}

if (-not (Test-Path -LiteralPath $clipB)) {
    & $ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i "testsrc2=size=640x360:rate=24:duration=2" `
        -f lavfi -i "sine=frequency=660:sample_rate=48000:duration=2" `
        -c:v libx264 -pix_fmt yuv420p -g 24 -c:a aac -shortest $clipB
    if ($LASTEXITCODE -ne 0) { throw "failed to generate MKV fixture" }
}

if (-not (Test-Path -LiteralPath $clipVfr)) {
    & $ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i "testsrc2=size=640x360:rate=30:duration=2" `
        -f lavfi -i "sine=frequency=880:sample_rate=48000:duration=2.3" `
        -vf "setpts=N/(30*TB)+if(gte(N\,30)\,0.2/TB\,0)" `
        -fps_mode vfr -c:v libx264 -pix_fmt yuv420p -g 30 -c:a aac -shortest $clipVfr
    if ($LASTEXITCODE -ne 0) { throw "failed to generate VFR MKV fixture" }
}

$env:PATH = "$qtRoot\bin;$gstRoot\bin;$env:PATH"
$env:GST_PLUGIN_PATH = "$gstRoot\lib\gstreamer-1.0"
$env:GST_REGISTRY = Join-Path $root ".tools\gst-registry.bin"
$env:GIO_MODULE_DIR = Join-Path $root ".tools\empty-gio-modules"
$env:GST_PLUGIN_FEATURE_RANK = "avdec_h264:MAX,nvh264dec:NONE,d3d12h264dec:NONE,mfh264dec:NONE"
$env:G_DEBUG = "fatal-criticals"
New-Item -ItemType Directory -Path $env:GIO_MODULE_DIR -Force | Out-Null

& $smokeExe $clipA $clipB $clipVfr
exit $LASTEXITCODE
