# list_windows.ps1 - lists visible application windows with their window handle (HWND).
# Windows port of list_windows.sh.
# Output (tab-separated): <hwnd>\t<appName>\t<windowTitle>

$ErrorActionPreference = 'Stop'

if (-not ('Win32.WindowList' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace Win32 {
    public static class WindowList {
        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
        [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
        [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
        [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    }
}
'@
}

$results = New-Object System.Collections.Generic.List[string]

$callback = [Win32.WindowList+EnumWindowsProc] {
    param($hWnd, $lParam)
    if (-not [Win32.WindowList]::IsWindowVisible($hWnd)) { return $true }
    $len = [Win32.WindowList]::GetWindowTextLength($hWnd)
    if ($len -eq 0) { return $true }
    $sb = New-Object System.Text.StringBuilder ($len + 1)
    [void][Win32.WindowList]::GetWindowText($hWnd, $sb, $sb.Capacity)
    $title = $sb.ToString()
    $procId = 0
    [void][Win32.WindowList]::GetWindowThreadProcessId($hWnd, [ref]$procId)
    $name = ''
    try { $name = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { return $true }
    $results.Add(("{0}`t{1}`t{2}" -f [int64]$hWnd, $name, $title))
    return $true
}

[void][Win32.WindowList]::EnumWindows($callback, [IntPtr]::Zero)
$results | ForEach-Object { Write-Output $_ }
