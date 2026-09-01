<#
.SYNOPSIS
  Native PowerShell stand-in for the Makefile targets.

.DESCRIPTION
  Smart App Control is enforcing on this machine and Chocolatey's make.exe is
  unsigned, so `make <target>` is blocked. Every target here runs the SAME
  command the Makefile recipe runs -- there is no make involved, so nothing is
  blocked. Keep this in step with the Makefile if you edit either.

  Variables are parameters: -Episodes, -DriftEpisodes, -Configs, -Seed, -Out,
  -Namespace, -Svc, -Fault, -Dur, and the three ports.

.EXAMPLE
  .\mk.ps1 help
  .\mk.ps1 webui-forward
  .\mk.ps1 status
  .\mk.ps1 experiments -Episodes 60 -DriftEpisodes 120
  .\mk.ps1 inject -Svc catalog-service -Fault cpu_saturation -Dur 120
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Target = 'help',

  # ---- Makefile variables, same defaults --------------------------------
  [int]$Episodes       = 200,
  [int]$DriftEpisodes  = 320,
  [int]$StreamEpisodes = 20,
  [int]$LiveEpisodes   = 30,
  [string]$Rq2Seeds    = '42,43,44,45,46',
  [string]$Rq3Seeds    = '42,43,44,45,46',
  [string]$Configs     = 'C1,C2,C3,C4',
  [string]$SweepConfigs = 'C1,C4',
  [int]$Seed           = 42,
  [string]$Out         = 'data/results',
  [string]$SweepOut    = 'data/results_drift_sweep',
  [string]$BaselinesOut = 'data/results_baselines_scaled',
  [string]$AblationOut = 'data/results_ablation',
  [string]$CostSeedsOut = 'data/results_cost_seeds',
  # live-replay: the recorded campaign and ITS directory. One directory per
  # campaign -- live_replay resumes from live_windows_cache.jsonl and returns
  # every window that cache holds, so a second campaign pointed at an existing
  # directory is scored against the union of both. results_live/ belongs to
  # labels_live.csv, the campaign the write-up reports.
  [string]$LiveLabels  = 'data/labels_live.csv',
  [string]$LiveOut     = 'data/results_live',
  [string]$Namespace   = 'on-demand-observability',
  [string]$Svc         = 'catalog-service',
  [string]$Fault       = 'cpu_saturation',
  [int]$Dur            = 120,
  [int]$OllamaPort     = 11434,
  [string]$OllamaModel = 'qwen2.5:3b',
  [int]$WebuiPort      = 8000,
  [int]$FrontendPort   = 5173,
  [int]$KafkaPort      = 9092,
  [double]$Timeout     = 15,
  [switch]$Force,
  [string[]]$RunArgs   = @()
)

$ErrorActionPreference = 'Continue'
$Root     = $PSScriptRoot
$Aiops    = Join-Path $Root 'aiops'
$Services = Join-Path $Root 'services'
$FrontendImg = 'traceflix/frontend:1.0.0'
$AiopsSrcImg = 'traceflix/aiops-src:1.0.0'

# Standalone Kafka, deliberately NOT the vm1-gpu compose overlay. That file also
# starts Ollama on :11434, which would shadow the in-cluster Qwen this project
# uses, and it pins bitnami/kafka:3.7 -- a delisted image that no longer pulls.
# apache/kafka:3.7.0 is what dissertation/FIGURES.md documents and what the
# existing tf-kafka container on this machine already runs.
$KafkaName   = 'tf-kafka'
$KafkaImage  = 'apache/kafka:3.7.0'
$KafkaVolume = 'tf-kafka-data'
$KafkaTopics = @('tf.telemetry.windows', 'tf.anomalies')

# Prefer the repo venv; fall back to whatever python is on PATH.
$PY = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $PY)) { $PY = 'python' }

function Info($m) { Write-Host "[mk] $m" -ForegroundColor DarkGray }
function Ok($m)   { Write-Host "[mk] $m" -ForegroundColor Green }
function Die($m)  { Write-Host "[mk] $m" -ForegroundColor Red; exit 1 }

# Run a native command from a directory, failing loudly on a non-zero exit.
function Run($workdir, [scriptblock]$block) {
  Push-Location $workdir
  try { & $block; if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { Die "exit $LASTEXITCODE" } }
  finally { Pop-Location }
}

# kafka-topics.sh lives at /opt/kafka/bin in the apache image (bitnami differs).
# MSYS_NO_PATHCONV is a Git Bash problem only; from PowerShell the path is safe.
function Kafka-Topics {
  param([string[]]$TopicArgs)
  docker exec $KafkaName /opt/kafka/bin/kafka-topics.sh --bootstrap-server "localhost:$KafkaPort" @TopicArgs
}

function Kafka-Exists {
  $n = docker ps -a --filter "name=^/$KafkaName$" --format '{{.Names}}' 2>$null
  return [bool]$n
}

function Kafka-Running {
  $n = docker ps --filter "name=^/$KafkaName$" --format '{{.Names}}' 2>$null
  return [bool]$n
}

# The broker accepts connections before it will answer a metadata request, so
# poll kafka-topics.sh rather than the port.
function Wait-Kafka {
  param([int]$TimeoutSec = 60)
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    docker exec $KafkaName /opt/kafka/bin/kafka-topics.sh --bootstrap-server "localhost:$KafkaPort" --list *> $null
    if ($LASTEXITCODE -eq 0) { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

# ---- ollama on the host port ------------------------------------------------
# Everything OUTSIDE the cluster -- `webui`, `llm`, `streaming` -- reads
# OLLAMA_URL, which aiops/ml/models/llm_detector.py defaults to
# http://localhost:11434. Qwen runs IN the cluster, so that port is bound by a
# port-forward or by nothing at all. In-cluster pods are unaffected: k8s/aiops.yaml
# points them at the Service DNS name http://ollama:11434.

# $null when nothing answers; the parsed /api/tags body when something does.
function Ollama-Tags {
  param([int]$TimeoutSec = 2)
  try { return Invoke-RestMethod -Uri "http://localhost:$OllamaPort/api/tags" -TimeoutSec $TimeoutSec -ErrorAction Stop }
  catch { return $null }
}

# Detached forwards started by this script, found by command line -- we do not
# track a PID file, and a forward from a previous shell should still be killable.
function Ollama-ForwardProcs {
  return @(Get-CimInstance Win32_Process -Filter "Name = 'kubectl.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'port-forward' -and $_.CommandLine -match 'svc/ollama' })
}

# Put the in-cluster Qwen on localhost:$OllamaPort and leave it there. Never
# throws: running the dashboard without the LLM is legitimate -- the detector
# says so in its banner and scores windows with the rule-of-thumb test instead.
# Warns in the two cases that banner cannot tell apart for you: nothing bound,
# and a daemon answering without the model, where every call errors and every
# window comes back "normal" -- a broken detector that reads as a healthy system.
function Start-OllamaForward {
  param([int]$TimeoutSec = 30)

  $tags = Ollama-Tags
  if ($tags) {
    Info "ollama already reachable on :$OllamaPort"
  } else {
    kubectl -n $Namespace get deploy/ollama *> $null
    if ($LASTEXITCODE -ne 0) {
      Info "deploy/ollama is not in $Namespace - run '.\mk.ps1 ollama-up' for the LLM detector"
      Info 'continuing without it (heuristic fallback)'
      # The failed probe would otherwise become the script's own exit code, and a
      # missing Ollama is not a failure of this target.
      $global:LASTEXITCODE = 0
      return $false
    }
    Info "port-forward svc/ollama -> localhost:$OllamaPort (background; '.\mk.ps1 ollama-forward-stop')"
    Start-Process -FilePath 'kubectl' -WindowStyle Hidden `
      -ArgumentList @('-n', $Namespace, 'port-forward', 'svc/ollama', "${OllamaPort}:11434")
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
      Start-Sleep -Seconds 1
      $tags = Ollama-Tags
      if ($tags) { break }
    }
  }

  if (-not $tags) {
    Write-Host "[mk] !! ollama unreachable on :$OllamaPort - the detector will use the heuristic fallback" -ForegroundColor Yellow
    return $false
  }
  $models = @($tags.models | ForEach-Object { $_.name })
  if ($models -notcontains $OllamaModel) {
    Write-Host "[mk] !! ollama answers but $OllamaModel is NOT pulled - every call errors and every" -ForegroundColor Yellow
    Write-Host "[mk] !! window reports normal. Watch the pull with '.\mk.ps1 ollama-logs'" -ForegroundColor Yellow
    return $false
  }
  Ok "ollama on :$OllamaPort serving $($models -join ', ')"
  return $true
}

# webui/backend/app.py loads aiops/.env via python-dotenv at startup, but the CLI
# entry points read os.environ directly and never see it -- so `streaming` would
# silently use the in-memory bus while the dashboard used the real broker, from the
# same configuration. Load it here so both agree. Existing env vars win, matching
# python-dotenv's default (override=False).
function Load-DotEnv {
  $envFile = Join-Path $Aiops '.env'
  if (-not (Test-Path $envFile)) { return }
  $loaded = @()
  foreach ($line in Get-Content $envFile) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    $eq = $trimmed.IndexOf('=')
    if ($eq -lt 1) { continue }
    $name  = $trimmed.Substring(0, $eq).Trim()
    $value = $trimmed.Substring($eq + 1).Trim().Trim('"', "'")
    if ([Environment]::GetEnvironmentVariable($name, 'Process')) { continue }
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    $loaded += $name
  }
  if ($loaded) { Info "aiops/.env -> $($loaded -join ', ')" }
}

# Docker Desktop's Kubernetes here is a multi-node kind cluster: each node is a
# kindest/node container with its OWN containerd store, so an image in the host
# daemon is invisible to the kubelet (-> ErrImageNeverPull under
# imagePullPolicy: Never). Load it into every node.
function Load-IntoKind {
  param([string]$Image)
  $nodes = @(docker ps --format '{{.Names}}|{{.Image}}' |
    Where-Object { $_ -match 'kindest/node' } |
    ForEach-Object { ($_ -split '\|')[0] })
  if ($nodes.Count -eq 0) {
    Info 'no kind nodes found - assuming host daemon == kubelet'
    return
  }
  foreach ($n in $nodes) {
    Info "  -> $n"
    # Pipe the tar through cmd, NOT PowerShell: PS corrupts binary pipelines.
    cmd /c "docker save $Image | docker exec -i $n ctr -n k8s.io images import -" | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "  !! load into $n failed" -ForegroundColor Yellow }
  }
}

# The inverse of Load-IntoKind: drop an image from every kind node's containerd
# store. `docker rmi` on the host does NOT touch these -- the kubelet reads the
# node store, so an image left there keeps satisfying imagePullPolicy: Never and
# a "cleaned" cluster still runs yesterday's build.
function Remove-FromKind {
  param([string[]]$Images)
  $nodes = @(docker ps --format '{{.Names}}|{{.Image}}' |
    Where-Object { $_ -match 'kindest/node' } |
    ForEach-Object { ($_ -split '\|')[0] })
  if ($nodes.Count -eq 0) {
    Info 'no kind nodes found - assuming host daemon == kubelet'
    return
  }
  foreach ($n in $nodes) {
    Info "  -> $n"
    foreach ($i in $Images) {
      docker exec $n ctr -n k8s.io images rm "docker.io/$i" *> $null
    }
  }
}

# Every image this project builds locally. None of them is in a registry, so
# these are the only copies: rebuilt with `images`, `frontend-image`,
# `aiops-image`.
function Local-Images {
  $svcs = @('movie','actor','review','catalog','auth','user','search','recommendation','gateway')
  return @($FrontendImg, $AiopsSrcImg, 'traceflix/aiops-dist:1.0.0') +
         @($svcs | ForEach-Object { "traceflix/$_-service:1.0.0" })
}

function Show-Help {
  Write-Host ""
  Write-Host "  mk.ps1 - Makefile stand-in (make.exe is blocked by Smart App Control)" -ForegroundColor White
  Write-Host ""
  Write-Host "  RUN (win)   run  run-platform  run-experiments  run-down" -ForegroundColor Gray
  Write-Host "  SETUP       setup  setup-llm" -ForegroundColor Gray
  Write-Host "  EXPERIMENTS experiments  quick  rq124  rq2  rq3  cost  plots" -ForegroundColor Gray
  Write-Host "  CONTROLS    controls  seeds  sweep  baselines  ablation  cost-seeds" -ForegroundColor Gray
  Write-Host "  WEBUI       webui  webui-build  webui-forward   (forward = the in-cluster one;" -ForegroundColor Gray
  Write-Host "                                                   webui auto-forwards ollama)" -ForegroundColor Gray
  Write-Host "  FRONTEND    frontend-image  frontend-up  frontend-down  frontend-forward" -ForegroundColor Gray
  Write-Host "  OLLAMA(k8s) ollama-up  ollama-down  ollama-logs" -ForegroundColor Gray
  Write-Host "              ollama-forward  ollama-forward-bg  ollama-forward-stop  (-bg = detached)" -ForegroundColor Gray
  Write-Host "  KAFKA       kafka-up  kafka-down  kafka-status  kafka-topics  kafka-logs  kafka-reset" -ForegroundColor Gray
  Write-Host "  AIOPS(k8s)  aiops-image  aiops-up  aiops-down  aiops-refresh" -ForegroundColor Gray
  Write-Host "  SERVICES    build-services  images  test  test-aiops  test-services" -ForegroundColor Gray
  Write-Host "  K8S         k8s-deploy  k8s-delete  status  chaos-install" -ForegroundColor Gray
  Write-Host "  K8S CLEAN   k8s-clean  k8s-clean-images  k8s-purge   (-Force for the images)" -ForegroundColor Gray
  Write-Host "  LIVE        live-episodes  live-replay  inject  streaming  ('live' is DEPRECATED)" -ForegroundColor Gray
  Write-Host ""
  Write-Host "  Demo shortcut:  dissertation\presentation\demo_video\start-demo.ps1" -ForegroundColor DarkCyan
  Write-Host ""
}

switch ($Target) {

  # ---- help ----------------------------------------------------------------
  'help' { Show-Help }

  # ---- run.ps1 wrappers ----------------------------------------------------
  'run'             { & (Join-Path $Root 'run.ps1') @RunArgs }
  'run-platform'    { & (Join-Path $Root 'run.ps1') -SkipExperiments @RunArgs }
  'run-experiments' { & (Join-Path $Root 'run.ps1') -SkipDeploy @RunArgs }
  'run-down'        { & (Join-Path $Root 'run.ps1') -Teardown }

  # ---- setup ---------------------------------------------------------------
  'setup'     { & $PY -m pip install -r (Join-Path $Aiops 'requirements.txt') }
  'setup-llm' { & $PY -m pip install -r (Join-Path $Aiops 'llm\requirements-llm.txt') }

  # ---- experiments ---------------------------------------------------------
  'rq124' { Run $Aiops { & $PY -m ml.experiments.run_experiment --episodes $Episodes --seed $Seed --out $Out } }
  'rq2'   { Run $Aiops { & $PY -m ml.experiments.rq2_localisation --episodes $Episodes --seeds $Rq2Seeds --out $Out } }
  'rq3'   { Run $Aiops { & $PY -m ml.experiments.online_vs_offline --episodes $DriftEpisodes --configs $Configs --out $Out } }
  'cost'  { Run $Aiops { & $PY -m ml.experiments.cost_compare --episodes $DriftEpisodes --configs $Configs --out $Out } }
  'plots' { Run $Aiops { & $PY -m ml.eval.plots $Out } }

  'experiments' {
    foreach ($t in @('rq124', 'rq2', 'rq3', 'cost', 'plots')) {
      Info "-> $t"
      & $PSCommandPath $t -Episodes $Episodes -DriftEpisodes $DriftEpisodes `
        -Configs $Configs -Seed $Seed -Out $Out -Rq2Seeds $Rq2Seeds
      if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { Die "$t failed" }
    }
    Ok "experiments complete -> aiops\$Out\"
  }

  'quick' {
    & $PSCommandPath experiments -Episodes 60 -DriftEpisodes 120
  }

  # ---- RQ3 controls (hours, not minutes) -----------------------------------
  'seeds'     { Run $Aiops { & $PY -u -m ml.experiments.baselines_and_seeds --seeds $Rq3Seeds --configs $Configs --out $Out } }
  'sweep'     { Run $Aiops { & $PY -u -m ml.experiments.drift_sweep --episodes $DriftEpisodes --seed $Seed --configs $SweepConfigs --out $SweepOut } }
  'baselines' { Run $Aiops { & $PY -u -m ml.experiments.baseline_streaming --episodes $DriftEpisodes --seed $Seed --configs $Configs --out $BaselinesOut } }
  'ablation'  { Run $Aiops { & $PY -u -m ml.experiments.ablate_online --episodes $DriftEpisodes --seed $Seed --configs $Configs --out $AblationOut } }
  'cost-seeds' { Run $Aiops { & $PY -u -m ml.experiments.cost_seeds --seeds $Rq3Seeds --configs $Configs --episodes $DriftEpisodes --out $Out --per-seed-out $CostSeedsOut } }
  'cost-seeds-agg' { Run $Aiops { & $PY -m ml.experiments.cost_seeds --seeds $Rq3Seeds --from-dir $CostSeedsOut --out $Out } }

  'controls' {
    foreach ($t in @('seeds', 'sweep', 'baselines', 'ablation')) {
      Info "-> $t"
      & $PSCommandPath $t -DriftEpisodes $DriftEpisodes -Configs $Configs -Seed $Seed -Out $Out -Rq3Seeds $Rq3Seeds
    }
    Ok 'RQ3 controls complete'
  }

  # ---- streaming -----------------------------------------------------------
  # -Timeout defaults to 15, NOT run_pipeline's own 2.0. Against a real broker a
  # KafkaConsumer must discover the group coordinator, join and be assigned
  # partitions before it reads anything, and that takes longer than 2 s -- the
  # iterator hits consumer_timeout_ms first and the run reports "0 verdicts"
  # while looking completely healthy. The in-memory bus ignores the timeout, so
  # this is safe either way. Measured on this machine: 2 s -> 0, 15 s -> all.
  'streaming' {
    Load-DotEnv
    if (-not $env:TF_KAFKA_BOOTSTRAP) {
      Info 'TF_KAFKA_BOOTSTRAP unset - the pipeline will use the in-memory bus'
    } elseif (-not (Kafka-Running)) {
      Info "TF_KAFKA_BOOTSTRAP=$env:TF_KAFKA_BOOTSTRAP but $KafkaName is not running - expect the in-memory fallback"
    }
    Run $Aiops { & $PY -m streaming.run_pipeline --episodes $StreamEpisodes --timeout $Timeout }
  }

  # ---- webui ---------------------------------------------------------------
  # The forward outlives the dashboard on purpose - restarting webui is common,
  # and Ctrl-C here kills the whole script, so a cleanup step would not run.
  'webui' {
    Start-OllamaForward | Out-Null
    Run $Aiops { & $PY -m uvicorn webui.backend.app:app --port $WebuiPort }
  }
  'webui-build' { Run (Join-Path $Aiops 'webui\frontend') { npm install; npm run build } }
  'webui-forward' {
    Info "aiops dashboard -> http://localhost:$WebuiPort  (Ctrl-C to stop)"
    kubectl -n $Namespace port-forward svc/aiops "${WebuiPort}:8000"
  }

  # ---- TraceFlix web client (k8s) -----------------------------------------
  'frontend-image' {
    Run $Root { docker build -t $FrontendImg (Join-Path $Services 'frontend') }
    Info "loading $FrontendImg into the kind node stores (imagePullPolicy: Never)"
    Load-IntoKind $FrontendImg
  }
  'frontend-up' {
    kubectl apply -f (Join-Path $Services 'frontend\k8s\frontend.yaml')
    kubectl -n $Namespace rollout status deploy/frontend --timeout=120s
  }
  'frontend-down' { kubectl delete -f (Join-Path $Services 'frontend\k8s\frontend.yaml') --ignore-not-found }
  'frontend-forward' {
    Info "traceflix web client -> http://localhost:$FrontendPort  (Ctrl-C to stop)"
    kubectl -n $Namespace port-forward svc/frontend "${FrontendPort}:5173"
  }

  # ---- AIOps / Ollama in k8s ----------------------------------------------
  # Build the source-injection sidecar and load it into the kind nodes. The pod's
  # initContainer copies it over /opt/traceflix/aiops, so the published :gpu image
  # runs TODAY's backend -- which is what puts /api/live/ml and /api/live/llm on
  # the in-cluster dashboard instead of 404.
  'aiops-image' {
    if (-not (Test-Path (Join-Path $Aiops 'webui\frontend\dist\index.html'))) {
      Die 'aiops/webui/frontend/dist is missing - run .\mk.ps1 webui-build first'
    }
    Run $Root { docker build -f (Join-Path $Aiops 'k8s\aiops-src.Dockerfile') -t $AiopsSrcImg . }
    Info "loading $AiopsSrcImg into the kind node stores"
    Load-IntoKind $AiopsSrcImg
    Ok "$AiopsSrcImg built and loaded"
  }

  # Rebuild the sidecar and restart the pod onto it. This is the target to run
  # after editing anything under aiops/.
  'aiops-refresh' {
    # aiops-image runs in a CHILD PowerShell process, so the Die inside it exits
    # that process, not this one. Without this check a failed build fell through
    # to the restart below and the pod came back on the previous image -- the
    # worst outcome available, because it prints "restarted on the current
    # source" over a pod running yesterday's code.
    & $PSCommandPath aiops-image
    if ($LASTEXITCODE -ne 0) {
      Die 'aiops-image failed - NOT restarting the pod (it would come back on the stale image)'
    }
    kubectl -n $Namespace rollout restart deploy/aiops
    kubectl -n $Namespace rollout status deploy/aiops --timeout=180s
    Ok 'aiops pod restarted on the current source'
  }

  'aiops-up'   { kubectl apply -f (Join-Path $Aiops 'k8s\aiops.yaml') }
  'aiops-down' { kubectl delete -f (Join-Path $Aiops 'k8s\aiops.yaml') --ignore-not-found }
  'ollama-up'  {
    kubectl apply -f (Join-Path $Aiops 'k8s\ollama.yaml')
    kubectl -n $Namespace rollout status deploy/ollama --timeout=300s
    Info "ollama up; the qwen2.5:3b pull (~2 GB) runs as job/ollama-pull -- watch with '.\mk.ps1 ollama-logs'"
  }
  'ollama-down' { kubectl delete -f (Join-Path $Aiops 'k8s\ollama.yaml') --ignore-not-found }
  'ollama-logs' { kubectl -n $Namespace logs job/ollama-pull -f }
  'ollama-forward-bg'   { Start-OllamaForward | Out-Null }
  'ollama-forward-stop' {
    # @() at the CALL site too: `return @(...)` unrolls a one-element array, and
    # a bare CimInstance has no .Count -- the message would print a blank.
    $procs = @(Ollama-ForwardProcs)
    if (-not $procs) { Info 'no background forward running'; break }
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Ok "stopped $($procs.Count) forward(s) on svc/ollama"
  }
  'ollama-forward' {
    Info "ollama -> http://localhost:$OllamaPort  (Ctrl-C to stop)"
    kubectl -n $Namespace port-forward svc/ollama "${OllamaPort}:11434"
  }

  # ---- Kafka (standalone, host Docker -- NOT the vm1-gpu compose overlay) ---
  # `kafka-llm-up` in the Makefile starts Kafka AND a second Ollama on :11434,
  # which collides with the forwarded in-cluster Qwen. These targets bring up the
  # broker only.
  'kafka-up' {
    if (-not (Kafka-Exists)) {
      Info "creating $KafkaName ($KafkaImage) on :$KafkaPort"
      docker volume create $KafkaVolume | Out-Null
      docker run -d --name $KafkaName `
        -p "${KafkaPort}:9092" `
        -v "${KafkaVolume}:/var/lib/kafka/data" `
        --restart unless-stopped `
        $KafkaImage | Out-Null
      if ($LASTEXITCODE -ne 0) { Die 'docker run failed' }
    } elseif (Kafka-Running) {
      Info "$KafkaName already running"
    } else {
      # Reuse rather than recreate: the stopped container keeps its topics.
      Info "starting existing $KafkaName (topics preserved)"
      docker start $KafkaName | Out-Null
      if ($LASTEXITCODE -ne 0) { Die 'docker start failed' }
    }

    Info 'waiting for the broker to answer metadata requests...'
    if (-not (Wait-Kafka)) { Die "broker did not come up - .\mk.ps1 kafka-logs" }
    Ok 'broker up'

    foreach ($t in $KafkaTopics) {
      Kafka-Topics @('--create', '--topic', $t, '--if-not-exists') | Out-Null
      Info "topic ready: $t"
    }
    Ok "Kafka on localhost:$KafkaPort  (aiops/.env already sets TF_KAFKA_BOOTSTRAP)"
    Info 'restart the dashboard so it picks the broker up: it reads .env at startup'
  }

  'kafka-down' {
    if (Kafka-Running) { docker stop $KafkaName | Out-Null; Ok "$KafkaName stopped (topics kept)" }
    else { Info "$KafkaName is not running" }
  }

  'kafka-status' {
    if (-not (Kafka-Exists)) { Info "$KafkaName does not exist - .\mk.ps1 kafka-up"; break }
    docker ps -a --filter "name=^/$KafkaName$" --format 'container: {{.Names}}  {{.Image}}  {{.Status}}'
    if (Kafka-Running) {
      Info 'topics:'
      Kafka-Topics @('--list')
    } else {
      Info 'not running - .\mk.ps1 kafka-up'
    }
  }

  'kafka-topics' {
    if (-not (Kafka-Running)) { Die "$KafkaName is not running - .\mk.ps1 kafka-up" }
    Kafka-Topics @('--list')
  }

  'kafka-logs' { docker logs -f $KafkaName }

  # Destructive: drops the container AND its topic data. Needs -Force.
  'kafka-reset' {
    if (-not $Force) { Die 'kafka-reset deletes the broker and all topic data. Re-run with -Force if that is what you want.' }
    docker rm -f $KafkaName 2>$null | Out-Null
    docker volume rm $KafkaVolume 2>$null | Out-Null
    Ok "$KafkaName and $KafkaVolume removed - .\mk.ps1 kafka-up to recreate"
  }

  # ---- Java services -------------------------------------------------------
  'build-services' { Run $Services { mvn -q clean package -DskipTests } }
  'images' {
    & $PSCommandPath build-services
    $all = @('movie','actor','review','catalog','auth','user','search','recommendation','gateway')
    foreach ($s in $all) {
      Run $Services { docker build -t "traceflix/$s-service:1.0.0" "$s-service" }
    }
  }

  # ---- tests ---------------------------------------------------------------
  'test-aiops'    { Run $Aiops { & $PY -m pytest tests/ -q } }
  'test-services' { Run $Services { mvn -q test } }
  'test' { & $PSCommandPath test-aiops; & $PSCommandPath test-services }

  # ---- Kubernetes ----------------------------------------------------------
  'k8s-deploy' {
    kubectl apply -f (Join-Path $Services 'deployment.yaml')
    kubectl apply -f (Join-Path $Root 'observability\on-demand-observability.yaml')
    kubectl apply -f (Join-Path $Aiops 'k8s\victoriametrics.yaml')
    kubectl apply -f (Join-Path $Aiops 'k8s\load-generator-fixed.yaml')
    kubectl apply -f (Join-Path $Aiops 'k8s\ollama.yaml')
  }
  'k8s-delete'    { kubectl delete namespace $Namespace }
  'status'        { kubectl get pods -n $Namespace -o wide }
  'chaos-install' {
    $bash = 'C:\Program Files\Git\bin\bash.exe'
    if (-not (Test-Path $bash)) { Die 'Git Bash not found at the usual path' }
    Run $Aiops { & $bash scripts/install_chaos_mesh.sh }
  }

  # ---- k8s clean -----------------------------------------------------------
  # `k8s-delete` removes ONE namespace. This removes everything the project puts
  # in a cluster, in the order that actually works:
  #
  #   1. Chaos experiment CRs first. A StressChaos/NetworkChaos carries a
  #      finalizer only the chaos-controller can clear, so deleting the namespace
  #      while the controller is going away leaves it Terminating forever.
  #   2. The chaos-mesh helm release (webhooks and ClusterRoles go with it).
  #   3. The three namespaces: on-demand-observability (mesh + telemetry + aiops
  #      + ollama + frontend + load-gen), devops-agent (VictoriaMetrics),
  #      chaos-mesh.
  #   4. The chaos-mesh.org CRDs -- helm deliberately leaves CRDs behind.
  #   5. PersistentVolumes left Released by the deleted PVCs (ollama-models),
  #      matched on claimRef namespace so no unrelated PV is touched.
  #
  # Nothing outside those namespaces is touched, and all of it comes back with
  # `.\mk.ps1 k8s-deploy` / `run-platform`.
  'k8s-clean' {
    $chaosKinds = @('podchaos','networkchaos','stresschaos','iochaos','httpchaos',
                    'timechaos','dnschaos','jvmchaos','kernelchaos','schedule','workflow')

    Info "1/5 deleting Chaos Mesh experiment CRs in $Namespace (finalizers block ns deletion)"
    foreach ($k in $chaosKinds) {
      kubectl get $k -n $Namespace *> $null
      if ($LASTEXITCODE -eq 0) {
        kubectl delete $k --all -n $Namespace --ignore-not-found --timeout=60s
      }
    }

    Info '2/5 uninstalling the chaos-mesh helm release'
    if (Get-Command helm -ErrorAction SilentlyContinue) {
      helm uninstall chaos-mesh -n chaos-mesh *> $null
    } else {
      Info '    helm not on PATH - skipped'
    }

    Info "3/5 deleting namespaces: $Namespace, devops-agent, chaos-mesh"
    kubectl delete namespace $Namespace devops-agent chaos-mesh --ignore-not-found --timeout=300s

    Info '4/5 deleting the chaos-mesh.org CRDs (helm leaves them behind)'
    $crds = @(kubectl get crd -o name 2>$null | Where-Object { $_ -match 'chaos-mesh\.org' })
    if ($crds.Count -gt 0) { kubectl delete @crds --ignore-not-found } else { Info '    none' }

    Info '5/5 deleting PersistentVolumes released by the above'
    $ours = @($Namespace, 'devops-agent')
    $pvs  = @()
    $raw  = kubectl get pv -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.phase}{" "}{.spec.claimRef.namespace}{"\n"}{end}' 2>$null
    foreach ($line in @($raw) -split "`n") {
      $f = ($line.Trim() -split '\s+')
      if ($f.Count -ge 3 -and $f[1] -eq 'Released' -and $ours -contains $f[2]) { $pvs += $f[0] }
    }
    if ($pvs.Count -gt 0) { kubectl delete pv @pvs } else { Info '    none' }

    Ok 'cluster clean'
    Info 'verify: kubectl get ns   (no on-demand-observability / devops-agent / chaos-mesh)'
  }

  # Destructive and slow to undo: these images are built here and side-loaded,
  # never pulled, so this is the only copy. Rebuilding all nine service images
  # is a full mvn package. Needs -Force.
  'k8s-clean-images' {
    if (-not $Force) {
      Die 'k8s-clean-images deletes the locally built traceflix images (the only copies - rebuilt by images / frontend-image / aiops-image). Re-run with -Force if that is what you want.'
    }
    $imgs = Local-Images
    Info 'removing the locally built images from the kind node stores'
    Remove-FromKind $imgs
    Info 'removing them from the host daemon'
    docker rmi @imgs *> $null
    Ok 'images cleaned - rebuild with .\mk.ps1 images / frontend-image / aiops-image'
  }

  # Everything: cluster resources, plus the images when -Force says so.
  'k8s-purge' {
    & $PSCommandPath k8s-clean -Namespace $Namespace
    if ($Force) {
      & $PSCommandPath k8s-clean-images -Force
    } else {
      Info 'images kept - .\mk.ps1 k8s-purge -Force removes those too'
    }
    Ok 'k8s purge complete'
  }

  # ---- live ----------------------------------------------------------------
  # DEPRECATED -- see the 'live' target in the Makefile for the full reasoning.
  # It never read live telemetry: run_experiment's live join was never written,
  # so this scored a GENERATED stream and, having no --out, wrote it over
  # data/results. Refuses rather than warns; the old failure was a
  # plausible-looking table, which is worse than no table.
  'live' {
    Write-Host "'live' is deprecated and does nothing -- it never read live telemetry." -ForegroundColor Yellow
    Write-Host "  run_experiment has no live join; it also defaulted to --out data/results," -ForegroundColor Gray
    Write-Host "  so this target overwrote the reported campaign with a generated run." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Score the DEPLOYED stack against a campaign you injected:" -ForegroundColor Gray
    Write-Host "    .\mk.ps1 live-replay -LiveLabels <your labels.csv> -LiveOut <its own dir>" -ForegroundColor Gray
    Write-Host "  Run the GENERATED campaign the write-up reports:" -ForegroundColor Gray
    Write-Host "    .\mk.ps1 rq124" -ForegroundColor Gray
    exit 1
  }
  'live-episodes' { Run $Aiops { & $PY faults/run_episodes.py --episodes $LiveEpisodes --labels data/labels.csv } }
  'live-replay' {
    $env:TF_LIVE = '1'
    if (-not $env:PROM_URL) { $env:PROM_URL = 'http://localhost:9090' }
    if (-not $env:VM_URL)   { $env:VM_URL   = 'http://localhost:8428' }
    if ($LiveOut -eq 'data/results_live' -and $LiveLabels -ne 'data/labels_live.csv') {
      Die "data/results_live is reserved for data/labels_live.csv - pass -LiveOut for this campaign, e.g. -LiveOut data/results_live_mine"
    }
    Run $Aiops { & $PY -u -m ml.experiments.live_replay --labels $LiveLabels --out $LiveOut }
  }
  'inject' {
    $bash = 'C:\Program Files\Git\bin\bash.exe'
    if (-not (Test-Path $bash)) { Die 'Git Bash not found at the usual path' }
    Run (Join-Path $Root 'deploy\virtfusion\vm2-services') { & $bash ./inject-fault.sh $Svc $Fault $Dur }
  }

  default {
    Write-Host "[mk] unknown target: $Target" -ForegroundColor Red
    Show-Help
    exit 2
  }
}
