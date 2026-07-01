# capture.ps1 - Windows screenshot wrapper for the `screenshot` Claude Code skill.
# PowerShell port of capture.sh. Prints the absolute path of the saved PNG on stdout.
#
# Usage: powershell -ExecutionPolicy Bypass -File capture.ps1 <mode> [args...]
#
# Modes:
#   full                       Capture the whole virtual desktop (all monitors merged)
#   display <N>                Capture display N (1 = primary; see list_displays.ps1)
#   region <X> <Y> <W> <H>     Capture an exact rectangle (top-left origin, virtual-desktop coords)
#   window <hwnd>              Capture a specific window by handle (see list_windows.ps1)
#   app <appName>              Capture the frontmost window of a named app (substring match)
#   select                     Interactive: user drags a rectangle (Snip & Sketch -> clipboard)
#
# Output goes to $env:CLAUDE_SCREENSHOT_DIR (default: %TEMP%\claude-screenshots\).

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Mode,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

# --- Win32 interop -----------------------------------------------------------
if (-not ('Win32.NativeMethods' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace Win32 {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    public static class NativeMethods {
        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
        [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
        [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
        [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
        [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
        [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    }
}
'@
}

# --- Output path -------------------------------------------------------------
$outDir = if ($env:CLAUDE_SCREENSHOT_DIR) { $env:CLAUDE_SCREENSHOT_DIR } else { Join-Path $env:TEMP 'claude-screenshots' }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outFile = Join-Path $outDir "screenshot-$timestamp.png"

function Show-Usage {
    @"
Usage: capture.ps1 <mode> [args...]

Modes:
  full                       Capture the whole virtual desktop (all monitors)
  display <N>                Capture display N (1 = primary)
  region <X> <Y> <W> <H>     Capture an exact rectangle (top-left origin)
  window <hwnd>              Capture a specific window by handle (see list_windows.ps1)
  app <appName>              Capture the frontmost window of a named app
  select                     Interactive: user drags a rectangle

Output goes to `$env:CLAUDE_SCREENSHOT_DIR (default: %TEMP%\claude-screenshots\).
"@ | Write-Error
    exit 1
}

function Save-Rectangle {
    param([int]$X, [int]$Y, [int]$W, [int]$H)
    if ($W -le 0 -or $H -le 0) { Write-Error "Invalid capture size ${W}x${H}"; exit 2 }
    $bmp = New-Object System.Drawing.Bitmap($W, $H)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $gfx.CopyFromScreen($X, $Y, 0, 0, (New-Object System.Drawing.Size($W, $H)))
    $bmp.Save($outFile, [System.Drawing.Imaging.ImageFormat]::Png)
    $gfx.Dispose(); $bmp.Dispose()
}

function Get-AppWindowHandle {
    param([string]$Query)
    $q = $Query.ToLower()
    $found = [IntPtr]::Zero
    $callback = [Win32.NativeMethods+EnumWindowsProc] {
        param($hWnd, $lParam)
        if (-not [Win32.NativeMethods]::IsWindowVisible($hWnd)) { return $true }
        $len = [Win32.NativeMethods]::GetWindowTextLength($hWnd)
        if ($len -eq 0) { return $true }
        $procId = 0
        [void][Win32.NativeMethods]::GetWindowThreadProcessId($hWnd, [ref]$procId)
        $proc = $null
        try { $proc = Get-Process -Id $procId -ErrorAction Stop } catch { return $true }
        $sb = New-Object System.Text.StringBuilder ($len + 1)
        [void][Win32.NativeMethods]::GetWindowText($hWnd, $sb, $sb.Capacity)
        $title = $sb.ToString()
        if ($proc.ProcessName.ToLower().Contains($q) -or $title.ToLower().Contains($q)) {
            $script:found = $hWnd
            return $false  # stop enumeration (front-to-back: first match is frontmost)
        }
        return $true
    }
    [void][Win32.NativeMethods]::EnumWindows($callback, [IntPtr]::Zero)
    return $script:found
}

function Save-Window {
    param([IntPtr]$Hwnd)
    if ($Hwnd -eq [IntPtr]::Zero) { Write-Error "No matching window found."; exit 3 }
    if ([Win32.NativeMethods]::IsIconic($Hwnd)) {
        [void][Win32.NativeMethods]::ShowWindow($Hwnd, 9)  # SW_RESTORE
        Start-Sleep -Milliseconds 300
    }
    [void][Win32.NativeMethods]::SetForegroundWindow($Hwnd)
    Start-Sleep -Milliseconds 200
    $rect = New-Object Win32.RECT
    [void][Win32.NativeMethods]::GetWindowRect($Hwnd, [ref]$rect)
    $w = $rect.Right - $rect.Left
    $h = $rect.Bottom - $rect.Top
    if ($w -le 0 -or $h -le 0) { Write-Error "Window has no visible area."; exit 2 }
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $gfx.GetHdc()
    # PW_RENDERFULLCONTENT (0x2) captures most hardware-accelerated windows too.
    $ok = [Win32.NativeMethods]::PrintWindow($Hwnd, $hdc, 2)
    $gfx.ReleaseHdc($hdc)
    if (-not $ok) {
        # Fallback: copy the on-screen rectangle directly.
        $gfx.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    }
    $bmp.Save($outFile, [System.Drawing.Imaging.ImageFormat]::Png)
    $gfx.Dispose(); $bmp.Dispose()
}

if (-not $Mode) { Show-Usage }

switch ($Mode.ToLower()) {
    'full' {
        $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
        Save-Rectangle -X $vs.X -Y $vs.Y -W $vs.Width -H $vs.Height
    }
    'display' {
        $n = if ($Args.Count -ge 1) { [int]$Args[0] } else { 1 }
        $screens = [System.Windows.Forms.Screen]::AllScreens
        if ($n -lt 1 -or $n -gt $screens.Count) { Write-Error "No display $n (have $($screens.Count))."; exit 2 }
        $b = $screens[$n - 1].Bounds
        Save-Rectangle -X $b.X -Y $b.Y -W $b.Width -H $b.Height
    }
    'region' {
        if ($Args.Count -lt 4) { Write-Error "region needs X Y W H"; Show-Usage }
        Save-Rectangle -X ([int]$Args[0]) -Y ([int]$Args[1]) -W ([int]$Args[2]) -H ([int]$Args[3])
    }
    'window' {
        if ($Args.Count -lt 1) { Write-Error "window needs <hwnd>"; Show-Usage }
        Save-Window -Hwnd ([IntPtr][int64]$Args[0])
    }
    'app' {
        if ($Args.Count -lt 1) { Write-Error "app needs <appName>"; Show-Usage }
        Save-Window -Hwnd (Get-AppWindowHandle -Query ($Args -join ' '))
    }
    'select' {
        # Snip & Sketch puts the selection on the clipboard; we save it to a PNG.
        Start-Process 'ms-screenclip:' | Out-Null
        Write-Error "Drag a region in Snip & Sketch; waiting up to 60s for the clipboard..."
        $img = $null
        for ($i = 0; $i -lt 120; $i++) {
            Start-Sleep -Milliseconds 500
            $img = [System.Windows.Forms.Clipboard]::GetImage()
            if ($img) { break }
        }
        if (-not $img) { Write-Error "No selection captured."; exit 2 }
        $img.Save($outFile, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    { $_ -in 'help', '-h', '--help' } { Show-Usage }
    default { Write-Error "Unknown mode: $Mode"; Show-Usage }
}

if (-not (Test-Path $outFile)) {
    Write-Error "No screenshot was created."
    exit 2
}

Write-Output (Resolve-Path $outFile).Path
