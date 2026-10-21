# arent/pack/indep_eval.ps1 - honest bc2 vs PPO comparison on the RESERVED independent set.
#
# Variant B (consultant): train NOTHING, create NO new weights. Only EVALUATE the already
# existing checkpoints (runs\bc2, runs\ppo_pilot) on the reserved ho_* scenarios
# (`evaluate --independent`) and return the FULL artifacts: every fight, manifests, SHA-256,
# the exact checkpoint id, seeds, and the PPO training log/history if present.
#
# Safety rules:
#   * we never touch model*/summary/run_manifest of bc2/ppo or the datasets - read + copy only;
#   * we overwrite ONLY our own eval_bc2_ho / eval_ppo_ho result dirs (results, not weights);
#   * if both existing evaluations are valid AND cover the same set (identical
#     testset_sha256) we do NOT re-run (REUSE); otherwise exactly one re-evaluation.
# ASCII only on purpose: Windows PowerShell 5.1 mis-parses UTF-8-without-BOM .ps1 bodies.
param(
    [Parameter(Mandatory = $true)][string]$Arent,   # path to server\arent
    [string]$Bc2Name = "bc2",
    [string]$PpoName = "ppo_pilot",
    [int]$Rounds = 8,
    [string]$Kind = "torch",
    [switch]$Force,                                 # re-evaluate even if a valid eval exists
    [string]$OutZip = ""                            # indep-back.zip (defaults next to pack\)
)
$ErrorActionPreference = "Stop"

$runs = Join-Path $Arent "runs"
if (-not (Test-Path $runs)) { throw "no runs folder: $runs" }

function Resolve-Checkpoint($name) {
    # prefer model_best.json (selected NOT on ho_* - see the independence check below)
    $dir = Join-Path $runs $name
    foreach ($f in @("model_best.json", "model.json")) {
        $p = Join-Path $dir $f
        if (Test-Path $p) { return @{ dir = $dir; path = $p; which = $f } }
    }
    return $null
}

function Sha256($path) {
    $stream = [System.IO.File]::OpenRead($path)
    try { (Get-FileHash -InputStream $stream -Algorithm SHA256).Hash.ToLower() }
    finally { $stream.Dispose() }
}

function Read-Json($path) {
    if (-not (Test-Path $path)) { return $null }
    Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Eval-Summary($dir) {
    $ev = Join-Path $dir "eval.json"
    $o = Read-Json $ev
    if (-not $o) { return $null }
    @{
        exists = $true; path = $ev
        set_tag = $o.provenance.set_tag
        testset_sha = $o.provenance.testset_sha256
        model_sha = $o.provenance.model_sha256
        model_path = $o.provenance.model_path
        n = $o.fights; survival = $o.survival_rate; clear = $o.clear_rate
        mean_value = $o.mean_value; mean_rounds = $o.mean_rounds
        rows = $o.rows
    }
}

$bc2 = Resolve-Checkpoint $Bc2Name
$ppo = Resolve-Checkpoint $PpoName
if (-not $bc2) { throw "no bc2 checkpoint ($Bc2Name): nothing to evaluate, we do not train here" }
if (-not $ppo) {
    throw "no PPO checkpoint ($PpoName). Variant B forbids training: a PPO run must already exist."
}

# --- what already exists, and is it valid ------------------------------------------
$evalBc2Dir = Join-Path $runs "eval_bc2_ho"
$evalPpoDir = Join-Path $runs "eval_ppo_ho"
$curBc2 = Eval-Summary $evalBc2Dir
$curPpo = Eval-Summary $evalPpoDir

function Is-Valid($e) {
    $e -and $e.exists -and $e.set_tag -eq "independent" -and $e.n -ge 1 -and $e.testset_sha
}
$reuse = (-not $Force) -and (Is-Valid $curBc2) -and (Is-Valid $curPpo) -and
         ($curBc2.testset_sha -eq $curPpo.testset_sha)

# --- if needed: re-run ONLY the EVALUATION of the existing weights on a common set --
$arentBat = Join-Path $Arent "arent.bat"
$helper = Join-Path $PSScriptRoot "run_logged.ps1"
function Invoke-Eval($ckptPath, $evalDirName, $logPath) {
    $d = Join-Path $runs $evalDirName
    if (Test-Path $d) { Remove-Item $d -Recurse -Force }   # only the eval result, never weights
    $arglist = "evaluate --independent --model `"$ckptPath`" --name $evalDirName --rounds $Rounds --kind $Kind"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $helper -Script $arentBat -Arg $arglist -Log $logPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "evaluate failed ($evalDirName), exit=$LASTEXITCODE - see $logPath" }
}

if ($reuse) {
    Write-Output "REUSE: both independent evals are already valid on the same set - not re-running."
} else {
    Write-Output "RECOMPUTE: running evaluate --independent for bc2 and PPO (eval, not training)."
    Invoke-Eval $bc2.path "eval_bc2_ho" (Join-Path $PSScriptRoot "indep_bc2_ho.log")
    Invoke-Eval $ppo.path "eval_ppo_ho" (Join-Path $PSScriptRoot "indep_ppo_ho.log")
    $curBc2 = Eval-Summary $evalBc2Dir
    $curPpo = Eval-Summary $evalPpoDir
}
if (-not $curBc2 -or -not $curPpo) { throw "missing eval.json for one of the two models" }

$sameSet = ($curBc2.testset_sha -eq $curPpo.testset_sha)

# --- independence proof from the run manifests -------------------------------------
function Groups-Leak-Ho($manifest) {
    if (-not $manifest -or -not $manifest.split) { return -1 }        # no split block - cannot confirm
    $keys = @()
    if ($manifest.split.train_group_keys) { $keys += $manifest.split.train_group_keys }
    if ($manifest.split.val_group_keys) { $keys += $manifest.split.val_group_keys }
    if ($manifest.split.train) { $keys += $manifest.split.train }
    if ($manifest.split.val) { $keys += $manifest.split.val }
    if ($manifest.split.holdout) { $keys += $manifest.split.holdout }
    $leak = $keys | Where-Object { $_ -match "(^|:)ho_" }
    return @($leak).Count
}
$bc2Man = Read-Json (Join-Path $bc2.dir "run_manifest.json")
$ppoMan = Read-Json (Join-Path $ppo.dir "run_manifest.json")
$bc2Leak = Groups-Leak-Ho $bc2Man
$ppoLeak = Groups-Leak-Ho $ppoMan

function Rows-All-Ho($rows) { (@($rows | Where-Object { $_.name -notmatch "^ho_" }).Count) -eq 0 }
$bc2EvalHo = Rows-All-Ho $curBc2.rows
$ppoEvalHo = Rows-All-Ho $curPpo.rows

$independent = ($bc2Leak -eq 0) -and ($ppoLeak -eq 0) -and $sameSet -and $bc2EvalHo -and $ppoEvalHo

# --- SHA-256 of the weights actually evaluated -------------------------------------
# In REUSE mode hash the exact file the finished eval referenced (provenance.model_path),
# otherwise we would fingerprint different weights. In RECOMPUTE mode it is our model_best.
function Effective-Ckpt($eval, $resolved) {
    if ($eval -and $eval.model_path -and (Test-Path $eval.model_path)) { return $eval.model_path }
    return $resolved
}
$bc2Eff = Effective-Ckpt $curBc2 $bc2.path
$ppoEff = Effective-Ckpt $curPpo $ppo.path
$bc2Sha = Sha256 $bc2Eff
$ppoSha = Sha256 $ppoEff
$bc2ShaMatches = ($bc2Sha -eq $curBc2.model_sha)
$ppoShaMatches = ($ppoSha -eq $curPpo.model_sha)

$scenarios = $curBc2.rows | ForEach-Object { $_.name } | Sort-Object

# --- human-readable table + machine-readable manifest ------------------------------
$mode = if ($reuse) { "reuse" } else { "recompute" }
$table = @(
    "=== Independent comparison (ho_*), mode: $mode ===",
    "Same scenario set (testset_sha equal): $sameSet",
    "Fully independent (ho_* out of train/val/holdout/selection of BOTH models AND same scenes): $independent",
    "",
    "model       checkpoint           sha256(ckpt)  fights survival clear rounds mean_value",
    "bc2         $((Split-Path $bc2Eff -Leaf))  $bc2Sha  $($curBc2.n)  $($curBc2.survival)  $($curBc2.clear)  $($curBc2.mean_rounds)  $($curBc2.mean_value)",
    "ppo($PpoName) $((Split-Path $ppoEff -Leaf))  $ppoSha  $($curPpo.n)  $($curPpo.survival)  $($curPpo.clear)  $($curPpo.mean_rounds)  $($curPpo.mean_value)"
)
$table += ""
$table += "bc2 per-fight outcome on ho_*:"
foreach ($r in ($curBc2.rows | Sort-Object name)) {
    $table += ("  {0,-22} rounds {1} survived {2} cleared {3} value {4}" -f $r.name, $r.rounds,
               [int]$r.survived, [int]$r.cleared, $r.value)
}
$table += "ppo per-fight outcome on ho_*:"
foreach ($r in ($curPpo.rows | Sort-Object name)) {
    $table += ("  {0,-22} rounds {1} survived {2} cleared {3} value {4}" -f $r.name, $r.rounds,
               [int]$r.survived, [int]$r.cleared, $r.value)
}
$tableText = $table -join "`r`n"
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "indep_report.txt"), $tableText,
                               [System.Text.UTF8Encoding]::new($false))

$manifest = [ordered]@{
    kind             = "independent_eval_comparison"
    mode             = $mode
    rounds_cap       = $Rounds
    eval_kind        = $Kind
    same_testset     = $sameSet
    fully_independent = $independent
    bc2 = [ordered]@{
        run = $Bc2Name; checkpoint = $bc2Eff; checkpoint_which = $bc2.which
        checkpoint_sha256 = $bc2Sha; eval_recorded_model_sha256 = $curBc2.model_sha
        checkpoint_sha_matches_eval = $bc2ShaMatches
        eval_set_tag = $curBc2.set_tag; testset_sha256 = $curBc2.testset_sha
        fights = $curBc2.n; survival = $curBc2.survival; clear = $curBc2.clear
        mean_value = $curBc2.mean_value; mean_rounds = $curBc2.mean_rounds
        ho_leak_in_training_groups = $bc2Leak; eval_scenes_all_ho = $bc2EvalHo
        split = $(if ($bc2Man -and $bc2Man.split) { @{ train_groups = $bc2Man.split.train_groups;
                val_groups = $bc2Man.split.val_groups; groups_total = $bc2Man.split.groups_total } } else { $null })
        seed = $(if ($bc2Man -and $bc2Man.generation) { $bc2Man.generation.seed } else { $null })
    }
    ppo = [ordered]@{
        run = $PpoName; checkpoint = $ppoEff; checkpoint_which = $ppo.which
        checkpoint_sha256 = $ppoSha; eval_recorded_model_sha256 = $curPpo.model_sha
        checkpoint_sha_matches_eval = $ppoShaMatches
        eval_set_tag = $curPpo.set_tag; testset_sha256 = $curPpo.testset_sha
        fights = $curPpo.n; survival = $curPpo.survival; clear = $curPpo.clear
        mean_value = $curPpo.mean_value; mean_rounds = $curPpo.mean_rounds
        ho_leak_in_training_groups = $ppoLeak; eval_scenes_all_ho = $ppoEvalHo
        split = $(if ($ppoMan -and $ppoMan.split) { $ppoMan.split } else { $null })
        rl_seed = $(if ($ppoMan -and $ppoMan.rl) { $ppoMan.rl.seed } else { $null })
    }
    independent_scenarios = @($scenarios)
    note = "Claiming PPO beats bc2 is valid ONLY when fully_independent=true and n is comparable; otherwise NOT VERIFIED. A higher one-step accuracy or mean internal reward is NOT by itself proof of a better policy."
}
$manifestJson = $manifest | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "indep_manifest.json"), $manifestJson,
                               [System.Text.UTF8Encoding]::new($false))

# --- pack the FULL reports (not just the summary) ----------------------------------
$outDir = Join-Path $PSScriptRoot "indep-back"
if (Test-Path $outDir) { Remove-Item $outDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Copy-Item $curBc2.path (Join-Path $outDir "eval_bc2_ho.json")
Copy-Item $curPpo.path (Join-Path $outDir "eval_ppo_ho.json")
Copy-Item (Join-Path $PSScriptRoot "indep_manifest.json") (Join-Path $outDir "indep_manifest.json")
Copy-Item (Join-Path $PSScriptRoot "indep_report.txt")   (Join-Path $outDir "indep_report.txt")
foreach ($pair in @(
    @((Join-Path $bc2.dir "run_manifest.json"), "bc2_run_manifest.json"),
    @((Join-Path $bc2.dir "summary.json"),      "bc2_summary.json"),
    @((Join-Path $ppo.dir "run_manifest.json"), "ppo_run_manifest.json"),
    @((Join-Path $ppo.dir "summary.json"),      "ppo_summary.json"),
    @((Join-Path $ppo.dir "history.json"),      "ppo_history.json")
)) {
    if (Test-Path $pair[0]) { Copy-Item $pair[0] (Join-Path $outDir $pair[1]) }
}
# the PPO training log, if it exists (ppo_pilot may have been trained by this or earlier code)
foreach ($cand in @("rl_run.log", "rl.log", "train.log")) {
    $p = Join-Path $ppo.dir $cand
    if (Test-Path $p) { Copy-Item $p (Join-Path $outDir ("ppo_" + $cand)); break }
}
foreach ($l in @("indep_bc2_ho.log", "indep_ppo_ho.log")) {
    $p = Join-Path $PSScriptRoot $l
    if (Test-Path $p) { Copy-Item $p (Join-Path $outDir $l) }
}

if (-not $OutZip) { $OutZip = Join-Path $PSScriptRoot "indep-back.zip" }
if (Test-Path $OutZip) { Remove-Item $OutZip -Force }
Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $OutZip -CompressionLevel Optimal

# --- verify the archive really carries the full reports ----------------------------
& (Join-Path $PSScriptRoot "verify_zip.ps1") $OutZip `
    -Need @("indep_manifest.json", "eval_bc2_ho.json", "eval_ppo_ho.json", "indep_report.txt")
$vrc = $LASTEXITCODE

Write-Output ""
Write-Output $tableText
Write-Output ""
Write-Output ("zip: $OutZip  (verify exit=$vrc)")
Write-Output ("fully_independent=$independent  same_testset=$sameSet  mode=$mode")
exit $vrc
