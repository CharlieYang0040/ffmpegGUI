param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [int]$Seconds = 5,
    [string]$BuildDirectory = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$gstRoot = Join-Path $root ".tools\gstreamer"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$mediaDir = Join-Path $root "out\test-media\ges-smoke"
if ([string]::IsNullOrWhiteSpace($BuildDirectory)) {
    $BuildDirectory = Join-Path $root "out\build\windows-msvc"
}
$application = Join-Path $BuildDirectory "$Configuration\ffmpegGUI-next.exe"
$clipA = Join-Path $mediaDir "shot-a.mp4"
$clipB = Join-Path $mediaDir "shot-b.mkv"
$clipVfr = Join-Path $mediaDir "shot-vfr.mkv"
$roundtripProject = Join-Path $mediaDir "roundtrip.ffnext"
$exportOutput = Join-Path $mediaDir "export-smoke.mp4"
$hevcExportOutput = Join-Path $mediaDir "export-hevc-compact.mkv"
$copySource = Join-Path $mediaDir "stream-copy-source.mp4"
$copyProject = Join-Path $mediaDir "stream-copy.ffnext"
$copyOutput = Join-Path $mediaDir "stream-copy-output.mp4"

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
Write-Output "Project roundtrip passed: caption move/trim, undo/redo and SRT import/export survived save/load"

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
if ($exportDuration -lt 5.7 -or $exportDuration -gt 6.1) {
    throw "exported timeline duration is outside the expected range: $exportDuration"
}
$streams = & (Join-Path $root ".tools\ffmpeg\bin\ffprobe.exe") `
    -v error -show_entries stream=codec_type -of csv=p=0 $exportOutput
if ($streams -notcontains "video" -or $streams -notcontains "audio") {
    throw "exported timeline must contain both video and audio streams"
}
$videoSize = & (Join-Path $root ".tools\ffmpeg\bin\ffprobe.exe") `
    -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x $exportOutput
if ($videoSize.Trim() -ne "1280x848") {
    throw "expanded stamp must preserve 1280x720 video pixels and add 64px bars: $videoSize"
}
Write-Output "Timeline export passed: rapid split/undo/redo, 300ms dissolve, clip audio, positioned text and letterbox stamp produced a validated $exportDuration second MP4"

if (Test-Path -LiteralPath $hevcExportOutput -PathType Leaf) {
    Remove-Item -LiteralPath $hevcExportOutput -Force
}
$hevcExport = Start-Process -FilePath $application `
    -ArgumentList @("--export-hevc-smoke", $hevcExportOutput, $clipA, $clipB, $clipVfr) `
    -WindowStyle Hidden -Wait -PassThru
if ($hevcExport.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $hevcExportOutput -PathType Leaf)) {
    throw "compact HEVC MKV preset export failed"
}
$hevcCodec = & (Join-Path $root ".tools\ffmpeg\bin\ffprobe.exe") `
    -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1:nk=1 $hevcExportOutput
if ($hevcCodec.Trim() -ne "hevc") {
    throw "HEVC MKV preset produced unexpected video codec: $hevcCodec"
}
Write-Output "Export preset passed: compact HEVC MKV was encoded and validated"

if (-not (Test-Path -LiteralPath $copySource -PathType Leaf)) {
    & (Join-Path $root ".tools\ffmpeg\bin\ffmpeg.exe") -hide_banner -loglevel error -y `
        -f lavfi -i "testsrc2=size=640x360:rate=30:duration=4" `
        -f lavfi -i "sine=frequency=550:sample_rate=48000:duration=4" `
        -c:v libx264 -pix_fmt yuv420p -g 30 -keyint_min 30 -sc_threshold 0 `
        -c:a aac -shortest $copySource
    if ($LASTEXITCODE -ne 0) { throw "failed to create stream-copy fixture" }
}
$copyAnalysis = Start-Process -FilePath $application `
    -ArgumentList @("--project-roundtrip", $copyProject, $copySource) `
    -WindowStyle Hidden -Wait -PassThru
if ($copyAnalysis.ExitCode -ne 0) { throw "stream-copy fixture analysis failed" }
$copyData = Get-Content -LiteralPath $copyProject -Raw | ConvertFrom-Json
if ($copyData.assets[0].keyframePtsNs.Count -lt 4) {
    throw "stream-copy fixture keyframes were not preserved"
}
$assetId = $copyData.assets[0].id
$copyTailDuration = ([Int64]$copyData.assets[0].durationNs - 2000000000).ToString()
$copyData.clips = @(
    [pscustomobject]@{ id = "copy-a"; assetId = $assetId; sourceInNs = "0"; durationNs = "1000000000" },
    [pscustomobject]@{ id = "copy-b"; assetId = $assetId; sourceInNs = "2000000000"; durationNs = $copyTailDuration }
)
$copyData.captions = @()
if ($null -ne $copyData.stamp) {
    $copyData.stamp.enabled = $false
}
[IO.File]::WriteAllText(
    $copyProject,
    ($copyData | ConvertTo-Json -Depth 8),
    [Text.UTF8Encoding]::new($false))
if (Test-Path -LiteralPath $copyOutput -PathType Leaf) {
    Remove-Item -LiteralPath $copyOutput -Force
}
$copyExport = Start-Process -FilePath $application `
    -ArgumentList @("--export-project-smoke", $copyProject, $copyOutput) `
    -WindowStyle Hidden -Wait -PassThru
if ($copyExport.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $copyOutput -PathType Leaf)) {
    throw "keyframe-aligned stream-copy export failed"
}
$copyDurationText = & (Join-Path $root ".tools\ffmpeg\bin\ffprobe.exe") `
    -v error -show_entries format=duration -of default=nw=1:nk=1 $copyOutput
$copyDuration = [double]::Parse($copyDurationText, [Globalization.CultureInfo]::InvariantCulture)
if ($copyDuration -lt 2.9 -or $copyDuration -gt 3.2) {
    throw "stream-copy output duration is outside the expected range: $copyDuration"
}
Write-Output "Stream-copy passed: two keyframe-aligned cuts were remuxed without re-encoding"

$playback = Start-Process -FilePath $application `
    -ArgumentList @("--playback-smoke", $clipA, $clipB, $clipVfr) `
    -WindowStyle Hidden -Wait -PassThru
if ($playback.ExitCode -ne 0) {
    throw "deferred preview rebuild playback failed with code $($playback.ExitCode)"
}
Write-Output "Preview refresh passed: deferred rebuild was ready before sequence playback"

$previousCpuPreview = $env:FFGUI_FORCE_CPU_PREVIEW
try {
    Remove-Item Env:FFGUI_FORCE_CPU_PREVIEW -ErrorAction SilentlyContinue
    $d3dPlayback = Start-Process -FilePath $application `
        -ArgumentList @("--offscreen-presentation-smoke", "--playback-smoke", $clipA, $clipB, $clipVfr) `
        -Wait -PassThru
    if ($d3dPlayback.ExitCode -ne 0) {
        throw "D3D11 zero-copy presentation failed with code $($d3dPlayback.ExitCode)"
    }
    Write-Output "D3D11 presentation passed: decoded GPU frames reached the exposed Qt scene graph"

    $env:FFGUI_FORCE_CPU_PREVIEW = "1"
    $cpuPlayback = Start-Process -FilePath $application `
        -ArgumentList @("--offscreen-presentation-smoke", "--playback-smoke", $clipA, $clipB, $clipVfr) `
        -Wait -PassThru
    if ($cpuPlayback.ExitCode -ne 0) {
        throw "CPU preview fallback failed with code $($cpuPlayback.ExitCode)"
    }
    Write-Output "CPU preview fallback passed: BGRA frames reached the exposed Qt scene graph"
} finally {
    if ($null -eq $previousCpuPreview) {
        Remove-Item Env:FFGUI_FORCE_CPU_PREVIEW -ErrorAction SilentlyContinue
    } else {
        $env:FFGUI_FORCE_CPU_PREVIEW = $previousCpuPreview
    }
}

$process = Start-Process -FilePath $application `
    -ArgumentList @($clipA, $clipB, $clipVfr) `
    -WindowStyle Hidden -PassThru
try {
    if ($process.WaitForExit($Seconds * 1000)) {
        throw "desktop application exited early with code $($process.ExitCode)"
    }
    Write-Output "Desktop smoke passed: in-process preview application remained responsive for $Seconds seconds"
} finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
}
