# Windows equivalent of the Makefile. Usage: .\make.ps1 <target>
param([Parameter(Position = 0)][string]$Target = "help")

$ErrorActionPreference = "Stop"

function Invoke-Step([string]$Cmd) {
    Write-Host "> $Cmd" -ForegroundColor Cyan
    Invoke-Expression $Cmd
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Target) {
    "setup" {
        Invoke-Step "uv sync --group dev"
        Invoke-Step "uv run pre-commit install --hook-type pre-commit --hook-type commit-msg"
    }
    "lint" {
        Invoke-Step "uv run ruff check ."
        Invoke-Step "uv run ruff format --check ."
    }
    "format" {
        Invoke-Step "uv run ruff check --fix ."
        Invoke-Step "uv run ruff format ."
    }
    "test" {
        Invoke-Step "uv run pytest -m 'not integration'"
    }
    default {
        Write-Host "Targets: setup, lint, format, test  (seed, dev, up, offline-check come later)"
    }
}
