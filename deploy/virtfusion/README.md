# Deploying TraceFlix across 4 VirtFusion VMs (1 GPU + 3 normal)

> **Additive only.** Everything in `deploy/virtfusion/` is new. No file in `aiops/`,
> `services/`, `observability/`, or `paper/` is modified. The upstream project keeps
> working exactly as before; this folder is an optional deployment overlay.

This runbook spreads the platform over **four KVM VMs provisioned in VirtFusion**,
joined by a private **WireGuard** mesh, each running its tier with **Docker Compose**.

| VM | Role | Type | WG IP | Runs |
|----|------|------|-------|------|
| **VM1** | AIOps engine + dashboard | **GPU** | `10.10.0.1` | torch/XGBoost training (RQ4), online/offline experiments, FastAPI + React dashboard |
| **VM2** | TraceFlix services | normal | `10.10.0.2` | movie/actor/review microservices, load-generator, OTel collector |
| **VM3** | Telemetry backends | normal | `10.10.0.3` | Prometheus, VictoriaMetrics, Loki, Tempo |
| **VM4** | Public gateway | normal | `10.10.0.4` | Grafana + nginx (TLS + auth) — the only public VM |

**Why the GPU lands on VM1 only:** the sole GPU consumer is the AIOps engine —
`aiops/ml/models/detectors.py` trains the torch **LSTM** and **fusion** models (RQ4)
and XGBoost. The microservices and telemetry tiers are pure CPU/IO.

```
                 Internet
                    │  443 (TLS + basic-auth)
              ┌─────▼─────┐
              │   VM4     │  nginx ─/─▶ VM1:8000 (dashboard, SSE)
              │  gateway  │  Grafana ─datasources─▶ VM3
              └─────┬─────┘
        ┌───────────┼───────────────┐   (all private, WireGuard 10.10.0.0/24)
   ┌────▼────┐  ┌───▼─────┐    ┌─────▼─────┐
   │  VM1    │  │  VM2    │    │   VM3     │
   │ GPU     │  │services │    │ telemetry │
   │ aiops + │  │ + otel  │    │ prom/vm/  │
   │dashboard│  │collector│───▶│ loki/tempo│
   └─────────┘  └─────────┘    └───────────┘
        │  (optional live collectors)  ▲
        └──────────────────────────────┘
```

> **Two reproduction paths, both work after this deploy:**
> 1. **Synthetic (default, no wiring needed).** The dashboard on VM1 runs RQ1–RQ4 and
>    the online-vs-offline + cost experiments on synthetic data — VM2/VM3 not required.
> 2. **Live.** VM2 emits real MELT into VM3; VM1's collectors (optional env in
>    `vm1-gpu/docker-compose.yml`) pull from VM3 for live episodes; Grafana visualises.

---

## 0. Files in this overlay

```
deploy/virtfusion/
├── README.md                 ← you are here (run this)
├── .env.example              ← copy to .env on every VM
├── vm1-gpu/        Dockerfile, docker-compose.yml      (AIOps + dashboard, CUDA)
├── vm2-services/   docker-compose.yml, otel-collector-config.yml
├── vm3-telemetry/  docker-compose.yml, prometheus.yml, tempo.yaml, loki-config.yml
└── vm4-gateway/    docker-compose.yml, nginx.conf, grafana-datasources.yml
```

---

## 1. Provision the 4 VMs in VirtFusion

In the VirtFusion panel, create four servers from an **Ubuntu 22.04 LTS** template:

| VM | vCPU | RAM | Disk | Extra |
|----|------|-----|------|-------|
| VM1 GPU | 8 | 32 GB | 80 GB | **GPU via PCIe passthrough** (see §1a) |
| VM2 services | 4 | 8 GB | 40 GB | — |
| VM3 telemetry | 4 | 16 GB | 100 GB | larger disk for TSDB/logs/traces |
| VM4 gateway | 2 | 4 GB | 20 GB | **public IPv4** + DNS A-record |

### 1a. GPU passthrough (VirtFusion / KVM)

GPU passthrough must be enabled **by the host/hypervisor**, not from inside the guest:

- The hypervisor needs IOMMU on (`intel_iommu=on` / `amd_iommu=on`) and the GPU bound
  to `vfio-pci`. On VirtFusion this is exposed as a **PCI passthrough** device attached
  to VM1's KVM definition — request it from your provider or set it on the hypervisor.
- Verify inside VM1 after boot: `lspci | grep -i nvidia` must list the card.

If your VirtFusion plan offers a **vGPU/MIG** profile instead of full passthrough, that
works too — just install the matching guest driver in §4.

---

## 2. Base setup on **every** VM

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin wireguard git ufw
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" && newgrp docker

# clone the repo (read-only use of the upstream tree; overlay lives inside it)
git clone <your-repo-url> traceflix-platform
cd traceflix-platform/deploy/virtfusion
cp .env.example .env        # then edit secrets + confirm the WG IPs (§3, §8)
```

---

## 3. WireGuard private mesh

VirtFusion VMs don't get k8s service-DNS, so we give them stable private IPs over
WireGuard. Generate a keypair on each VM (`wg genkey | tee privatekey | wg pubkey > publickey`),
then create `/etc/wireguard/wg0.conf`. Example for **VM2** (repeat per host, changing
`Address` and listing the other three as `[Peer]`s):

```ini
[Interface]
Address = 10.10.0.2/24
PrivateKey = <VM2_PRIVATE_KEY>
ListenPort = 51820

[Peer]   # VM1 GPU
PublicKey = <VM1_PUBLIC_KEY>
Endpoint = <VM1_PUBLIC_OR_VIRTFUSION_IP>:51820
AllowedIPs = 10.10.0.1/32
PersistentKeepalive = 25

[Peer]   # VM3 telemetry
PublicKey = <VM3_PUBLIC_KEY>
Endpoint = <VM3_PUBLIC_OR_VIRTFUSION_IP>:51820
AllowedIPs = 10.10.0.3/32
PersistentKeepalive = 25

[Peer]   # VM4 gateway
PublicKey = <VM4_PUBLIC_KEY>
Endpoint = <VM4_PUBLIC_OR_VIRTFUSION_IP>:51820
AllowedIPs = 10.10.0.4/32
PersistentKeepalive = 25
```

```bash
sudo systemctl enable --now wg-quick@wg0
ping -c1 10.10.0.3        # from VM2: the mesh is up
```

> If all four VMs share a VirtFusion **internal/private network**, you can skip
> WireGuard and just set the `VM*_IP` values in `.env` to those private addresses.

---

## 4. VM1 (GPU) — NVIDIA toolkit, then deploy

```bash
# NVIDIA driver (guest)
sudo apt-get install -y nvidia-driver-550 && sudo reboot
nvidia-smi                                  # after reboot: card visible

# NVIDIA Container Toolkit (lets Docker see the GPU)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi   # GPU in a container ✔

# Build + run the AIOps engine + dashboard
cd ~/traceflix-platform/deploy/virtfusion/vm1-gpu
docker compose --env-file ../.env up -d --build
docker compose logs -f aiops        # wait for: "Open http://localhost:8000"
```

Confirm the GPU is actually used by training:
```bash
docker compose exec aiops python3 -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## 5. VM2 (services) — microservices + collector

```bash
cd ~/traceflix-platform/deploy/virtfusion/vm2-services
docker compose --env-file ../.env up -d
docker compose ps        # movie/actor/review + load-generator + otel-collector Up
```

The collector reads `VM3_TEL_IP` from `.env` and ships traces→Tempo, logs→Loki,
metrics→its `:8889` exporter for Prometheus to scrape.

---

## 6. VM3 (telemetry) — Prometheus/VM/Loki/Tempo

Prometheus must scrape the collector on VM2, so substitute the IP into the scrape
target once, then start the stack:

```bash
cd ~/traceflix-platform/deploy/virtfusion/vm3-telemetry
source ../.env
sed -i "s/__VM2_SVC_IP__/${VM2_SVC_IP}/g" prometheus.yml
docker compose --env-file ../.env up -d
curl -s "http://localhost:9090/api/v1/targets" | grep -o '"health":"[a-z]*"'   # expect "up"
```

---

## 7. VM4 (gateway) — Grafana + nginx

```bash
cd ~/traceflix-platform/deploy/virtfusion/vm4-gateway
source ../.env
sed -i "s/__VM3_TEL_IP__/${VM3_TEL_IP}/g" grafana-datasources.yml
# (TLS certs + basic-auth: see §8 before `up`)
docker compose --env-file ../.env up -d
```

Browse **https://$PUBLIC_HOST/** → AIOps dashboard, **https://$PUBLIC_HOST/grafana/** → Grafana.

---

## 8. Security hardening (do this — the upstream defaults are demo-grade)

The original manifests ship `admin/admin` Grafana, CORS `*`, and plaintext NodePorts.
On public VirtFusion IPs that is unsafe. This overlay closes it:

1. **Firewall every VM to the mesh.** Only VM4 exposes 80/443 publicly.
   ```bash
   # VM1/VM2/VM3: allow SSH + WireGuard + intra-mesh only
   sudo ufw default deny incoming && sudo ufw allow 22/tcp && sudo ufw allow 51820/udp
   sudo ufw allow from 10.10.0.0/24
   sudo ufw enable
   # VM4 additionally:
   sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
   ```
   > **Already handled:** Docker can bypass UFW by publishing straight to iptables, so
   > every published port in the VM1–VM3 compose files is **bound to that VM's WireGuard
   > IP** (`${VM*_IP}:port:port`) — they are unreachable on the public interface even
   > before UFW. Only VM4's nginx (80/443) is intentionally public. UFW above is
   > defence-in-depth. (If you skip WireGuard and set `VM*_IP` to VirtFusion private-network
   > addresses, the same binding applies to those.)
2. **Change Grafana creds** in `.env` (`GRAFANA_ADMIN_PASSWORD`).
3. **Basic-auth + TLS on the public gateway.** Generate the htpasswd and certs on VM4:
   ```bash
   cd ~/traceflix-platform/deploy/virtfusion/vm4-gateway && mkdir -p certs
   # basic-auth (replace admin/strongpass):
   docker run --rm httpd:2.4 htpasswd -nbB admin 'strongpass' > .htpasswd
   docker compose exec -T nginx sh -c 'cp /dev/stdin /etc/nginx/.htpasswd' < .htpasswd  # or bake into image
   # TLS via certbot (DNS A-record of $PUBLIC_HOST must point at VM4 first):
   sudo apt-get install -y certbot && sudo certbot certonly --standalone -d "$PUBLIC_HOST"
   sudo cp /etc/letsencrypt/live/$PUBLIC_HOST/fullchain.pem certs/
   sudo cp /etc/letsencrypt/live/$PUBLIC_HOST/privkey.pem  certs/
   docker compose --env-file ../.env restart nginx
   ```

---

## 9. Fault injection without Chaos Mesh

The upstream live experiment uses **Chaos Mesh**, which needs Kubernetes. On plain
Docker VMs, reproduce the same C1–C4 fault episodes with **Pumba** (Docker-native chaos)
on VM2 — no project change, just an external tool:

```bash
# latency spike on review-service (cf. aiops/faults/scenarios/latency-spike.yaml)
docker run -d --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
  netem --duration 120s --tc-image gaiadocker/iproute2 delay --time 300 re2:review-service

# pod-kill equivalent
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
  kill --signal SIGKILL re2:actor-service

# cpu / memory saturation (cf. cpu-saturation.yaml / memory-leak.yaml)
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
  stress --duration 120s --stressors "--cpu 4 --vm 2 --vm-bytes 256M" re2:movie-service
```

Record the start/stop timestamps as ground-truth labels exactly as the live harness does.

---

## 10. Verify end-to-end

```bash
# VM1: dashboard alive + experiments runnable on GPU
curl -s http://10.10.0.1:8000/api/health
# Or run an experiment headless inside the container (writes aiops/data/results):
docker compose -f ~/traceflix-platform/deploy/virtfusion/vm1-gpu/docker-compose.yml \
  exec aiops bash ./scripts/run_online_offline.sh 320

# VM2 -> VM3: traffic produces telemetry
curl -s "http://10.10.0.3:9090/api/v1/query?query=up" | grep -o '"value"'      # metrics
curl -s "http://10.10.0.3:3100/ready"                                          # loki ready
curl -s "http://10.10.0.3:3200/status/buildinfo"                               # tempo up

# Public: dashboard + Grafana through the gateway
curl -sk https://$PUBLIC_HOST/api/health
```

---

## Appendix A — Alternative: k3s cluster (keeps Chaos Mesh + the original manifests)

If you'd rather run the project's **unmodified** k8s manifests (`services/deployment.yaml`,
`observability/on-demand-observability.yaml`, `aiops/k8s/*`, Chaos Mesh) instead of Compose:

```bash
# VM1 GPU = control-plane + GPU worker
curl -sfL https://get.k3s.io | sh -
sudo kubectl label node vm1 nvidia.com/gpu=present node-role=gpu
# VM2/VM3/VM4 join as agents:
curl -sfL https://get.k3s.io | K3S_URL=https://10.10.0.1:6443 K3S_TOKEN=<token> sh -
# pin AIOps GPU pods to VM1 with a nodeSelector; install the NVIDIA k8s device plugin.
kubectl apply -f services/deployment.yaml
kubectl apply -f observability/on-demand-observability.yaml
kubectl apply -f aiops/k8s/victoriametrics.yaml
kubectl apply -f aiops/k8s/load-generator-fixed.yaml
bash aiops/scripts/install_chaos_mesh.sh
```

This keeps the WireGuard mesh as the k3s node network. Choose Compose (this README) for
simplicity and a literal "one service tier per VM"; choose k3s if you need Chaos Mesh and
the exact upstream manifests. Either way, the upstream project files are never edited.

---

## Appendix B — Mapping to upstream (nothing here modifies it)

| This overlay | Mirrors upstream | Difference |
|--------------|------------------|------------|
| `vm2-services/docker-compose.yml` | `services/deployment.yaml` | Compose instead of k8s; same images, OTLP wiring; review path uses the `?movieId=` fix |
| `vm2-services/otel-collector-config.yml` | collector in `observability/on-demand-observability.yaml` | exporters target VM3 over WG |
| `vm3-telemetry/*` | `observability/on-demand-observability.yaml` + `aiops/k8s/victoriametrics.yaml` | one VM, same images/versions |
| `vm1-gpu/*` | `aiops/` + `aiops/scripts/run_webui.sh` | CUDA torch wheel layered in; source bind-mounted read-only-to-project |
| `vm4-gateway/*` | Grafana in the observability manifest | adds TLS + basic-auth public edge |
