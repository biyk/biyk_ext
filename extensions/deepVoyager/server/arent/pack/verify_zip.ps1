# arent/pack/verify_zip.ps1 - prove a results-back.zip really carries every artifact.
#
# AUTO.bat calls this after packing so a "DONE" can never be printed over an empty or
# half-written archive (the bug that shipped a 461-byte zip holding only bench.json).
# Exits 0 when all required files are present and non-empty, 1 otherwise. ASCII only.
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [string[]]$Need = @()                  # empty -> the default BC list below
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

# what a real run must contain, by file name (they sit flat at the zip root)
if (-not $Need) {
    $Need = @("model.json", "model_best.json", "summary.json", "history.json",
              "run_manifest.json",
              "train.log", "bench.json", "info.txt")
}

if (-not (Test-Path $Zip)) {
    Write-Output "verify_zip: no such archive: $Zip"
    exit 1
}

$archive = [System.IO.Compression.ZipFile]::OpenRead($Zip)
try {
    $names = @{}
    foreach ($entry in $archive.Entries) {
        $leaf = Split-Path $entry.FullName -Leaf
        if ($leaf) { $names[$leaf] = $entry.Length }
    }
    $bad = @()
    foreach ($file in $Need) {
        if (-not $names.ContainsKey($file)) { $bad += "$file (missing)" }
        elseif ($names[$file] -lt 1) { $bad += "$file (empty)" }
    }
    if ($bad) {
        Write-Output ("verify_zip: INCOMPLETE - " + ($bad -join ", "))
        exit 1
    }
    Write-Output ("verify_zip: OK - all {0} artifacts present and non-empty" -f $Need.Count)
    exit 0
}
finally {
    $archive.Dispose()
}
