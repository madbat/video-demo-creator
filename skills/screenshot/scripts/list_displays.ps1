# list_displays.ps1 - lists active displays in the order capture.ps1's `display` mode uses.
# Windows port of list_displays.sh.
# Output (tab-separated): <displayNumber>\t<width>x<height>\t<main|secondary>
#
# Note: `capture.ps1 display N` is 1-indexed and matches the order printed here.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

$i = 1
foreach ($s in [System.Windows.Forms.Screen]::AllScreens) {
    $role = if ($s.Primary) { 'main' } else { 'secondary' }
    Write-Output ("{0}`t{1}x{2}`t{3}" -f $i, $s.Bounds.Width, $s.Bounds.Height, $role)
    $i++
}
