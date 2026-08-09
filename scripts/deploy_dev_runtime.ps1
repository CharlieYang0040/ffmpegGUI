param(
    [Parameter(Mandatory = $true)][string]$Application,
    [Parameter(Mandatory = $true)][string]$Configuration,
    [Parameter(Mandatory = $true)][string]$QtRoot,
    [Parameter(Mandatory = $true)][string]$GStreamerRoot
)

$ErrorActionPreference = "Stop"
$application = [System.IO.Path]::GetFullPath($Application)
$target = Split-Path -Parent $application
$gstBin = Join-Path $GStreamerRoot "bin"
$gstPluginRoot = Join-Path $GStreamerRoot "lib\gstreamer-1.0"
$deploy = Join-Path $QtRoot "bin\windeployqt.exe"
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) { throw "application is missing" }
if (-not (Test-Path -LiteralPath $deploy -PathType Leaf)) { throw "windeployqt is missing" }

$mode = if ($Configuration -eq "Debug") { "--debug" } else { "--release" }
& $deploy $mode --qmldir (Join-Path (Split-Path -Parent $PSScriptRoot) "apps\desktop") `
    --no-translations --no-compiler-runtime --verbose 0 $application
if ($LASTEXITCODE -ne 0) { throw "windeployqt failed" }

$pluginNames = @(
    "gstapp.dll", "gstaudioconvert.dll", "gstaudiofx.dll", "gstaudiomixer.dll",
    "gstaudioparsers.dll", "gstaudioresample.dll", "gstaudiotestsrc.dll",
    "gstcompositor.dll", "gstcoreelements.dll",
    "gstd3d11.dll", "gstencoding.dll", "gstges.dll", "gstisomp4.dll", "gstlibav.dll",
    "gstmatroska.dll", "gstnle.dll", "gstopengl.dll", "gstplayback.dll", "gstsoundtouch.dll",
    "gsttypefindfunctions.dll", "gstvideoconvertscale.dll", "gstvideofilter.dll",
    "gstvideomixer.dll", "gstvideoparsersbad.dll", "gstvideorate.dll", "gstvideotestsrc.dll",
    "gstvolume.dll",
    "gstwasapi2.dll"
)
$pluginTarget = Join-Path $target "lib\gstreamer-1.0"
$scannerTarget = Join-Path $target "libexec\gstreamer-1.0"
New-Item -ItemType Directory -Path $pluginTarget, $scannerTarget -Force | Out-Null

$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$installation = & $vswhere -latest -products * -property installationPath
$dumpbin = Get-ChildItem (Join-Path $installation "VC\Tools\MSVC") -Recurse -Filter dumpbin.exe |
    Where-Object { $_.FullName -like '*Hostx64\x64*' } |
    Sort-Object FullName -Descending | Select-Object -First 1
if ($null -eq $dumpbin) { throw "dumpbin is missing" }

$queue = [System.Collections.Generic.Queue[string]]::new()
$visited = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase)
foreach ($name in $pluginNames) {
    $source = Join-Path $gstPluginRoot $name
    if (-not (Test-Path -LiteralPath $source)) { throw "GStreamer plugin is missing: $name" }
    Copy-Item -LiteralPath $source -Destination $pluginTarget -Force
    $queue.Enqueue($source)
}
$scanner = Join-Path $GStreamerRoot "libexec\gstreamer-1.0\gst-plugin-scanner.exe"
Copy-Item -LiteralPath $scanner -Destination $scannerTarget -Force
$queue.Enqueue($scanner)
$queue.Enqueue($application)

while ($queue.Count -gt 0) {
    $binary = $queue.Dequeue()
    if (-not $visited.Add($binary)) { continue }
    foreach ($line in (& $dumpbin.FullName /dependents $binary)) {
        if ($line -notmatch '^\s+([A-Za-z0-9_.+-]+\.dll)\s*$') { continue }
        $source = Join-Path $gstBin $Matches[1]
        if (-not (Test-Path -LiteralPath $source)) { continue }
        Copy-Item -LiteralPath $source -Destination $target -Force
        $queue.Enqueue($source)
    }
}

$marker = Join-Path $target ".runtime-deployed"
Set-Content -LiteralPath $marker -Value "Qt and GStreamer runtime deployed for $Configuration" -Encoding UTF8
