param(
    [string]$Version = "0.1.0",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][A-Za-z0-9.]+)?$') {
    throw "invalid release version: $Version"
}

$root = Split-Path -Parent $PSScriptRoot
$outRoot = [System.IO.Path]::GetFullPath((Join-Path $root "out"))
$releaseRoot = [System.IO.Path]::GetFullPath((Join-Path $outRoot "release-v$Version"))
$packageName = "ffmpegGUI-next-v$Version-win-x64"
$packageDir = Join-Path $releaseRoot $packageName
$buildDir = Join-Path $root "out\build\windows-msvc\Release"
$sourceExe = Join-Path $buildDir "ffmpegGUI-next.exe"
$qtRoot = Join-Path $root ".tools\Qt\6.10.2\msvc2022_64"
$gstRoot = Join-Path $root ".tools\gstreamer"
$gstBin = Join-Path $gstRoot "bin"
$gstPluginRoot = Join-Path $gstRoot "lib\gstreamer-1.0"
$dumpbin = Get-ChildItem `
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC" `
    -Recurse -Filter dumpbin.exe | Where-Object { $_.FullName -like '*Hostx64\x64*' } |
    Sort-Object FullName -Descending | Select-Object -First 1

if (-not $releaseRoot.StartsWith($outRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "refusing to package outside the project out directory"
}
if ($null -eq $dumpbin) { throw "Visual Studio x64 dumpbin.exe was not found" }
if (-not $SkipBuild) {
    & cmake --build --preset windows-release
    if ($LASTEXITCODE -ne 0) { throw "Release build failed" }
}
if (-not (Test-Path -LiteralPath $sourceExe)) { throw "Release executable is missing" }
if (Test-Path -LiteralPath $releaseRoot) {
    Remove-Item -LiteralPath $releaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null

$packageExe = Join-Path $packageDir "ffmpegGUI-next.exe"
Copy-Item -LiteralPath $sourceExe -Destination $packageExe

$originalPath = $env:PATH
$env:PATH = "$(Join-Path $qtRoot 'bin');$gstBin;$originalPath"
try {
    & (Join-Path $qtRoot "bin\windeployqt.exe") --release --qmldir `
        (Join-Path $root "apps\desktop") --no-translations --compiler-runtime $packageExe
    if ($LASTEXITCODE -ne 0) { throw "windeployqt failed" }
} finally {
    $env:PATH = $originalPath
}

$pluginNames = @(
    "gstaudioconvert.dll", "gstaudiofx.dll", "gstaudiomixer.dll",
    "gstaudioparsers.dll", "gstaudioresample.dll", "gstcompositor.dll",
    "gstcoreelements.dll", "gstd3d11.dll", "gstencoding.dll",
    "gstges.dll", "gstisomp4.dll", "gstlibav.dll", "gstmatroska.dll",
    "gstnle.dll", "gstopengl.dll", "gstplayback.dll", "gstsoundtouch.dll",
    "gsttypefindfunctions.dll", "gstvideoconvertscale.dll", "gstvideofilter.dll",
    "gstvideomixer.dll", "gstvideoparsersbad.dll", "gstvideorate.dll",
    "gstvolume.dll", "gstwasapi2.dll"
)
$pluginTarget = Join-Path $packageDir "lib\gstreamer-1.0"
$scannerTarget = Join-Path $packageDir "libexec\gstreamer-1.0"
$gioTarget = Join-Path $packageDir "lib\gio\modules"
New-Item -ItemType Directory -Path $pluginTarget, $scannerTarget, $gioTarget -Force | Out-Null

$dependencyQueue = [System.Collections.Generic.Queue[string]]::new()
$visited = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase)
foreach ($name in $pluginNames) {
    $source = Join-Path $gstPluginRoot $name
    if (-not (Test-Path -LiteralPath $source)) { throw "missing GStreamer plugin: $name" }
    Copy-Item -LiteralPath $source -Destination $pluginTarget
    $dependencyQueue.Enqueue($source)
}

$scannerSource = Join-Path $gstRoot "libexec\gstreamer-1.0\gst-plugin-scanner.exe"
if (-not (Test-Path -LiteralPath $scannerSource)) { throw "GStreamer plugin scanner is missing" }
Copy-Item -LiteralPath $scannerSource -Destination $scannerTarget
$dependencyQueue.Enqueue($scannerSource)
$dependencyQueue.Enqueue($sourceExe)

while ($dependencyQueue.Count -gt 0) {
    $binary = $dependencyQueue.Dequeue()
    if (-not $visited.Add($binary)) { continue }
    $lines = & $dumpbin.FullName /dependents $binary
    foreach ($line in $lines) {
        if ($line -notmatch '^\s+([A-Za-z0-9_.+-]+\.dll)\s*$') { continue }
        $name = $Matches[1]
        $gstDependency = Join-Path $gstBin $name
        if (-not (Test-Path -LiteralPath $gstDependency)) { continue }
        $target = Join-Path $packageDir $name
        if (-not (Test-Path -LiteralPath $target)) {
            Copy-Item -LiteralPath $gstDependency -Destination $target
        }
        $dependencyQueue.Enqueue($gstDependency)
    }
}

Copy-Item -LiteralPath (Join-Path $gstRoot "etc") -Destination $packageDir -Recurse
$shareTarget = Join-Path $packageDir "share"
New-Item -ItemType Directory -Path $shareTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $gstRoot "share\gstreamer-1.0") -Destination $shareTarget -Recurse
Copy-Item -LiteralPath (Join-Path $gstRoot "share\glib-2.0") -Destination $shareTarget -Recurse
Copy-Item -LiteralPath (Join-Path $gstRoot "share\fontconfig") -Destination $shareTarget -Recurse
$licenseTarget = Join-Path $packageDir "licenses"
New-Item -ItemType Directory -Path $licenseTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $gstRoot "share\licenses") `
    -Destination (Join-Path $licenseTarget "gstreamer") -Recurse

$redistRoot = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Redist\MSVC"
$redistVersion = Get-ChildItem -LiteralPath $redistRoot -Directory |
    Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
if ($null -eq $redistVersion) { throw "MSVC x64 redistributable files were not found" }
$crtRoot = Join-Path $redistVersion.FullName "x64\Microsoft.VC143.CRT"
if (-not (Test-Path -LiteralPath $crtRoot)) { throw "MSVC x64 CRT directory is missing" }
Copy-Item -Path (Join-Path $crtRoot "*.dll") -Destination $packageDir

$notice = @"
ffmpegGUI Next v$Version

This package includes Qt 6.10.2 and GStreamer 1.28.5 runtime components.
It also includes the Microsoft Visual C++ 2022 x64 runtime DLLs.
Qt licensing: https://www.qt.io/licensing/open-source-obligations
GStreamer licensing: https://gstreamer.freedesktop.org/documentation/frequently-asked-questions/licensing.html

The complete GStreamer runtime license collection is included in licenses/gstreamer.
"@
Set-Content -LiteralPath (Join-Path $packageDir "THIRD_PARTY_NOTICES.txt") `
    -Value $notice -Encoding UTF8

$archive = Join-Path $releaseRoot "$packageName.zip"
Compress-Archive -LiteralPath $packageDir -DestinationPath $archive -CompressionLevel Optimal
$hash = Get-FileHash -LiteralPath $archive -Algorithm SHA256
"$($hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($archive))" |
    Set-Content -LiteralPath (Join-Path $releaseRoot "SHA256SUMS.txt") -Encoding ASCII

Write-Output "Release package: $packageDir"
Write-Output "Archive: $archive"
Write-Output "SHA-256: $($hash.Hash.ToLowerInvariant())"
