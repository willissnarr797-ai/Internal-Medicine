[CmdletBinding()]
param(
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$python = 'C:\Users\morning\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $command = Get-Command python -ErrorAction Stop
    $python = $command.Source
}

$builder = Join-Path -Path $PSScriptRoot -ChildPath 'build_internal_medicine_book.py'
$mode = if ($VerifyOnly) { '--verify-only' } else { '--write' }
& $python $builder $mode
if ($LASTEXITCODE -ne 0) {
    throw "Chapter build failed with exit code $LASTEXITCODE"
}
