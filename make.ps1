# Windows equivalent of the Makefile. Usage: .\make.ps1 <target>
param(
    [Parameter(Position = 0)][string]$Target = "help",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)

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
    "seed" {
        # Fresh demo database; add args after the target, e.g. .\make.ps1 seed --cluster live
        Invoke-Step "uv run python scripts/seed_demo.py --reset $($Rest -join ' ')"
    }
    "demo-check" {
        # Every demo beat (spec section 16) through the gateway, as the browser does.
        Invoke-Step "uv run --offline python scripts/demo_check.py $($Rest -join ' ')"
    }
    "offline-check" {
        # Run with Wi-Fi OFF: container isolation, then the full demo through the gateway.
        $env:MSYS_NO_PATHCONV = "1"
        Invoke-Step "docker compose exec -T backend python /app/scripts/check_isolation.py"
        Invoke-Step "uv run --offline python scripts/demo_check.py $($Rest -join ' ')"
    }
    default {
        Write-Host "Targets: setup, lint, format, test, seed, demo-check, offline-check"
    }
}
