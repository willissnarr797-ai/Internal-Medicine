[CmdletBinding()]
param(
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workspace = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $workspace '999_附件文件夹'
$outputDir = Join-Path $sourceDir '02_内科学第10版_按章节'
$targetDir = Join-Path $sourceDir 'images'
$manifestPath = Join-Path $outputDir '00_图片恢复清单.json'

$baselines = [ordered]@{
    '1_内科学.md' = [ordered]@{ lines = 5601; bytes = 661370; sha256 = '437ffb956e5e6b15b5c3eb26b00f7f71eba99625fb5443d8c208d1824e14d409' }
    '2_内科学.md' = [ordered]@{ lines = 4954; bytes = 777787; sha256 = '0460f9989fe1a6387a68282e4a0966819e0d31a2eddecaa398ee69576ce34851' }
    '3_内科学.md' = [ordered]@{ lines = 5502; bytes = 741717; sha256 = '5a8cafa5b9174bf477ef303be4cda114d86fa2befcbb926e12866f4a5820fbd1' }
    '4_内科学.md' = [ordered]@{ lines = 5275; bytes = 732736; sha256 = 'effbed98d87e4dc87706cc3b8cc1ff64e01a12e5372fdeb42fa18d86c33f0ac9' }
    '5_内科学.md' = [ordered]@{ lines = 4901; bytes = 701193; sha256 = '5682ccaf9b8a66ca6d7f157a9218985f904110df7a090d52c04e64c124041f49' }
}

$mineruRoot = 'D:\morning\文档\mineru'
$imageRoots = [ordered]@{
    '1_内科学.md' = Join-Path $mineruRoot '内科学 第10版(1)带书签.pdf-7fa9f3d2-f827-43a1-be91-9175b055e63f\images'
    '2_内科学.md' = Join-Path $mineruRoot '内科学 第10版(1)带书签.pdf-23d5241e-0f6d-4a7a-998a-6b658aebd5e4\images'
    '3_内科学.md' = Join-Path $mineruRoot '内科学 第10版(1)带书签.pdf-2069d952-6026-4c56-9b8a-36a25057e94f\images'
    '4_内科学.md' = Join-Path $mineruRoot '内科学 第10版(1)带书签.pdf-a0f0e1cf-f675-48ea-85d4-fb7856179ef2\images'
    '5_内科学.md' = Join-Path $mineruRoot '内科学 第10版(1)带书签.pdf-b0001e39-b529-44eb-accd-1d4515cb0e22\images'
}
$sourceOrder = @('5_内科学.md', '4_内科学.md', '3_内科学.md', '2_内科学.md', '1_内科学.md')
$imageRegex = [regex]'!\[[^\]]*\]\((?:<)?images/([a-fA-F0-9]{64}\.jpg)(?:>)?\)'

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-SourceBaselines {
    foreach ($name in $baselines.Keys) {
        $path = Join-Path $sourceDir $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Missing source Markdown: $path"
        }
        $expected = $baselines[$name]
        $item = Get-Item -LiteralPath $path
        $lineCount = (Get-Content -LiteralPath $path -Encoding UTF8).Count
        $hash = Get-Sha256 $path
        if ($lineCount -ne $expected.lines -or $item.Length -ne $expected.bytes -or $hash -ne $expected.sha256) {
            throw "Source baseline changed: $name lines=$lineCount bytes=$($item.Length) sha256=$hash"
        }
    }
}

function Test-ImageDecode([string]$Path) {
    try {
        Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
        $image = [System.Drawing.Image]::FromFile($Path)
        try {
            $null = $image.Width
            $null = $image.Height
        }
        finally {
            $image.Dispose()
        }
        return $true
    }
    catch {
        return $false
    }
}

Assert-SourceBaselines

$byName = [ordered]@{}
$referenceCount = 0
foreach ($sourceName in $sourceOrder) {
    $markdownPath = Join-Path $sourceDir $sourceName
    $imageRoot = $imageRoots[$sourceName]
    if (-not (Test-Path -LiteralPath $imageRoot -PathType Container)) {
        throw "Missing designated MinerU image root: $imageRoot"
    }
    $text = [IO.File]::ReadAllText($markdownPath, [Text.Encoding]::UTF8)
    foreach ($match in $imageRegex.Matches($text)) {
        $referenceCount++
        $filename = $match.Groups[1].Value.ToLowerInvariant()
        $sourceImage = Join-Path $imageRoot $filename
        if (-not (Test-Path -LiteralPath $sourceImage -PathType Leaf)) {
            throw "Referenced image is absent from its exact MinerU package: $sourceName -> $filename"
        }
        $sourceHash = Get-Sha256 $sourceImage
        if ($byName.Contains($filename)) {
            if ($byName[$filename].sha256 -ne $sourceHash) {
                throw "Conflicting source images share filename $filename"
            }
            $byName[$filename].source_markdowns += $sourceName
            continue
        }
        $item = Get-Item -LiteralPath $sourceImage
        $byName[$filename] = [ordered]@{
            filename = $filename
            source_path = $sourceImage
            target_path = Join-Path $targetDir $filename
            bytes = $item.Length
            sha256 = $sourceHash
            source_markdowns = @($sourceName)
        }
    }
}

if ($referenceCount -ne 361 -or $byName.Count -ne 361) {
    throw "Image inventory mismatch: references=$referenceCount unique=$($byName.Count), expected 361/361"
}

$decodeFailures = 0
foreach ($entry in $byName.Values) {
    if (-not (Test-ImageDecode $entry.source_path)) {
        $decodeFailures++
        throw "Source image cannot be decoded: $($entry.source_path)"
    }
    if (Test-Path -LiteralPath $entry.target_path -PathType Leaf) {
        $targetHash = Get-Sha256 $entry.target_path
        if ($targetHash -ne $entry.sha256) {
            throw "Target image conflict; refusing overwrite: $($entry.target_path)"
        }
    }
}

$manifestRows = @()
foreach ($entry in $byName.Values) {
    $manifestRows += [ordered]@{
        filename = $entry.filename
        source_path = $entry.source_path
        target_path = $entry.target_path
        bytes = $entry.bytes
        sha256 = $entry.sha256
        source_markdowns = @($entry.source_markdowns | Select-Object -Unique)
    }
}
$manifest = [ordered]@{
    schema_version = 'internal-medicine-10e-image-restore-v1'
    references = $referenceCount
    unique_images = $byName.Count
    missing_images = 0
    decode_failures = 0
    images = $manifestRows
}
$manifestText = ($manifest | ConvertTo-Json -Depth 8) + "`n"
$utf8NoBom = [Text.UTF8Encoding]::new($false)

function Assert-ManifestMatches([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Image restore manifest is missing: $Path"
    }
    try {
        $actual = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    }
    catch {
        throw "Image restore manifest is not valid JSON: $Path"
    }
    if ($actual.schema_version -ne 'internal-medicine-10e-image-restore-v1' -or
        [int]$actual.references -ne 361 -or [int]$actual.unique_images -ne 361 -or
        [int]$actual.missing_images -ne 0 -or [int]$actual.decode_failures -ne 0 -or
        @($actual.images).Count -ne 361) {
        throw 'Image restore manifest summary was modified'
    }
    $actualByName = @{}
    foreach ($row in @($actual.images)) {
        $actualByName[[string]$row.filename] = $row
    }
    foreach ($entry in $byName.Values) {
        if (-not $actualByName.ContainsKey($entry.filename)) {
            throw "Image restore manifest row is missing: $($entry.filename)"
        }
        $row = $actualByName[$entry.filename]
        $expectedSources = @($entry.source_markdowns | Select-Object -Unique | Sort-Object) -join '|'
        $actualSources = @($row.source_markdowns | ForEach-Object { [string]$_ } | Sort-Object) -join '|'
        if ([string]$row.source_path -ne $entry.source_path -or
            [string]$row.target_path -ne $entry.target_path -or
            [int64]$row.bytes -ne [int64]$entry.bytes -or
            [string]$row.sha256 -ne $entry.sha256 -or
            $actualSources -ne $expectedSources) {
            throw "Image restore manifest row was modified: $($entry.filename)"
        }
    }
}

if ($VerifyOnly) {
    Assert-ManifestMatches $manifestPath
    foreach ($entry in $byName.Values) {
        if (-not (Test-Path -LiteralPath $entry.target_path -PathType Leaf)) {
            throw "Restored image is missing: $($entry.target_path)"
        }
        if ((Get-Sha256 $entry.target_path) -ne $entry.sha256) {
            throw "Restored image hash mismatch: $($entry.target_path)"
        }
        if (-not (Test-ImageDecode $entry.target_path)) {
            throw "Restored image decode failure: $($entry.target_path)"
        }
    }
}
else {
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        Assert-ManifestMatches $manifestPath
    }
    $null = New-Item -ItemType Directory -Path $targetDir -Force
    $null = New-Item -ItemType Directory -Path $outputDir -Force
    foreach ($entry in $byName.Values) {
        if (-not (Test-Path -LiteralPath $entry.target_path -PathType Leaf)) {
            Copy-Item -LiteralPath $entry.source_path -Destination $entry.target_path
        }
    }
    [IO.File]::WriteAllText($manifestPath, $manifestText, $utf8NoBom)
}

$restored = 0
foreach ($entry in $byName.Values) {
    if ((Test-Path -LiteralPath $entry.target_path -PathType Leaf) -and (Get-Sha256 $entry.target_path) -eq $entry.sha256) {
        if (Test-ImageDecode $entry.target_path) {
            $restored++
        }
        else {
            $decodeFailures++
        }
    }
}
$missing = $byName.Count - $restored

$derivedReferences = 0
$derivedMissing = 0
if (Test-Path -LiteralPath $outputDir -PathType Container) {
    $derivedRegex = [regex]'!\[[^\]]*\]\((?:<)?([^)>]+\.jpg)(?:>)?\)'
    foreach ($markdown in Get-ChildItem -LiteralPath $outputDir -Recurse -File -Filter '*.md') {
        $text = [IO.File]::ReadAllText($markdown.FullName, [Text.Encoding]::UTF8)
        foreach ($match in $derivedRegex.Matches($text)) {
            $derivedReferences++
            $relative = $match.Groups[1].Value.Replace('/', [IO.Path]::DirectorySeparatorChar)
            $resolved = [IO.Path]::GetFullPath((Join-Path $markdown.DirectoryName $relative))
            if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
                $derivedMissing++
            }
        }
    }
}

Assert-SourceBaselines

if ($restored -ne 361 -or $missing -ne 0 -or $decodeFailures -ne 0 -or $derivedMissing -ne 0) {
    throw "Image verification failed: restored=$restored missing=$missing decode_failures=$decodeFailures derived_missing=$derivedMissing"
}

Write-Output 'IMAGE_VERIFY_OK'
Write-Output "references=$referenceCount"
Write-Output "unique_images=$($byName.Count)"
Write-Output 'missing_images=0'
Write-Output 'decode_failures=0'
Write-Output "derived_references=$derivedReferences"
Write-Output 'derived_missing_images=0'
if ($VerifyOnly) {
    Write-Output 'VERIFY_ONLY_OK'
}
