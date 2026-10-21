# arent/pack/make_zip.ps1 - build the self-sufficient round-trip archive for the RTX 4060.
#
# The archive unpacks to a folder with EXACTLY this shape, so a heavy handoff never loses work:
#   RUN.bat     the only launcher (double-click it)
#   server\     CODE ONLY (arenas, arent, planner, pack). Safe to delete + replace next handoff.
#   state\      runs\ + data\ - EMPTY by default in v2: RUN.bat builds bc_v2 (gen+train) and
#               ppo_v2 (team-reward PPO) on the 4060 itself. Lives OUTSIDE server so swapping
#               the code folder keeps the models; venv\ is likewise a sibling.
# By DEFAULT the launcher builds the whole v2 stack (BC v2 if absent, then team-reward PPO warm
# from bc_v2 into state\runs\ppo_v2 - idempotent, bc_v2 never overwritten), then compares
# bc_v2 vs the ppo on the independent ho_* + ho2_* set, and writes ONE result.zip back carrying
# both my analysis reports AND a fresh copy of state\ (the returned zip IS the backup).
# RUN.bat --eval-only skips training and only compares; see START_HERE.txt.
#
# What never goes in: .venv (rebuilt at root by RUN.bat), build/dist, logs, __pycache__, .env
# (DeepSeek key), .pip-tmp, wheels, local pilot runs (seeded, not shipped), and the local
# scratch homes (.dryrun_v2, .launcher_test).
param(
    [string]$OutDir = "",
    [string]$Name = "",
    [string]$StateSeed = "",          # OPTIONAL v1-era dir with model_best.json etc. to carry over
    [int]$Schema = 2,                 # 2 = v2 stack (default); 3 = schema-3 archive (RUN.bat trains v3)
    [switch]$Lean                     # explicit code-only request (v2 default is already lean)
)
$ErrorActionPreference = "Stop"

$arent = Split-Path $PSScriptRoot -Parent
$server = Split-Path $arent -Parent
$moduleRoot = Split-Path (Split-Path (Split-Path $server -Parent) -Parent) -Parent
if (-not $Name) { $Name = "arent4060" + $(if ($Schema -eq 3) { "-v3" } else { "" }) + "-" + (Get-Date).ToString("yyyyMMdd") }
if (-not $OutDir) { $OutDir = Join-Path $moduleRoot "temp" }
if (-not $StateSeed) {
    $cand = Join-Path $env:TEMP "arent_ro"
    if (Test-Path (Join-Path $cand "model_best.json")) { $StateSeed = $cand }   # optional v1 carry-over
}

$stage = Join-Path $env:TEMP ($Name + "-stage")
$stageServer = Join-Path $stage "server"
$stageState = Join-Path $stage "state"
$zip = Join-Path $OutDir ($Name + ".zip")
$log = @()

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stageServer | Out-Null
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# server\ ships CODE ONLY: runs\ and data\ belong in state\, so exclude them from the code copy.
$xd = @("$server\.venv", "$arent\build", "$arent\dist", "$arent\.pip-tmp",
        "$server\logs", ".venv", "__pycache__", ".pytest_cache", "wheels",
        "$server\.dryrun_v2", "$server\.launcher_test",
        (Join-Path $arent "runs"), (Join-Path $arent "data"),
        (Join-Path $arent "pack\indep-back"), (Join-Path $arent "pack\results-back"),
        (Join-Path $arent "pack\ab-back"), (Join-Path $arent "pack\logs"))
# collector / launcher runtime outputs must never be baked into a fresh archive
$xf = @(".env", "indep-back.zip", "indep_manifest.json", "indep_report.txt",
        "indep.log", "indep_run.txt", "indep_bc2_ho.log", "indep_ppo_ho.log",
        "results-back.zip", "ab-back.zip", "ppo-back.zip", "logs-back.zip",
        "result.zip", "result_stage", "handoff_out.txt", "handoff_error.txt", "run.log",
        "_pytest.txt", "_pytest2.txt", "_launcher_smoke.ps1", "_launcher_smoke.out",
        "_launcher_setup.ps1", "_zippeek.ps1")
if ($Lean) {
    & robocopy $server $stageServer /E /NFL /NDL /NJH /NJS /NP /XD $xd /XF $xf | Out-Null
} else {
    & robocopy $server $stageServer /E /NFL /NDL /NJH /NJS /NP /XD $xd /XF $xf | Out-Null
}
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }
$global:LASTEXITCODE = 0

# --- the single launcher + a short readme go to the archive ROOT (nothing else clutters it) ---
Copy-Item (Join-Path $PSScriptRoot "RUN.bat") (Join-Path $stage "RUN.bat")
if (Test-Path (Join-Path $PSScriptRoot "START_HERE.txt")) {
    Copy-Item (Join-Path $PSScriptRoot "START_HERE.txt") (Join-Path $stage "START_HERE.txt")
}
# a schema-3 archive carries schema.txt so a bare double-click of RUN.bat trains v3 (bc_v3 +
# ppo_v3, evaluated on ho3_*). Absent/2 = the untouched v2 default. RUN.bat --v2 overrides it.
if ($Schema -eq 3) {
    [System.IO.File]::WriteAllText((Join-Path $stage "schema.txt"), "3",
                                   [System.Text.UTF8Encoding]::new($false))
}

# --- state\ starts EMPTY in v2 (RUN.bat trains bc_v2 + ppo_v2 on the 4060) ------------------
if (-not $Lean) {
    $ssRuns = Join-Path $stageState "runs"
    $ssData = Join-Path $stageState "data"
    New-Item -ItemType Directory -Force -Path $ssRuns | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $ssData "samples") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $ssData "payloads") | Out-Null
    # Compress-Archive skips EMPTY folders - keep the structure with a placeholder; RUN.bat
    # (handoff.ps1) needs state\runs to exist and fills it with bc_v2/ppo_v2 during the run.
    [System.IO.File]::WriteAllText((Join-Path $ssRuns "README.txt"),
        "Empty on purpose. Double-click RUN.bat: it trains bc_v2 + ppo_v2 into this folder.",
        [System.Text.UTF8Encoding]::new($false))

    # OPTIONAL v1-era carry-over: if an old bc2 extraction is provided, ship it as history
    # (the v2 launcher skips old-schema checkpoints in comparison automatically).
    if ($StateSeed -and (Test-Path (Join-Path $StateSeed "model_best.json"))) {
        $bc2 = Join-Path $ssRuns "bc2"
        New-Item -ItemType Directory -Force -Path $bc2 | Out-Null
        foreach ($f in "model.json", "model_best.json", "run_manifest.json", "summary.json", "history.json") {
            $src = Join-Path $StateSeed $f
            if (Test-Path $src) { Copy-Item $src (Join-Path $bc2 $f) }
        }
        foreach ($f in "bcall.jsonl", "bcall.jsonl.meta.json") {
            $src = Join-Path $StateSeed $f
            if (Test-Path $src) { Copy-Item $src (Join-Path $ssData "samples\$f") }
        }
        Write-Output "pack: v1 bc2 seed included (history only; v2 launcher rebuilds bc_v2 itself)"
    }
    if (Test-Path (Join-Path $arent "data\payloads")) {
        & robocopy (Join-Path $arent "data\payloads") (Join-Path $ssData "payloads") /E /NFL /NDL /NJH /NJS /NP | Out-Null
        $global:LASTEXITCODE = 0
    }
}

$must = @("RUN.bat",
          "server\server.py", "server\run_server.bat", "server\requirements.txt",
          "server\points.json", "server\arent\main.py", "server\arent\cli.py",
          "server\arent\train.py", "server\arent\bench.py", "server\arent\capture.py",
          "server\arent\evaluate.py", "server\arent\rl.py", "server\arent\rollout.py",
          "server\arent\rl_setup.py", "server\arent\rl_state.py",
          "server\arent\env.py", "server\arent\torch_rl.py",
          "server\arent\team_reward.py", "server\arent\holdout.py",
          "server\arent\scenarios.py", "server\arent\scenario_layout.py",
          "server\arent\scenario_units.py", "server\arent\teachers.py",
          "server\arent\states.py", "server\arent\spec.py", "server\arent\observe.py",
          "server\planner\initiative.py", "server\planner\turns.py",
          "server\arent\setup.bat", "server\arent\arent.bat", "server\arent\build_exe.bat",
          "server\arent\config.json", "server\arent\requirements.txt",
          "server\arent\pack\handoff.ps1",
          "server\arent\pack\verify_zip.ps1", "server\arent\pack\run_logged.ps1",
          "server\arent\pack\no_quickedit.ps1",
          "server\planner\service.py", "server\playground\arena.py")
if ($Schema -eq 3) {
    # the move-plan / LOS / F-D teacher stack the v3 launcher runs on must ship with the archive
    $must += @("server\planner\los.py", "server\arent\spec3.py", "server\arent\slots_v3.py",
               "server\arent\encode_v3.py", "server\arent\battlecast.py",
               "server\arent\battlecast_heuristics.py", "server\arent\polyenv.py",
               "server\arent\teachers.py", "server\arent\holdout.py")
}
foreach ($rel in $must) {
    if (-not (Test-Path (Join-Path $stage $rel))) { throw "pack: missing $rel" }
}

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
$entries = $archive.Entries
$log += "zip       : $zip"
$log += ("size      : {0:N0} bytes ({1:N2} MB)" -f (Get-Item $zip).Length,
         ((Get-Item $zip).Length / 1MB))
$log += "entries   : $($entries.Count)"
$leak = $entries | Where-Object { $_.FullName -match "\.env$|/build/|/dist/|\.venv/|__pycache__|/logs/|\.pip-tmp/" }
$log += "leaks     : $(if ($leak) { ($leak | ForEach-Object FullName) -join ", " } else { "none" })"
foreach ($group in @("RUN.bat", "server/arent/main.py", "server/playground/arenas", "server/arent/team_reward.py", "state/runs")) {
    $found = $entries | Where-Object { $_.FullName -replace "\\", "/" -like "*$group*" }
    if ($found.Count -eq 0 -and ($group -like "RUN.bat" -or $group -like "*main.py*" -or $group -like "*team_reward.py*" -or $group -like "state/runs")) {
        $log += "CHECK     : $group  MISSING"
    } else {
        $log += ("{0,-24}: {1} file(s)" -f $group, $found.Count)
    }
}
$ho = $entries | Where-Object { $_.FullName -replace "\\", "/" -like "*playground/arenas/ho_*" }
$ho2 = $entries | Where-Object { $_.FullName -replace "\\", "/" -like "*playground/arenas/ho2_*" }
$ho3 = $entries | Where-Object { $_.FullName -replace "\\", "/" -like "*playground/arenas/ho3_*" }
$log += ("ho_* arenas             : {0}" -f $ho.Count)
$log += ("ho2_* arenas            : {0}" -f $ho2.Count)
$log += ("ho3_* arenas            : {0}" -f $ho3.Count)
$sv = if ($Schema -eq 3) { '  (RUN.bat trains bc_v3+ppo_v3, compares on ho3_* only)' } else { '  (v2 default stack)' }
$log += ("schema                  : " + $Schema + $sv)
$archive.Dispose()
Remove-Item $stage -Recurse -Force

$log += "next      : copy the zip to the 4060, unpack the WHOLE thing (RUN.bat beside server\ and state\), double-click RUN.bat, send back result.zip"
$text = $log -join "`r`n"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Write-Output $text
# report goes next to the zip (in temp), never into the repository
[System.IO.File]::WriteAllText((Join-Path $OutDir "last_pack.txt"), $text,
                               [System.Text.UTF8Encoding]::new($false))
