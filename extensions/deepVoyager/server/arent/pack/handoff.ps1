# arent/pack/handoff.ps1 - THE single round-trip worker for a handoff archive.
#
# Layout on the training box (why heavy stuff survives replacing the code):
#   <root>\RUN.bat     the only launcher; overwrite it every handoff
#   <root>\server\     CODE ONLY (arenas + arent + pack). DELETE and replace freely.
#   <root>\state\      runs\ (models) + data\ (datasets). --home target, persists outside server.
#   <root>\venv\       torch env, persists outside server, never re-downloaded on a code swap.
#
# CONTRACT: running this leaves EXACTLY ONE new file at <root> - result.zip. Nothing else
# (no run.log, no eval_*.log, no handoff_out.txt) may litter the folder next to RUN.bat: every
# log is packed INSIDE result.zip. BY DEFAULT it builds the v2 stack if missing: BC v2 (gen +
# train into state\runs\bc_v2, skipped when the checkpoint already exists), then a team-reward
# PPO warm from bc_v2 into state\runs\ppo_v2 (idempotent: skipped if ppo_v2 exists; bc_v2 is
# NEVER overwritten), then evaluates bc_v2 AND every v2 ppo* on the reserved independent set
# (ho_* + ho2_*), writes the honest comparison, and packs result.zip with BOTH the analysis AND
# a full copy of state\ (the returned zip is itself the backup). Pass -EvalOnly to skip
# training and only compare. Even on failure it still writes result.zip (with an error.txt),
# so the user always has one file back. Old-schema checkpoints (state length different from
# the bc_v2 one) are skipped in discovery - v1 weights cannot poison a v2 comparison.
#
# ASCII only: Windows PowerShell 5.1 mis-parses UTF-8-without-BOM .ps1 bodies.
param(
    [string]$Root = "",        # parent that holds server\ state\ venv\ (default: inferred)
    [string]$Server = "",      # default: <root>\server
    [string]$State = "",       # default: <root>\state   (arent --home)
    [string]$Venv = "",        # default: <root>\venv
    [string]$Work = "",        # scratch dir for all logs (default: %TEMP%\arent_handoff_<pid>)
    [string]$Mode = "cuda",    # cuda | cpu | lite | offline  (used only when the venv must be built)
    [int]$Rounds = 8,
    [string]$Kind = "auto",
    [string]$Bc2Name = "bc_v2",   # BC parent for the v2 schema; built by gen+train when absent
    [int]$BcSamples = 600,        # scenarios for the BC v2 dataset (only used when bc_v2 is absent)
    [int]$Schema = 2,             # task schema: 2 = cell-action (default), 3 = move-plan (team)
    [int]$BcScenarios = 150,      # schema 3: team scenarios generated for the BC/PPO pool
    [string]$Out = "",         # the ONE output file (default <root>\result.zip)
    [switch]$Train,            # kept for backward compat; PPO training is the DEFAULT now (see -EvalOnly)
    [switch]$EvalOnly,         # escape hatch: skip training, only compare existing checkpoints on ho_*
    [string]$PpoName = "ppo_v2",
    [int]$Iters = 120,         # PPO iterations (RlConfig's own default is 60; RL.bat used 120)
    [switch]$SkipEnv          # do not build/verify the venv (used for offline wiring tests)
)
$ErrorActionPreference = "Stop"
$script:log = @()
$script:err = $null
$script:results = @()
$script:trained = $false
$script:report = ""
$script:manifestJson = ""
$script:shaText = ""
$script:setSha = ""
$script:flags = @{ sameSet = $false; allHo = $false; independent = $false }
function Say($m) { $script:log += (Get-Date).ToString("HH:mm:ss") + " " + $m; Write-Output $m }

# ---- schema 3 defaults: distinct run names + evaluate only on the ho3_ holdout ----------
# v2 stays the untouched default (rollback). Under -Schema 3 the BC/PPO parents move to
# bc_v3/ppo_v3 so they never collide with a v2 state\, and the fair comparison set becomes
# exactly the frozen ho3_* arenas (ho_/ho2_ are already used). Caller-supplied names win.
$script:hoBare = if ($Schema -eq 3) { 'ho3_' } else { 'ho2?_' }
$script:hoPattern = '^' + $script:hoBare
if ($Schema -eq 3) {
    if ($Bc2Name -eq 'bc_v2') { $Bc2Name = 'bc_v3' }
    if ($PpoName -eq 'ppo_v2') { $PpoName = 'ppo_v3' }
}

# ---- paths --------------------------------------------------------------------------
if (-not $Server) { $Server = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }  # ...\server
if (-not $Root)   { $Root = Split-Path $Server -Parent }
if (-not $State)  { $State = Join-Path $Root "state" }
if (-not $Venv)   { $Venv = Join-Path $Root "venv" }
if (-not $Out)    { $Out = Join-Path $Root "result.zip" }
if (-not $Work)   { $Work = Join-Path $env:TEMP ("arent_handoff_" + $PID) }
$arentDir = Join-Path $Server "arent"
$main = Join-Path $arentDir "main.py"
$pv = Join-Path $Venv "Scripts\python.exe"
$runs = Join-Path $State "runs"
if (Test-Path $Work) { Remove-Item $Work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Work | Out-Null

# ---- helpers (pure) -----------------------------------------------------------------
function Sha256($path) {
    $s = [System.IO.File]::OpenRead($path)
    try { (Get-FileHash -InputStream $s -Algorithm SHA256).Hash.ToLower() } finally { $s.Dispose() }
}
function Read-Json($path) {
    if (-not (Test-Path $path)) { return $null }
    Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
}
function Resolve-Checkpoint($dir) {
    if (-not (Test-Path $dir)) { return $null }
    foreach ($f in @("model_best.json", "model.json")) {
        $p = Join-Path $dir $f
        if (Test-Path $p) { return @{ dir = $dir; path = $p; which = $f; name = (Split-Path $dir -Leaf) } }
    }
    return $null
}
function Model-Schema($path) {
    # v3 checkpoints stamp dims.schema=3 (and cell_feat 22); v2 have no schema key. dims.state
    # is identical (498) across v2/v3, so it cannot tell the schemas apart - schema can.
    $s = (Read-Json $path).dims.schema
    if ($null -eq $s) { return 2 }
    return [int]$s
}
function Eval-Of($dir) {
    $o = Read-Json (Join-Path $dir "eval.json")
    if (-not $o) { return $null }
    @{ set_tag = $o.provenance.set_tag; testset_sha = $o.provenance.testset_sha256
       model_sha = $o.provenance.model_sha256; model_path = $o.provenance.model_path
       n = $o.fights; survival = $o.survival_rate; clear = $o.clear_rate
       mean_value = $o.mean_value; mean_rounds = $o.mean_rounds; rows = $o.rows; path = (Join-Path $dir "eval.json") }
}
# every log goes into $Work (NEVER the root); run_logged tees live + file
function Invoke-Eval($ckptPath, $evalName) {
    $helper = Join-Path $PSScriptRoot "run_logged.ps1"
    $logPath = Join-Path $Work ("eval_" + $evalName + ".log")
    $pre = if ($Schema -eq 3) { ' --independent-prefix ho3_' } else { '' }
    $a = '"' + $main + '" --home "' + $State + '" evaluate --independent' + $pre + ' --no-live --model "' + $ckptPath + '" --name ' + $evalName + ' --rounds ' + $Rounds + ' --kind ' + $Kind
    & powershell -NoProfile -ExecutionPolicy Bypass -File $helper -Script $pv -Arg $a -Log $logPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "evaluate failed for $ckptPath (exit $LASTEXITCODE)" }
}
# device actually available to THIS venv's torch (cuda only if the driver is really there)
function Detect-Device {
    $q = (& $pv -c "import torch;print('cuda' if torch.cuda.is_available() else 'cpu')" 2>$null)
    if ($q -match "cuda") { return "cuda" }
    return "cpu"
}
# long step: PPO warm from bc_v2 -> state\runs\<name>. Streams live (no Out-Null) so the user sees progress.
function Invoke-Train($name, $iters, $device) {
    $helper = Join-Path $PSScriptRoot "run_logged.ps1"
    $logPath = Join-Path $Work ("rl_" + $name + ".log")
    $v3 = if ($Schema -eq 3) { ' --schema 3 --scenarios ' + $BcScenarios + ' --no-live' } else { '' }
    $a = '"' + $main + '" --home "' + $State + '" rl --warm ' + $Bc2Name + ' --name ' + $name + ' --iters ' + $iters + ' --rounds ' + $Rounds + ' --replays 3 --team-reward --kind torch --device ' + $device + $v3
    Write-Output ("[train] arent rl --warm " + $Bc2Name + " --name " + $name + " --iters " + $iters + " --team-reward --device " + $device + $v3 + "   (live copy -> rl_" + $name + ".log inside result.zip)")
    & powershell -NoProfile -ExecutionPolicy Bypass -File $helper -Script $pv -Arg $a -Log $logPath
    if ($LASTEXITCODE -ne 0) { throw "PPO training failed (exit $LASTEXITCODE) - see rl_" + $name + ".log" }
}
# long step (only when bc_v2 is absent): label a v2 dataset, then BC-train it. kind auto ->
# pure backend when the venv has no torch (RUN.bat --lite); torch path is unchanged otherwise.
function Invoke-Bc($device) {
    $helper = Join-Path $PSScriptRoot "run_logged.ps1"
    $genLog = Join-Path $Work "bc_gen.log"; $trLog = Join-Path $Work "bc_train.log"
    # v2 labels the arena+live pool with the default schema; v3 labels generated TEAM battles
    # (scenarios-only) with the move-plan schema and the strengthened battlecast teacher (F-D).
    $gen = '"' + $main + '" --home "' + $State + '" gen --name ' + $Bc2Name + ' --count ' + $BcSamples + ' --no-live'
    if ($Schema -eq 3) { $gen += ' --schema 3 --scenarios ' + $BcScenarios + ' --scenarios-only --teacher battlecast --teacher-rounds 1 --rounds-max 2 --per-src 4' }
    Write-Output ("[bc] arent gen --name " + $Bc2Name + " --count " + $BcSamples + $(if ($Schema -eq 3) { ' --schema 3 --scenarios ' + $BcScenarios + ' --scenarios-only --teacher battlecast' } else { '' }) + "   (-> bc_gen.log inside result.zip)")
    & powershell -NoProfile -ExecutionPolicy Bypass -File $helper -Script $pv -Arg $gen -Log $genLog
    if ($LASTEXITCODE -ne 0) { throw "BC gen failed (exit $LASTEXITCODE) - see bc_gen.log" }
    $tr = '"' + $main + '" --home "' + $State + '" train --dataset ' + $Bc2Name + ' --name ' + $Bc2Name + ' --kind auto --device ' + $device
    if ($Schema -eq 3) { $tr += ' --schema 3' }
    Write-Output ("[bc] arent train --dataset " + $Bc2Name + " --name " + $Bc2Name + "   (-> bc_train.log inside result.zip)")
    & powershell -NoProfile -ExecutionPolicy Bypass -File $helper -Script $pv -Arg $tr -Log $trLog
    if ($LASTEXITCODE -ne 0) { throw "BC train failed (exit $LASTEXITCODE) - see bc_train.log" }
}
function Groups-Leak-Ho($m) {
    if (-not $m -or -not $m.split) { return -1 }
    $keys = @()
    foreach ($k in @("train_group_keys","val_group_keys","train","val","holdout")) { if ($m.split.$k) { $keys += $m.split.$k } }
    $leak = $keys | Where-Object { $_ -match (("(^|:)" + $script:hoBare)) }
    return @($leak).Count
}
function Torch-Ok {
    if ($Mode -eq "lite") { return $true }
    if (-not (Test-Path $pv)) { return $false }
    & $pv -c "import torch" 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
}

# ---- ALWAYS produce exactly one result.zip (happy path or after an error) -----------
function Publish-Result {
    $stage = Join-Path $Work "stage"
    $an = Join-Path $stage "analysis"; New-Item -ItemType Directory -Force -Path $an | Out-Null
    if ($script:report) { [System.IO.File]::WriteAllText((Join-Path $an "indep_report.txt"), $script:report, [System.Text.UTF8Encoding]::new($false)) }
    if ($script:manifestJson) { [System.IO.File]::WriteAllText((Join-Path $an "indep_manifest.json"), $script:manifestJson, [System.Text.UTF8Encoding]::new($false)) }
    if ($script:shaText) { [System.IO.File]::WriteAllText((Join-Path $an "sha256.txt"), $script:shaText, [System.Text.UTF8Encoding]::new($false)) }
    foreach ($r in $script:results) {
        if ($r.eval -and (Test-Path $r.eval.path)) { Copy-Item $r.eval.path (Join-Path $an ("eval_" + $r.evalName + ".json")) }
        foreach ($pair in @(
            @((Join-Path $r.ck.dir "run_manifest.json"), ($r.ck.name + "_run_manifest.json")),
            @((Join-Path $r.ck.dir "summary.json"),      ($r.ck.name + "_summary.json")),
            @((Join-Path $r.ck.dir "history.json"),      ($r.ck.name + "_history.json")))) {
            if (Test-Path $pair[0]) { Copy-Item $pair[0] (Join-Path $an $pair[1]) }
        }
    }
    # every scratch log (setup/eval/trace) lives inside the archive, never beside RUN.bat
    foreach ($l in (Get-ChildItem $Work -Filter "*.log" -ErrorAction SilentlyContinue)) { Copy-Item $l.FullName (Join-Path $an $l.Name) }
    if ($script:err) { [System.IO.File]::WriteAllText((Join-Path $an "error.txt"), ("HANDOFF FAILED:`r`n" + $script:err), [System.Text.UTF8Encoding]::new($false)) }

    $nl = Join-Path $stage "note"; New-Item -ItemType Directory -Force -Path $nl | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $nl "handoff.log"), ($script:log -join "`r`n"), [System.Text.UTF8Encoding]::new($false))

    # round-trip: carry the WHOLE live state (models + datasets + PPO state) so nothing is lost
    if (Test-Path $State) {
        $stStage = Join-Path $stage "state"; New-Item -ItemType Directory -Force -Path $stStage | Out-Null
        & robocopy $State $stStage /E /NFL /NDL /NJH /NJS /NP /XD "__pycache__" | Out-Null
        $global:LASTEXITCODE = 0
    }
    if (Test-Path $Out) { Remove-Item $Out -Force }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $Out -CompressionLevel Optimal
}

try {
    if (-not (Test-Path $main)) { throw "no arent main.py at $main (server unpacked wrong?)" }
    if (-not (Test-Path $runs)) { throw "no state\runs at $runs (models live outside server on purpose - check the archive carries state\)" }
    Say "root=$Root"; Say "server=$Server"; Say "state=$State"; Say "venv=$Venv"; Say "mode=$Mode"
    Say ("schema=" + $Schema + " bc=" + $Bc2Name + " ppo=" + $PpoName + " eval_prefix=" + $script:hoPattern)

    # ---- venv: build only if the backend is actually missing ------------------------
    if ($SkipEnv) { Say "SkipEnv set - not touching the venv" }
    elseif (Torch-Ok) { Say "venv OK ($pv)" }
    else {
        Say "building root venv at $Venv (mode=$Mode) - torch download up to ~2.4 GB, one-time"
        $setupLog = Join-Path $Work "setup.log"
        if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py"; $pyPre = @("-3") }
        else { $py = "python"; $pyPre = @() }
        & $py @pyPre -m venv $Venv *>> $setupLog
        if ($LASTEXITCODE -ne 0) { throw "venv create failed (install Python 3.10+ and tick Add to PATH)" }
        $ErrorActionPreference = "Continue"
        & $pv -m pip install --retries 8 --timeout 60 --upgrade pip setuptools wheel *>> $setupLog
        if ($Mode -eq "cuda")         { & $pv -m pip install --no-cache-dir --retries 8 --timeout 120 torch==2.5.1+cu121 --index-url https://download.pytorch.org/whl/cu121 --extra-index-url https://pypi.org/simple *>> $setupLog }
        elseif ($Mode -eq "cpu")      { & $pv -m pip install --no-cache-dir --retries 8 --timeout 120 torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple *>> $setupLog }
        elseif ($Mode -eq "offline")  { & $pv -m pip install --no-cache-dir --no-index --find-links (Join-Path $Server "wheels") torch *>> $setupLog }
        if ($Mode -ne "lite" -and $Mode -ne "offline") { & $pv -m pip install --no-cache-dir --retries 5 --timeout 120 numpy *>> $setupLog }
        $ErrorActionPreference = "Stop"
        if (-not (Torch-Ok)) { throw "venv built but torch still not importable (mode=$Mode). Retry: RUN.bat --cpu  or  --lite" }
        Say "venv ready ($pv), torch importable"
    }

    # ---- DEFAULT: build v2 stack (BC if absent, then team-reward PPO), idempotent; -EvalOnly skips --
    if (-not $EvalOnly) {
        $dev = Detect-Device
        $bcDir = Join-Path $runs $Bc2Name
        if (Resolve-Checkpoint $bcDir) {
            Say ("BC '$Bc2Name' already exists -> SKIP gen/train (delete state\runs\" + $Bc2Name + " to rebuild)")
        } else {
            Say ("training BC '$Bc2Name' from generated v2 data: samples=" + $BcSamples + " device=" + $dev + " (LONG step)")
            Invoke-Bc $dev
            if (-not (Resolve-Checkpoint $bcDir)) { throw "BC finished but no '$Bc2Name' checkpoint was written" }
            Say ("BC '$Bc2Name' trained")
        }
        $ppoDir = Join-Path $runs $PpoName
        if (Resolve-Checkpoint $ppoDir) {
            Say ("PPO '$PpoName' already exists -> SKIP training (delete state\runs\" + $PpoName + " to retrain)")
        } elseif (-not (Resolve-Checkpoint $bcDir)) {
            throw "cannot train PPO: no warm parent '$Bc2Name' checkpoint in state\runs"
        } else {
            Say ("training PPO '$PpoName' warm from " + $Bc2Name + " with --team-reward : iters=" + $Iters + " device=" + $dev + " (LONG step)")
            Invoke-Train $PpoName $Iters $dev
            if (-not (Resolve-Checkpoint $ppoDir)) { throw "training finished but no '$PpoName' checkpoint was written" }
            $script:trained = $true
            Say ("PPO '$PpoName' trained")
        }
    }

    # ---- discover checkpoints (bc parent + every SAME-SCHEMA ppo* run) -------------
    # Compare BOTH dims.schema AND dims.state. schema separates v2 from v3 (state is the same
    # 498 for both, so the old state-only guard let a stale v2 ppo leak into a v3 comparison on
    # the 4060); state still drops genuinely older checkpoints (e.g. ppo1 state 472).
    $targets = @()
    $bc2 = Resolve-Checkpoint (Join-Path $runs $Bc2Name)
    $wantSchema = $null; $wantState = $null
    if ($bc2) {
        $targets += @{ role = "bc2"; ck = $bc2 }
        $wantSchema = Model-Schema $bc2.path
        $wantState = (Read-Json $bc2.path).dims.state
    } else { Say "WARNING: no $Bc2Name checkpoint in state\runs" }
    foreach ($d in (Get-ChildItem $runs -Directory -ErrorAction SilentlyContinue)) {
        if ($d.Name -match "^ppo") {
            $c = Resolve-Checkpoint $d.FullName
            if ($c) {
                $dSchema = Model-Schema $c.path
                $dState = (Read-Json $c.path).dims.state
                if (($dSchema -ne $wantSchema) -or ($wantState -and ($dState -ne $wantState))) {
                    Say ("skip " + $d.Name + " (schema " + $dSchema + "/" + $wantSchema + ", state " + $dState + "/" + $wantState + "): not comparable to " + $Bc2Name)
                } else { $targets += @{ role = "ppo"; ck = $c } }
            }
        }
    }
    if ($targets.Count -eq 0) { throw "no checkpoint (bc2 or ppo*) found in state\runs - nothing to evaluate" }

    # ---- evaluate each on the independent set (reuse only a genuinely valid one) ----
    foreach ($t in $targets) {
        $evalName = "ho_" + $t.role + "_" + $t.ck.name
        $evalDir = Join-Path $runs $evalName
        $cur = Eval-Of $evalDir
        # reuse ONLY a same-schema eval: every row must belong to THIS run's holdout prefix, so a
        # stale v2 ho_/ho2_ eval is never recycled into a v3 ho3_ comparison (the earlier leak).
        $rowsHo = (@($cur.rows | Where-Object { $_.name -notmatch $script:hoPattern }).Count -eq 0)
        $valid = ($cur -and $cur.set_tag -eq "independent" -and $cur.n -ge 1 -and $cur.testset_sha -and ($cur.model_sha -eq (Sha256 $t.ck.path)) -and $rowsHo)
        if (-not $valid) {
            if (Test-Path $evalDir) { Remove-Item $evalDir -Recurse -Force }
            Invoke-Eval $t.ck.path $evalName
            $cur = Eval-Of $evalDir
        } else { Say ("reuse valid independent eval for " + $t.ck.name) }
        if (-not $cur) { throw "no eval.json produced for " + $t.ck.name }
        $man = Read-Json (Join-Path $t.ck.dir "run_manifest.json")
        $script:results += @{ role = $t.role; ck = $t.ck; eval = $cur; leak = (Groups-Leak-Ho $man); evalName = $evalName }
    }

    # ---- independence + same-set + table --------------------------------------------
    $setsha = @($script:results | ForEach-Object { $_.eval.testset_sha } | Select-Object -Unique)
    $sameSet = ($setsha.Count -eq 1)
    $allHo = $true
    foreach ($r in $script:results) { if (@($r.eval.rows | Where-Object { $_.name -notmatch $script:hoPattern }).Count -ne 0) { $allHo = $false } }
    $leaks = @($script:results | Where-Object { $_.leak -ne 0 }).Count
    $independent = ($sameSet -and $allHo -and ($leaks -eq 0))
    $script:setSha = ($setsha -join ",")

    $lines = @()
    $lines += ("=== Independent comparison on " + $script:hoPattern + " set. same_testset=" + $sameSet + "  fully_independent=" + $independent + " ===")
    $lines += ""
    $lines += ("{0,-8} {1,-14} {2,-6} {3,-7} {4,-9} {5,-8} {6,-7} {7}" -f "role","run","fights","surviv","clear","mean_val","rounds","ckpt_sha256(12)")
    foreach ($r in $script:results) {
        $lines += ("{0,-8} {1,-14} {2,-6} {3,-7} {4,-9} {5,-8} {6,-7} {7}" -f $r.role, $r.ck.name,
                   $r.eval.n, $r.eval.survival, $r.eval.clear, $r.eval.mean_value, $r.eval.mean_rounds,
                   $r.eval.model_sha.Substring(0,12))
    }
    if (@($script:results | Where-Object { $_.role -eq "ppo" }).Count -eq 0) {
        $lines += ""; $lines += "NO PPO checkpoint present (training skipped via -EvalOnly, no ppo* in state\runs). Run plain RUN.bat to train PPO, then compare."
    }
    $lines += ""
    $lines += "Note: claiming a model is better than bc2 needs fully_independent=true AND a real (non-toy) PPO. A higher one-step accuracy or internal reward is NOT proof."
    $script:report = $lines -join "`r`n"

    $shaLines = @()
    foreach ($r in $script:results) { $shaLines += ($r.eval.model_sha + "  " + $r.ck.path) }
    $shaLines += ("testset_sha256 = " + $script:setSha)
    $script:shaText = $shaLines -join "`r`n"

    $mode = if ($script:trained) { "trained_new_ppo_then_compared_independently" } else { "evaluate_only_no_training" }
    $mnote = if ($script:trained) { "state\ now holds a NEW '$PpoName' checkpoint (team-reward PPO warm from $Bc2Name; the reserved holdout matched by " + $script:hoPattern + " was never in its training/selection); '$Bc2Name' was NOT overwritten. The returned state\ is the backup." } else { "returned state\ contains every model+dataset; it is the backup. Nothing here trained or overwrote weights." }
    $manifest = [ordered]@{
        kind = "handoff_independent_comparison"; mode = $mode; trained_ppo = $script:trained
        schema = $Schema; eval_prefix_pattern = $script:hoPattern
        same_testset = $sameSet; eval_scenes_all_ho = $allHo; ho_leak_in_any_training = ($leaks -gt 0)
        fully_independent = $independent; rounds_cap = $Rounds; eval_kind = $Kind
        models = @($script:results | ForEach-Object { [ordered]@{
            role = $_.role; run = $_.ck.name; checkpoint = $_.ck.path; checkpoint_which = $_.ck.which
            checkpoint_sha256 = $_.eval.model_sha; eval_name = $_.evalName; set_tag = $_.eval.set_tag
            testset_sha256 = $_.eval.testset_sha; fights = $_.eval.n; survival = $_.eval.survival
            clear = $_.eval.clear; mean_value = $_.eval.mean_value; mean_rounds = $_.eval.mean_rounds
            ho_leak_in_training_groups = $_.leak } })
        note = $mnote
    }
    $script:manifestJson = $manifest | ConvertTo-Json -Depth 8
    $script:flags = @{ sameSet = $sameSet; allHo = $allHo; independent = $independent }
}
catch {
    $script:err = $_.Exception.Message
    if ($_.InvocationInfo -and $_.InvocationInfo.ScriptLineNumber) { $script:err += "  (line " + $_.InvocationInfo.ScriptLineNumber + ")" }
    Say ("ERROR: " + $script:err)
}
finally {
    try { Publish-Result } catch { Write-Output ("PUBLISH FAILED: " + $_.Exception.Message) }
    Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path $Out) {
    & (Join-Path $PSScriptRoot "verify_zip.ps1") $Out -Need @("state") 1>$null 2>$null
    Write-Output ""
    if ($script:report) { Write-Output $script:report; Write-Output "" }
    if ($script:err) {
        Write-Output ("result.zip was still written (with error.txt) : " + $Out)
        Write-Output ("ERROR: " + $script:err)
        exit 2
    }
    Write-Output ("result.zip : " + $Out + "  (the ONLY new file next to RUN.bat)")
    Write-Output ("fully_independent=" + $script:flags.independent + "  same_testset=" + $script:flags.sameSet + "  models=" + $script:results.Count)
    exit 0
}
Write-Output "handoff: result.zip was NOT produced (fatal before packaging)"
exit 1
