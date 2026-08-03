param(
    [string]$QtVersion = "6.10.2",
    [string]$GStreamerVersion = "1.28.5",
    [string]$FFmpegVersion = "8.1.2"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$toolsRoot = Join-Path $root ".tools"
$qtRoot = Join-Path $toolsRoot "Qt"
$qtInstall = Join-Path $qtRoot "$QtVersion\msvc2022_64"
$gstInstall = Join-Path $toolsRoot "gstreamer"
$downloads = Join-Path $toolsRoot "downloads"
$venv = Join-Path $toolsRoot "aqt-venv"
$installerName = "gstreamer-1.0-msvc-x86_64-$GStreamerVersion.exe"
$installer = Join-Path $downloads $installerName
$gstUrl = "https://gstreamer.freedesktop.org/data/pkg/windows/$GStreamerVersion/msvc/$installerName"
$knownGStreamerHash = "51ee5eaec33008e8409d8cf6f6884457f22aa3bd515f8856f993a3eaab903530"
$ffmpegInstall = Join-Path $toolsRoot "ffmpeg"
$ffmpegArchiveName = "ffmpeg-$FFmpegVersion-essentials_build.zip"
$ffmpegArchive = Join-Path $downloads $ffmpegArchiveName
$ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/packages/$ffmpegArchiveName"
$knownFFmpegHash = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"

New-Item -ItemType Directory -Path $toolsRoot, $downloads -Force | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $qtInstall "bin\qmake.exe"))) {
    if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
        py -3 -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Python 3 is required to install Qt" }
    }
    $venvPython = Join-Path $venv "Scripts\python.exe"
    & $venvPython -m pip install --disable-pip-version-check "aqtinstall==3.3.0"
    if ($LASTEXITCODE -ne 0) { throw "failed to install aqtinstall" }
    & $venvPython -m aqt install-qt windows desktop $QtVersion win64_msvc2022_64 `
        --outputdir $qtRoot
    if ($LASTEXITCODE -ne 0) { throw "failed to install Qt $QtVersion" }
}

if (-not (Test-Path -LiteralPath (Join-Path $gstInstall "bin\gst-launch-1.0.exe"))) {
    if (-not (Test-Path -LiteralPath $installer)) {
        Invoke-WebRequest -Uri $gstUrl -OutFile $installer
    }
    $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($GStreamerVersion -eq "1.28.5" -and $actualHash -ne $knownGStreamerHash) {
        throw "GStreamer installer SHA-256 mismatch: $actualHash"
    }
    $install = Start-Process -FilePath $installer `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$gstInstall") `
        -WindowStyle Hidden -Wait -PassThru
    if ($install.ExitCode -ne 0) {
        throw "GStreamer installer failed with code $($install.ExitCode)"
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $ffmpegInstall "bin\ffmpeg.exe"))) {
    if (-not (Test-Path -LiteralPath $ffmpegArchive)) {
        Invoke-WebRequest -Uri $ffmpegUrl -OutFile $ffmpegArchive
    }
    $actualHash = (Get-FileHash -LiteralPath $ffmpegArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($FFmpegVersion -eq "8.1.2" -and $actualHash -ne $knownFFmpegHash) {
        throw "FFmpeg archive SHA-256 mismatch: $actualHash"
    }
    $extractRoot = Join-Path $toolsRoot "ffmpeg-extract"
    $resolvedTools = [System.IO.Path]::GetFullPath($toolsRoot)
    $resolvedExtract = [System.IO.Path]::GetFullPath($extractRoot)
    if (-not $resolvedExtract.StartsWith($resolvedTools, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing to replace an extraction directory outside .tools"
    }
    if (Test-Path -LiteralPath $resolvedExtract) {
        Remove-Item -LiteralPath $resolvedExtract -Recurse -Force
    }
    Expand-Archive -LiteralPath $ffmpegArchive -DestinationPath $resolvedExtract
    $packageRoot = Get-ChildItem -LiteralPath $resolvedExtract -Directory | Select-Object -First 1
    if ($null -eq $packageRoot -or -not (Test-Path -LiteralPath (Join-Path $packageRoot.FullName "bin\ffmpeg.exe"))) {
        throw "FFmpeg archive layout is invalid"
    }
    Move-Item -LiteralPath $packageRoot.FullName -Destination $ffmpegInstall
    Remove-Item -LiteralPath $resolvedExtract -Recurse -Force
}

Write-Output "Native dependencies are ready."
Write-Output "Qt: $qtInstall"
Write-Output "GStreamer: $gstInstall"
Write-Output "FFmpeg: $ffmpegInstall"
