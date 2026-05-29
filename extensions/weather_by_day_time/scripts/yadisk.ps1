param(
    [string]$Path = "/Музыка",
    [string]$Token = "y0__xCV9rpLGNuWAyCJ04f2FjDB8MjjB62QfdbSdK5iVOsR7FsLivUZYqP_",
    [string]$Url,
    [string]$OutDir,
    [switch]$Download,
    [int]$Limit = 10
)

# Режим 1: публичная папка (если передан Url)
if ($Url) {
    $api = "https://cloud-api.yandex.net/v1/disk/public/resources"
    $publicKey = if ($Url -match '(https?://disk\.yandex\.[^/]+/d/[^/]+)') { $matches[1] } else { $Url }
    $folderPath = "/"
    if ($Url -match "/d/[^/]+/(.+)") { $folderPath = "/" + [System.Uri]::UnescapeDataString($matches[1]) }

    $params = @{ public_key = $publicKey; path = $folderPath; limit = $Limit }
    $resp = Invoke-RestMethod -Uri $api -Body $params -Method Get
    $title = "Публичная папка"
} else {
    # Режим 2: личный диск по OAuth-токену
    $api = "https://cloud-api.yandex.net/v1/disk/resources"
    $headers = @{ Authorization = "OAuth $Token" }
    $params = @{ path = $Path; limit = $Limit }
    $resp = Invoke-RestMethod -Uri $api -Headers $headers -Body $params -Method Get
    $title = "Личный диск: $($resp.name)"
}

Write-Host "$title" -ForegroundColor Cyan
Write-Host "Всего: $($resp._embedded.total) элементов, показано $($resp._embedded.items.Count)" -ForegroundColor Cyan
Write-Host ""

$items = $resp._embedded.items
foreach ($item in $items) {
    $type = if ($item.type -eq "dir") { "[DIR]" } else { "[FILE]" }
    $size = if ($item.size) { "{0:N0} KB" -f ($item.size / 1KB) } else { "" }
    Write-Host "$type $($item.name) $size"
}

if ($Download -and $OutDir) {
    if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
    foreach ($item in $items) {
        if ($item.type -eq "file") {
            $outPath = Join-Path $OutDir $item.name
            Write-Host "Скачиваю: $($item.name)..." -NoNewline
            if ($Url) {
                Invoke-WebRequest -Uri $item.file -OutFile $outPath
            } else {
                $dl = Invoke-RestMethod -Uri "https://cloud-api.yandex.net/v1/disk/resources/download?path=$($item.path)" -Headers $headers -Method Get
                Invoke-WebRequest -Uri $dl.href -OutFile $outPath
            }
            Write-Host " OK" -ForegroundColor Green
        }
    }
}