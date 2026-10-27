# tests\run_pt.ps1 — быстрый запуск pytest с аргументами из командной строки tools.
param([Parameter(ValueFromRemainingArguments = $true)] $Args_)
$proj = 'C:\Users\b5\AppData\Local\FoundryVTT\Data\modules\biyk_ext\extensions\deepVoyager\server'
Set-Location $proj
& (Join-Path $proj '.venv\Scripts\python.exe') -m pytest @Args_
