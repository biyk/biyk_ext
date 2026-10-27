# tests\run_full.ps1 — полный прогон pytest с логом (обходит проблему кавыстей в -Command).
$proj = 'C:\Users\b5\AppData\Local\FoundryVTT\Data\modules\biyk_ext\extensions\deepVoyager\server'
Set-Location $proj
# ядро arent через torch-интерпретатор; тесты сервера (нужен dotenv из server/.venv) исключаем (§5).
& (Join-Path $proj 'arent\.venv\Scripts\python.exe') -m pytest tests -q --tb=short `
    --ignore=tests/test_server_log.py --ignore=tests/test_server_routes.py *>&1 |
    Tee-Object -FilePath (Join-Path $proj 'tests_full_run.log')
