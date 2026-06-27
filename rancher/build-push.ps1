<#
.SYNOPSIS
  Build and push the TraceFlix images (nine services + the AIOps engine) for the
  Rancher GPU k8s deploy. Windows PowerShell friendly.

.EXAMPLE
  ./rancher/build-push.ps1 -Registry registry.example.com/traceflix
  ./rancher/build-push.ps1 -Registry myreg/traceflix -Tag 1.0.0 -SkipBuild
  ./rancher/build-push.ps1 -Registry myreg/traceflix -ServicesOnly

  If script execution is blocked:
    powershell -ExecutionPolicy Bypass -File rancher/build-push.ps1 -Registry myreg/traceflix
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Registry,
  [string]$Tag = "1.0.0",
  [string]$AiopsTag = "gpu",
  [switch]$SkipBuild,     # skip the mvn package step (reuse existing jars)
  [switch]$ServicesOnly,  # skip the aiops image
  [switch]$NoPush         # build only, do not docker push
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot      # rancher/ -> repo root
Push-Location $repoRoot
try {
  $services = @("movie","actor","review","gateway","user","search","recommendation","auth","catalog")

  if (-not $SkipBuild) {
    Write-Host "==> mvn package (nine services)" -ForegroundColor Cyan
    mvn -f services/pom.xml clean package -DskipTests
    if ($LASTEXITCODE -ne 0) { throw "mvn build failed" }
  }

  foreach ($s in $services) {
    $img = "$Registry/$s-service:$Tag"
    Write-Host "==> $img" -ForegroundColor Cyan
    docker build -t $img "services/$s-service"
    if ($LASTEXITCODE -ne 0) { throw "docker build failed: $s-service" }
    if (-not $NoPush) {
      docker push $img
      if ($LASTEXITCODE -ne 0) { throw "docker push failed: $img" }
    }
  }

  if (-not $ServicesOnly) {
    $ai = "$Registry/traceflix-aiops:$AiopsTag"
    Write-Host "==> $ai" -ForegroundColor Cyan
    docker build -f rancher/aiops.Dockerfile -t $ai .
    if ($LASTEXITCODE -ne 0) { throw "docker build failed: aiops" }
    if (-not $NoPush) {
      docker push $ai
      if ($LASTEXITCODE -ne 0) { throw "docker push failed: $ai" }
    }
  }

  Write-Host "Done. Use:  --set image.registry=$Registry" -ForegroundColor Green
}
finally {
  Pop-Location
}
