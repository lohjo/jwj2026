<#
setup-gcp-secrets.ps1 — Configure Secret Manager + Cloud Run secret references for SENTINEL.

This script does NOT store secrets in the repo. Provide secret values via environment variables.

Usage (PowerShell):
    $env:GCP_PROJECT_ID = "your-project-id"   # optional; falls back to `gcloud config get-value project`
  $env:GCP_REGION     = "asia-southeast1"   # optional
  $env:CLOUD_RUN_SERVICE = "sentinel"       # optional

    $env:TELEGRAM_TOKEN = "PASTE_TELEGRAM_TOKEN"
    $env:GEMINI_API_KEY = "PASTE_GEMINI_API_KEY"
    $env:OPENAI_API_KEY = "PASTE_SEA_LION_KEY"

  .\setup-gcp-secrets.ps1

Notes:
- Requires `gcloud` to be installed and authenticated.
- Creates secrets if missing; otherwise adds a new version.
- Grants Secret Manager access to the Cloud Run runtime service account.
- Updates Cloud Run to reference secrets (latest).
#>

$ErrorActionPreference = "Stop"

function Get-GcloudValue([string[]]$gcloudArgs) {
    $out = & gcloud @gcloudArgs 2>$null
    if ($LASTEXITCODE -ne 0) { return "" }
    return ($out | Out-String).Trim()
}

function Write-TempFileNoNewline([string]$value) {
    $tmp = New-TemporaryFile
    # Windows PowerShell's -Encoding utf8 writes a BOM; secret values must not include it.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tmp, $value, $utf8NoBom)
    return $tmp
}

function Enable-SecretManagerApiIfNeeded([string]$projectId) {
    # Non-interactive enable (idempotent). Avoids the gcloud prompt:
    # "API [secretmanager.googleapis.com] not enabled... Would you like to enable and retry?"
    & gcloud services enable secretmanager.googleapis.com --project $projectId --quiet | Out-Null
}

function Import-DotEnvIfPresent() {
    $envPath = Join-Path (Get-Location) ".env"
    if (-not (Test-Path $envPath)) {
        return
    }

    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line) { return }
        if ($line.StartsWith("#")) { return }

        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }

        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()

        # Strip surrounding single/double quotes if present.
        if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
            $val = $val.Substring(1, $val.Length - 2)
        }

        if ($key) {
            $existing = [Environment]::GetEnvironmentVariable($key)
            if ([string]::IsNullOrWhiteSpace($existing)) {
                Set-Item -Path ("env:" + $key) -Value $val
            }
        }
    }
}

function Assert-RequiredSecretsPresent() {
    $missing = @()
    foreach ($k in @("TELEGRAM_TOKEN", "GEMINI_API_KEY", "OPENAI_API_KEY")) {
        $v = [Environment]::GetEnvironmentVariable($k)
        if ([string]::IsNullOrWhiteSpace($v)) {
            $missing += $k
        }
    }
    if ($missing.Count -gt 0) {
        throw ("Missing required environment variables for secret values: " + ($missing -join ", ") + ". " +
               "Set them in PowerShell or add them to .env (not committed) and rerun.")
    }
}

function Set-SecretValue([string]$projectId, [string]$name, [string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required environment variable: $name"
    }

    $tmp = Write-TempFileNoNewline $value
    try {
        $prevErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & gcloud secrets describe $name --project $projectId --quiet *> $null
        }
        finally {
            $describeExitCode = $LASTEXITCODE
            $ErrorActionPreference = $prevErrorActionPreference
        }

        if ($describeExitCode -eq 0) {
            & gcloud secrets versions add $name --data-file=$tmp --project $projectId | Out-Null
        } else {
            & gcloud secrets create $name --data-file=$tmp --replication-policy=automatic --project $projectId | Out-Null
        }
    }
    finally {
        Remove-Item -Force $tmp
    }
}

function Grant-SecretAccessor([string]$projectId, [string]$secretName, [string]$serviceAccount) {
    & gcloud secrets add-iam-policy-binding $secretName `
        --member "serviceAccount:$serviceAccount" `
        --role "roles/secretmanager.secretAccessor" `
        --project $projectId | Out-Null
}

function Get-CloudRunRuntimeServiceAccount([string]$projectId, [string]$region, [string]$service) {
    $sa = Get-GcloudValue @(
        "run", "services", "describe", $service,
        "--region", $region,
        "--project", $projectId,
        "--format=value(spec.template.spec.serviceAccountName)"
    )
    if (-not $sa) {
        return "$projectId-compute@developer.gserviceaccount.com"
    }
    return $sa
}

function Test-ServiceEnvForInlineComments([string]$projectId, [string]$region, [string]$service) {
    $envDump = Get-GcloudValue @(
        "run", "services", "describe", $service,
        "--region", $region,
        "--project", $projectId,
        "--format=get(spec.template.spec.containers[0].env)"
    )
    if (-not $envDump) { return }

    # Don’t print values; just warn if we see common comment markers.
    if ($envDump -match "\s#\s" -or $envDump -match "\s;\s") {
        Write-Warning "Cloud Run service env appears to include inline comments (e.g. 'VALUE # note'). Secrets will overwrite those vars when configured below."
    }
}

$projectId = $env:GCP_PROJECT_ID
if (-not $projectId) {
    $projectId = Get-GcloudValue @("config", "get-value", "project")
}
if (-not $projectId) {
    throw "No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID (or set $env:GCP_PROJECT_ID)."
}

Enable-SecretManagerApiIfNeeded -projectId $projectId

Import-DotEnvIfPresent
Assert-RequiredSecretsPresent

$region = $env:GCP_REGION
if (-not $region) { $region = "asia-southeast1" }

$service = $env:CLOUD_RUN_SERVICE
if (-not $service) { $service = "sentinel" }

Test-ServiceEnvForInlineComments -projectId $projectId -region $region -service $service

$runtimeSa = Get-CloudRunRuntimeServiceAccount -projectId $projectId -region $region -service $service
Write-Host "Project:  $projectId"
Write-Host "Region:   $region"
Write-Host "Service:  $service"
Write-Host "Runtime SA: $runtimeSa"

# Create/update secrets
Set-SecretValue -projectId $projectId -name "TELEGRAM_TOKEN" -value $env:TELEGRAM_TOKEN
Set-SecretValue -projectId $projectId -name "GEMINI_API_KEY" -value $env:GEMINI_API_KEY
Set-SecretValue -projectId $projectId -name "OPENAI_API_KEY" -value $env:OPENAI_API_KEY

# Grant access
Grant-SecretAccessor -projectId $projectId -secretName "TELEGRAM_TOKEN" -serviceAccount $runtimeSa
Grant-SecretAccessor -projectId $projectId -secretName "GEMINI_API_KEY" -serviceAccount $runtimeSa
Grant-SecretAccessor -projectId $projectId -secretName "OPENAI_API_KEY" -serviceAccount $runtimeSa

# Update Cloud Run to use Secret Manager references

$prevErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    # If these keys are already set as plaintext env vars, Cloud Run will refuse to change their type.
    & gcloud run services update $service `
        --region $region `
        --project $projectId `
        --remove-env-vars "TELEGRAM_TOKEN,GEMINI_API_KEY,OPENAI_API_KEY" `
        --quiet | Out-Null
}
finally {
    $ErrorActionPreference = $prevErrorActionPreference
}

& gcloud run services update $service `
    --region $region `
    --project $projectId `
    --update-secrets "TELEGRAM_TOKEN=TELEGRAM_TOKEN:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest" `
    --quiet | Out-Null

Write-Host "Done. Verify with:"
Write-Host "  gcloud run services describe $service --region $region --project $projectId --format=get(spec.template.spec.containers[0].env)"
