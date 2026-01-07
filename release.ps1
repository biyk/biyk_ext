param(
    [string]$ModuleFile = "module.json",
    [string]$ZipName = "module.zip"
)

# Read module.json
$module = Get-Content $ModuleFile -Raw | ConvertFrom-Json

if (-not $module.version) { throw "module.json missing 'version'" }

# Parse version
$parts = $module.version -split "\."
if ($parts.Count -ne 3) { throw "Version must be X.Y.Z" }

$major = [int]$parts[0]
$minor = [int]$parts[1]
$patch = [int]$parts[2]

# Increment patch
$patch++
$newVersion = "$major.$minor.$patch"

# Update module.json version
$module.version = $newVersion

# Update download URL (assumes releases are named module.zip)
# Adjust USERNAME/REPO to your GitHub repo
$module.download = "https://github.com/USERNAME/REPO/releases/download/v$newVersion/module.zip"

# Save updated module.json
$module | ConvertTo-Json -Depth 10 | Out-File $ModuleFile -Encoding UTF8

# Remove old ZIP if exists
if (Test-Path $ZipName) { Remove-Item $ZipName }

# Create ZIP with module files (exclude .git and workflow files)
$exclude = @(".git","release.ps1",".github")
$files = Get-ChildItem -Recurse | Where-Object { $exclude -notcontains $_.Name }
Compress-Archive -Path $files.FullName -DestinationPath $ZipName -Force

# Git commit and tag
git add $ModuleFile
git add $ZipName
git commit -m "Release $newVersion"
$tag = "v$newVersion"
git tag $tag
git push
git push --tags

# GitHub release with ZIP
gh release create $tag $ZipName `
    --title "Release $newVersion" `
    --notes "Automated release $newVersion"
