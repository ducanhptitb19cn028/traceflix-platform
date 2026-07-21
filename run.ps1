<#
.SYNOPSIS
  Run the TraceFlix platform on the local Kubernetes cluster (docker-desktop)
  in the `on-demand-observability` namespace, then run the offline experiments.

  Pure PowerShell + native Windows tools (mvn, docker, kubectl, python). No make,
  no Git Bash, no WSL - this is the fragility that broke `make bootstrap`.

.DESCRIPTION
  Default (no args) does the whole thing, in order:
    1. Preflight   - check docker / kubectl / mvn / python and that a cluster is up
    2. Build       - mvn package the Java services
    3. Images      - docker build movie/actor/review -> traceflix/*-service:1.0.0
    4. Deploy      - kubectl apply the observability stack + services + load-gen
                     + VictoriaMetrics into the cluster
    5. Wait        - block until the on-demand-observability pods are Ready
    6. Experiments - pip install + run RQ1/2/4, RQ3 drift, cost, and plots
  Skip any phase with the switches below. Grafana access is printed at the end.

.EXAMPLE
  .\run.ps1                      # full run: deploy platform + experiments
  .\run.ps1 -SkipExperiments     # just bring the k8s platform up
  .\run.ps1 -SkipDeploy          # just run the experiments (platform already up)
  .\run.ps1 -SkipBuild           # redeploy without rebuilding jars/images
  .\run.ps1 -Chaos               # also install Chaos Mesh (needs helm)
  .\run.ps1 -Teardown            # delete the namespaces and exit
  .\run.ps1 -Episodes 60 -DriftEpisodes 120   # faster experiment run
#>

[CmdletBinding()]
param(
  [switch]$SkipBuild,
  [switch]$SkipDeploy,
  [switch]$SkipExperiments,
  [switch]$SkipPip,
  [switch]$Chaos,
  [switch]$Teardown,
  [int]$Episodes       = 200,
  [int]$DriftEpisodes  = 320,
  [string]$Configs     = "C1,C2,C3,C4",
  [int]$Seed           = 42,
  [int]$WaitTimeoutSec = 300
)

# Native tools (kubectl/docker/mvn) routinely write progress and warnings to
# stderr. Under 'Stop', PowerShell 5.1 turns ANY native stderr into a terminating
# error - which spuriously killed this script during a Docker Desktop API blip.
# Use 'Continue' and gate on exit codes explicitly (Exec + $LASTEXITCODE checks).
$ErrorActionPreference = 'Continue'
$Root      = $PSScriptRoot
$Namespace = 'on-demand-observability'
# All 9 Java services. Each is deployed with imagePullPolicy:Never, so every one
# needs a locally-built traceflix/<name>-service:1.0.0 image.
#   movie/actor/review          -> observability/on-demand-observability.yaml
#   the other 6 (catalog..gateway) -> dissertation/scripts/mesh.yaml
$Services  = @('movie', 'actor', 'review',
               'catalog', 'auth', 'user', 'search', 'recommendation', 'gateway')

# --- helpers ---------------------------------------------------------------
function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Info($msg)     { Write-Host "    $msg" -ForegroundColor DarkGray }
function Ok($msg)       { Write-Host "    $msg" -ForegroundColor Green }
function Warn($msg)     { Write-Host "    WARN: $msg" -ForegroundColor Yellow }

# Run a native command and fail the script if it returns non-zero. PowerShell
# does NOT stop on a native non-zero exit by itself, so we check $LASTEXITCODE.
function Exec {
  param([Parameter(Mandatory)][string]$File, [string[]]$ArgList, [string]$In)
  if ($In) { Push-Location $In }
  try {
    & $File @ArgList
    if ($LASTEXITCODE -ne 0) {
      throw "'$File $($ArgList -join ' ')' failed with exit code $LASTEXITCODE"
    }
  } finally { if ($In) { Pop-Location } }
}

function Need($tool) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "'$tool' not found on PATH. Install it (or open a shell that has it) and retry."
  }
}

# --- teardown short-circuit ------------------------------------------------
if ($Teardown) {
  Step 'teardown' "Deleting namespaces"
  kubectl delete namespace $Namespace --ignore-not-found
  kubectl delete namespace devops-agent --ignore-not-found
  if (Get-Command helm -ErrorAction SilentlyContinue) {
    helm uninstall chaos-mesh -n chaos-mesh 2>$null | Out-Null
    kubectl delete namespace chaos-mesh --ignore-not-found
  }
  Ok "Torn down."
  return
}

# --- 1. preflight ----------------------------------------------------------
Step '1/6' "Preflight checks"
Need docker; Need kubectl; Need python
if (-not $SkipBuild) { Need mvn }

# JAVA_HOME sanity (the thing that started all this)
if (-not $SkipBuild) {
  if (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
    throw "JAVA_HOME is not set to a valid JDK (need `$env:JAVA_HOME\bin\java.exe). Current: '$env:JAVA_HOME'"
  }
  Info "JAVA_HOME = $env:JAVA_HOME"
}

# cluster must be reachable. Docker Desktop's API server flaps (briefly
# unreachable, then fine), so retry a few times before giving up.
$reachable = $false
foreach ($try in 1..6) {
  # Probe via cmd so kubectl's stderr during a blip can't bubble up as a PS error.
  cmd /c "kubectl cluster-info >NUL 2>NUL"
  if ($LASTEXITCODE -eq 0) { $reachable = $true; break }
  Info "cluster not reachable yet (attempt $try/6) - retrying in 5s..."
  Start-Sleep -Seconds 5
}
if (-not $reachable) {
  throw "kubectl cannot reach a cluster after 6 tries. Start Kubernetes (Docker Desktop -> Settings -> Kubernetes -> Enable), wait for it to go green, then retry."
}
$ctx = (kubectl config current-context).Trim()
Info "kube context = $ctx"
if ($ctx -ne 'docker-desktop') { Warn "context is '$ctx', not 'docker-desktop'. Continuing - Ctrl+C if that's wrong." }
Ok "Preflight passed."

# --- 2. build Java services ------------------------------------------------
if ($SkipBuild) {
  Step '2/6' "Build Java services  (skipped: -SkipBuild)"
} else {
  Step '2/6' "Build Java services  (mvn package)"
  Info "Building the full services/ reactor - first run downloads dependencies."
  Exec mvn @('-q', 'clean', 'package', '-DskipTests') (Join-Path $Root 'services')
  Ok "Jars built."
}

# --- 3. build Docker images ------------------------------------------------
if ($SkipBuild) {
  Step '3/6' "Build Docker images  (skipped: -SkipBuild)"
} else {
  Step '3/6' "Build Docker images  (imagePullPolicy: Never)"
  $localImages = @()
  foreach ($s in $Services) {
    $img = "traceflix/$s-service:1.0.0"
    $dir = Join-Path $Root "services\$s-service"
    Info "docker build -> $img"
    Exec docker @('build', '-t', $img, $dir)
    $localImages += $img
  }
  # Tiny sidecar image carrying the AIOps dashboard SPA (injected via initContainer
  # in aiops/k8s/aiops.yaml). Built from repo root so the dist/ is in context.
  Info "docker build -> traceflix/aiops-dist:1.0.0 (AIOps dashboard SPA)"
  Exec docker @('build', '-f', 'aiops\k8s\aiops-dist.Dockerfile', '-t', 'traceflix/aiops-dist:1.0.0', '.') $Root
  $localImages += 'traceflix/aiops-dist:1.0.0'
  Ok "Images built into the host Docker daemon."

  # Docker Desktop's Kubernetes here is a MULTI-NODE kind cluster: each node is a
  # kindest/node container with its OWN containerd image store, so images in the
  # host daemon are invisible to the kubelet (-> ErrImageNeverPull under
  # imagePullPolicy: Never). Load every image into every node's store. Pipe the
  # tar through cmd, NOT PowerShell - PowerShell's pipeline corrupts binary data.
  $nodeContainers = @(docker ps --format '{{.Names}}|{{.Image}}' |
    Where-Object { $_ -match 'kindest/node' } |
    ForEach-Object { ($_ -split '\|')[0] })
  if ($nodeContainers.Count -gt 0) {
    Info "kind nodes detected ($($nodeContainers -join ', ')) - loading images into each store"
    foreach ($n in $nodeContainers) {
      foreach ($img in $localImages) {
        cmd /c "docker save $img | docker exec -i $n ctr -n k8s.io images import -" | Out-Null
        if ($LASTEXITCODE -ne 0) { Warn "load $img -> $n returned exit $LASTEXITCODE" }
      }
    }
    Ok "Images loaded into $($nodeContainers.Count) node store(s)."
  } else {
    Info "No kind node containers found - assuming a single shared daemon (host = kubelet)."
  }
}

# --- 4. deploy -------------------------------------------------------------
if ($SkipDeploy) {
  Step '4/6' "Deploy to Kubernetes  (skipped: -SkipDeploy)"
} else {
  Step '4/6' "Deploy to Kubernetes  (namespace: $Namespace)"
  $manifests = @(
    'observability\on-demand-observability.yaml',   # ns + otel/tempo/loki/prom/grafana + ALL 9 services + load-gens
    'aiops\k8s\load-generator-fixed.yaml',           # updated load generator
    'aiops\k8s\victoriametrics.yaml',                # metrics store (devops-agent ns)
    'aiops\k8s\aiops.yaml',                           # AIOps engine + API (:8000), reads the 9 services' live telemetry
    'aiops\k8s\ollama.yaml'                           # qwen2.5:3b for the LLM detector, at http://ollama:11434 (OLLAMA_URL in aiops.yaml)
  )
  foreach ($m in $manifests) {
    $path = Join-Path $Root $m
    if (-not (Test-Path $path)) { Warn "manifest not found, skipping: $m"; continue }
    Info "kubectl apply -f $m"
    Exec kubectl @('apply', '-f', $path)
  }
  Ok "Manifests applied."

  if ($Chaos) {
    Step '4b'  "Install Chaos Mesh (fault engine)"
    if (Get-Command helm -ErrorAction SilentlyContinue) {
      try {
        helm repo add chaos-mesh https://charts.chaos-mesh.org 2>$null | Out-Null
        helm repo update 2>$null | Out-Null
        kubectl create ns chaos-mesh --dry-run=client -o yaml | kubectl apply -f -
        helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh `
          --set chaosDaemon.runtime=containerd `
          --set chaosDaemon.socketPath=/run/containerd/containerd.sock
        if ($LASTEXITCODE -eq 0) { Ok "Chaos Mesh installed." }
        else { Warn "Chaos Mesh install returned exit $LASTEXITCODE (non-fatal)." }
      } catch { Warn "Chaos Mesh install failed (non-fatal): $($_.Exception.Message)" }
    } else { Warn "helm not found - skipping Chaos Mesh. Install helm, or drop -Chaos." }
  }
}

# --- 5. wait for pods ------------------------------------------------------
if ($SkipDeploy) {
  Step '5/6' "Wait for pods  (skipped: -SkipDeploy)"
} else {
  Step '5/6' "Wait for pods to become Ready  (up to ${WaitTimeoutSec}s)"
  Info "Java pods pull the OTel agent from GitHub on first boot - give it a minute."
  $deploys = kubectl get deploy -n $Namespace -o name 2>$null
  if ($deploys) {
    kubectl wait --for=condition=Available --timeout="${WaitTimeoutSec}s" -n $Namespace deploy --all
    if ($LASTEXITCODE -eq 0) {
      Ok "All deployments Available."
    } else {
      Warn "Not everything came up within ${WaitTimeoutSec}s. Current state:"
      kubectl get pods -n $Namespace -o wide
      Warn "If a traceflix/* pod shows ErrImageNeverPull, the kubelet can't see the local image."
      Warn "Rebuild the images (.\run.ps1 -SkipExperiments) or check Docker Desktop's image store setting."
    }
  } else { Warn "No deployments found in $Namespace." }
  kubectl get pods -n $Namespace -o wide
}

# --- 6. experiments --------------------------------------------------------
if ($SkipExperiments) {
  Step '6/6' "Experiments  (skipped: -SkipExperiments)"
} else {
  Step '6/6' "Run offline experiments  (RQ1/2/4, RQ3 drift, cost, plots)"
  $aiops = Join-Path $Root 'aiops'
  if (-not $SkipPip) {
    Info "pip install -r aiops/requirements.txt"
    try { Exec python @('-m', 'pip', 'install', '-q', '-r', (Join-Path $aiops 'requirements.txt')) }
    catch { Warn "pip install had problems (Python $((python --version 2>&1))). Continuing; add -SkipPip to skip. $($_.Exception.Message)" }
  }
  Info "RQ1/2/4  run_experiment  (episodes=$Episodes seed=$Seed)"
  Exec python @('-m', 'ml.experiments.run_experiment', '--episodes', "$Episodes", '--seed', "$Seed", '--out', 'data/results') $aiops
  Info "RQ3      online_vs_offline  (episodes=$DriftEpisodes configs=$Configs)"
  Exec python @('-m', 'ml.experiments.online_vs_offline', '--episodes', "$DriftEpisodes", '--configs', $Configs, '--out', 'data/results') $aiops
  Info "cost     cost_compare"
  Exec python @('-m', 'ml.experiments.cost_compare', '--episodes', "$DriftEpisodes", '--configs', $Configs, '--out', 'data/results') $aiops
  Info "plots    ml.eval.plots"
  Exec python @('-m', 'ml.eval.plots', 'data/results') $aiops
  Ok "Experiments done -> aiops/data/results/ (figures in data/results/figures/)."
}

# --- summary ---------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " Done." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
if (-not $SkipDeploy) {
  Write-Host @"

  Watch pods:        kubectl get pods -n $Namespace -w
  Grafana (admin/admin):
      kubectl port-forward -n $Namespace svc/grafana 3000:3000
      then open  http://localhost:3000
  Prometheus:        kubectl port-forward -n $Namespace svc/prometheus 9090:9090
  Tempo (traces):    kubectl port-forward -n $Namespace svc/tempo 3200:3200
  Tear it all down:  .\run.ps1 -Teardown
"@ -ForegroundColor Gray
}
if (-not $SkipExperiments) {
  Write-Host "  Results:           aiops\data\results\" -ForegroundColor Gray
}
