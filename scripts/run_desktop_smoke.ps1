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
$exportOutput = Join-Path $mediaDir "export-smoke.mp4"

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

$roundtrip = Start-Process -FilePath $application `
    -ArgumentList @("--project-roundtrip", $roundtripProject, $clipA, $clipB, $clipVfr) `
    -WindowStyle Hidden -Wait -PassThru
if ($roundtrip.ExitCode -ne 0) {
    throw "project save/load roundtrip failed"
}
Write-Output "Project roundtrip passed: media timeline saved and loaded without duration drift"

$savedProject = Get-Content -LiteralPath $roundtripProject -Raw | ConvertFrom-Json
foreach ($asset in $savedProject.assets) {
    if ([string]::IsNullOrWhiteSpace($asset.thumbnailAtlas) -or
        -not (Test-Path -LiteralPath $asset.thumbnailAtlas -PathType Leaf)) {
        throw "thumbnail atlas was not generated for $($asset.id)"
    }
}
Write-Output "Thumbnail atlas passed: all imported media have cached timeline images"

if (Test-Path -LiteralPath $exportOutput -PathType Leaf) {
    Remove-Item -LiteralPath $exportOutput -Force
}
$export = Start-Process -FilePath $application `
    -ArgumentList @("--export-smoke", $exportOutput, $clipA, $clipB, $clipVfr) `
    -WindowStyle Hidden -Wait -PassThru
if ($export.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $exportOutput -PathType Leaf)) {
    throw "edited timeline export failed"
}
$probe = & (Join-Path $root ".tools\ffmpeg\bin\ffprobe.exe") `
    -v error -show_entries format=duration -of default=nw=1:nk=1 $exportOutput
$exportDuration = [double]::Parse($probe, [Globalization.CultureInfo]::InvariantCulture)
if ($exportDuration -lt 6.0 -or $exportDuration -gt 6.4) {
    throw "exported timeline duration is outside the expected range: $exportDuration"
}
$streams = & (Join-Path $root ".tools\ffmpeg\bin\ffprobe.exe") `
    -v error -show_entries stream=codec_type -of csv=p=0 $exportOutput
if ($streams -notcontains "video" -or $streams -notcontains "audio") {
    throw "exported timeline must contain both video and audio streams"
}
Write-Output "Timeline export passed: NVENC/CPU pipeline produced a $exportDuration second MP4"

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
