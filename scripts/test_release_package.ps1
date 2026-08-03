param(
    [string]$Version = "0.1.0",
    [int]$Seconds = 8,
    [string]$PackageDir
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PackageDir)) {
    $PackageDir = Join-Path $root "out\release-v$Version\ffmpegGUI-next-v$Version-win-x64"
}
$packageDir = [System.IO.Path]::GetFullPath($PackageDir)
$application = Join-Path $packageDir "ffmpegGUI-next.exe"
$mediaDir = Join-Path $root "out\test-media\ges-smoke"
$media = @(
    (Join-Path $mediaDir "shot-a.mp4"),
    (Join-Path $mediaDir "shot-b.mkv"),
    (Join-Path $mediaDir "shot-vfr.mkv")
)
foreach ($required in @($application) + $media) {
    if (-not (Test-Path -LiteralPath $required)) { throw "missing package test file: $required" }
}

$savedEnvironment = @{}
foreach ($name in @(
    "PATH", "QML2_IMPORT_PATH", "QT_PLUGIN_PATH", "GST_PLUGIN_PATH",
    "GST_PLUGIN_SYSTEM_PATH", "GST_PLUGIN_PATH_1_0", "GST_PLUGIN_SYSTEM_PATH_1_0",
    "GST_REGISTRY", "GST_REGISTRY_1_0", "GST_PLUGIN_SCANNER", "GIO_MODULE_DIR")) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    [Environment]::SetEnvironmentVariable($name, $null, "Process")
}
$env:PATH = "C:\Windows\System32;C:\Windows"

try {
    $roundtrip = Join-Path $mediaDir "packaged-roundtrip.ffnext"
    $roundtripArguments = @("--project-roundtrip", $roundtrip) + $media
    $roundtripProcess = Start-Process -FilePath $application -ArgumentList $roundtripArguments `
        -WindowStyle Hidden -Wait -PassThru
    if ($roundtripProcess.ExitCode -ne 0) { throw "packaged project roundtrip failed" }
    $project = Get-Content -LiteralPath $roundtrip -Raw | ConvertFrom-Json
    $vfrAsset = $project.assets | Where-Object { $_.path -like '*shot-vfr.mkv' } | Select-Object -First 1
    if ($null -eq $vfrAsset -or @($vfrAsset.framePtsNs).Count -lt 2) {
        throw "packaged FFprobe did not persist frame timestamps"
    }
    $timestamps = @($vfrAsset.framePtsNs | ForEach-Object { [int64]$_ })
    $maximumGap = 0L
    for ($index = 1; $index -lt $timestamps.Count; ++$index) {
        $maximumGap = [math]::Max($maximumGap, $timestamps[$index] - $timestamps[$index - 1])
    }
    if ($maximumGap -lt 100000000) {
        throw "packaged FFprobe lost the VFR timestamp gap"
    }
    $audioPeaks = @($vfrAsset.audioPeaks | ForEach-Object { [double]$_ })
    if ($audioPeaks.Count -lt 100 -or ($audioPeaks | Measure-Object -Maximum).Maximum -lt 0.99) {
        throw "packaged FFmpeg did not generate a normalized audio waveform"
    }

    $playbackArguments = @("--playback-smoke") + $media
    $process = Start-Process -FilePath $application -ArgumentList $playbackArguments `
        -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit($Seconds * 1000)) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
        throw "packaged playback smoke timed out"
    }
    if ($process.ExitCode -ne 0) { throw "packaged timeline playback failed" }
    Write-Output "Standalone package PTS, waveform and playback passed without development PATH entries"
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
    }
}
