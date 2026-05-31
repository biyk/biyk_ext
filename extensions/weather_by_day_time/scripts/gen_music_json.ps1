param(
    [string]$CacheDir = "$PSScriptRoot/../temp",
    [int]$CacheHours = 24
)

$api = "https://cloud-api.yandex.net/v1/disk/public/resources"
$publicKey = "https://disk.yandex.ru/d/S25ICf3RhneLzA"
$outFile = "$PSScriptRoot/../data/ydisk/music.json"

if (-not (Test-Path $CacheDir)) { New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null }

function New-CacheKey($params) {
    $raw = ($params.Keys | Sort-Object | % { "$_=$($params[$_])" }) -join "&"
    $bytes = [Text.Encoding]::UTF8.GetBytes($raw)
    $hash = -join ([Security.Cryptography.SHA256]::Create().ComputeHash($bytes) | % { $_.ToString("x2") })
    return Join-Path $CacheDir "$hash.json"
}

function Invoke-CachedApi($params) {
    $cacheFile = New-CacheKey $params
    if ((Test-Path $cacheFile) -and ((Get-Item $cacheFile).LastWriteTime -gt (Get-Date).AddHours(-$CacheHours))) {
        return Get-Content $cacheFile -Raw | ConvertFrom-Json
    }
    Write-Host "  [API] $($params.path)" -ForegroundColor DarkYellow
    $resp = Invoke-RestMethod -Uri $api -Body $params -Method Get -TimeoutSec 600
    $resp | ConvertTo-Json -Depth 5 | Out-File $cacheFile -Encoding utf8
    return $resp
}

function Get-AllItems($folderPath) {
    $all = @(); $offset = 0; $limit = 100
    do {
        $params = @{ public_key = $publicKey; path = $folderPath; limit = $limit; offset = $offset }
        $resp = Invoke-CachedApi $params
        $all += $resp._embedded.items
        $offset += $limit
    } while ($offset -lt $resp._embedded.total)
    return $all
}

function Build-Tree($folderPath) {
    $items = Get-AllItems $folderPath
    $tree = @()
    foreach ($item in $items) {
        $entry = @{ name = $item.name; type = $item.type; path = $item.path }
        if ($item.type -eq "file") {
            $entry.size = $item.size; $entry.file = $item.file
            $entry.media_type = $item.media_type; $entry.mime_type = $item.mime_type
        } else {
            $entry.children = Build-Tree $item.path
        }
        $tree += $entry
    }
    return $tree
}

Write-Host "=== Сбор музыки с Яндекс.Диска ===" -ForegroundColor Cyan
$tree = Build-Tree "/Музыка"
$json = $tree | ConvertTo-Json -Depth 10
$json | Out-File $outFile -Encoding utf8

$files = 0
function Count-Files($items) { foreach ($it in $items) { if ($it.type -eq "file") { $files++ } elseif ($it.children) { Count-Files $it.children } } }
Count-Files $tree

Write-Host "Готово:" -ForegroundColor Green
Write-Host "  Папок: $($tree.Count)" -ForegroundColor Green
Write-Host "  Файлов: $files" -ForegroundColor Green
Write-Host "  Сохранено: $outFile" -ForegroundColor Green
