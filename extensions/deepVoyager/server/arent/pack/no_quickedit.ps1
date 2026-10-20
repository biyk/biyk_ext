# arent/pack/no_quickedit.ps1 - turn OFF console QuickEdit for the window running AUTO.bat.
#
# Why: with QuickEdit on, a stray click (or a text selection) in the console grabs the
# output buffer and FREEZES every stdout write - the whole unattended run appears dead
# (CPU/GPU idle, nothing scrolls) until someone presses Enter/Esc. That is exactly the
# "it hung and only continued after I hit Enter" report. Clearing ENABLE_QUICK_EDIT_MODE
# makes clicks harmless, so the keypress-free AUTO.bat flow can never be stalled by hand.
$ErrorActionPreference = "SilentlyContinue"
Add-Type -Namespace ConsoleWin -Name K -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int n);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr h, out int m);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr h, int m);
'@
$STD_INPUT = -10
$ENABLE_EXTENDED_FLAGS = 0x80   # required to be set for the quick-edit bit to take effect
$ENABLE_QUICK_EDIT_MODE = 0x40  # the bit that lets a mouse selection block output
$h = [ConsoleWin.K]::GetStdHandle($STD_INPUT)
if ($h -and $h.ToInt64() -ne -1) {
    $mode = 0
    if ([ConsoleWin.K]::GetConsoleMode($h, [ref]$mode)) {
        $new = ($mode -band (-bnot $ENABLE_QUICK_EDIT_MODE)) -bor $ENABLE_EXTENDED_FLAGS
        [void][ConsoleWin.K]::SetConsoleMode($h, $new)
    }
}
exit 0
