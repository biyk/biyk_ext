# arent/pack/run_logged.ps1 - run a command, show output LIVE on the console AND save it.
#
# Used by AUTO.bat / RUN_ALL.bat for the long steps (setup / bench / train). Tee-Object both
# writes every line to -Log in real time and lets it reach the screen, so the operator sees
# progress and we still keep the exact output on disk even if the window is later killed.
# The child command's exit code is propagated so the caller can check errorlevel.
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$Arg = "",
    [Parameter(Mandatory = $true)][string]$Log
)
$ErrorActionPreference = "Continue"
if (Test-Path $Log) { Remove-Item $Log -Force }
# The script path is always wrapped in quotes (safe for spaces); args follow. cmd merges
# stderr into stdout (2>&1) BEFORE PowerShell sees it, so Tee writes clean lines with no
# NativeCommandError noise, while the same text still reaches the console live.
$inner = '"' + $Script + '" ' + $Arg + ' 2>&1'
& cmd.exe /c $inner | Tee-Object -FilePath $Log
exit $LASTEXITCODE
