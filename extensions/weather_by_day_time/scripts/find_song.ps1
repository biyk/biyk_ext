param(
    [Parameter(Mandatory=$true)]
    [string]$Query,
    [int]$Top = 10
)

$musicJson = "$PSScriptRoot/../data/ydisk/music.json"
if (-not (Test-Path $musicJson)) { Write-Error "music.json not found. Run gen_music_json.ps1 first."; exit 1 }

Write-Host "=== Поиск: $Query ===" -ForegroundColor Cyan
Write-Host ""

$tree = Get-Content $musicJson -Raw | ConvertFrom-Json

# Собираем все файлы в плоский список
$allFiles = @()
function Flatten($items, $parentPath) {
    foreach ($it in $items) {
        $fullPath = if ($parentPath) { "$parentPath/$($it.name)" } else { $it.name }
        if ($it.type -eq "file") {
            $allFiles += [PSCustomObject]@{
                name = $it.name
                path = $fullPath
                size = $it.size
                url  = $it.file
                mime = $it.mime_type
            }
        }
        if ($it.children) { Flatten $it.children $fullPath }
    }
}
Flatten $tree ""

# Оценка релевантности
$queryLower = $Query.ToLower()
$results = foreach ($f in $allFiles) {
    $nameLower = $f.name.ToLower()
    $pathLower = $f.path.ToLower()
    $score = 0

    # Полное совпадение имени
    if ($nameLower -eq $queryLower) { $score = 100 }
    # Имя начинается с запроса
    elseif ($nameLower.StartsWith($queryLower)) { $score = 90 }
    # Запрос начинается с имени
    elseif ($queryLower.StartsWith($nameLower)) { $score = 80 }
    # Слово из запроса есть в имени
    else {
        $words = $queryLower -split '\s+'
        $matchCount = 0
        foreach ($w in $words) {
            if ($w.Length -gt 2 -and $nameLower -match [regex]::Escape($w)) { $matchCount++ }
        }
        $score = [math]::Round(($matchCount / [math]::Max($words.Count, 1)) * 70)
        # Бонус если строка из запроса есть в пути
        if ($pathLower -match [regex]::Escape($queryLower)) { $score += 10 }
    }

    [PSCustomObject]@{ name = $f.name; path = $f.path; score = $score; url = $f.url; size = $f.size }
}

$top = $results | Where-Object { $_.score -gt 0 } | Sort-Object score -Descending | Select-Object -First $Top

if ($top.Count -eq 0) {
    Write-Host "Ничего не найдено." -ForegroundColor Yellow
    exit
}

Write-Host "Найдено: $($top.Count) результатов" -ForegroundColor Green
Write-Host ""

$i = 1
foreach ($r in $top) {
    $sizeStr = if ($r.size) { "{0:N0} KB" -f ($r.size / 1KB) } else { "?" }
    Write-Host "[$i] $($r.name)" -ForegroundColor White
    Write-Host "    Путь: $($r.path)" -ForegroundColor Gray
    Write-Host "    Размер: $sizeStr  Совпадение: $($r.score)%" -ForegroundColor Gray
    Write-Host ""
    $i++
}
