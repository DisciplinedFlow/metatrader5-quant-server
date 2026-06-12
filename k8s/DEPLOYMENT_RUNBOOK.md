# Deployment Runbook — MT5 Quant Server on K3s (new VM)

End-to-end rollout from zero to a trading cluster. Companion to `k8s/README.md`
(which documents the manifests themselves). Work through the phases in order;
each ends with a verification gate — don't continue past a failing gate.

---

## Phase 0 — Prerequisites (before renting anything)

- [ ] MT5 broker account credentials (start with a **demo account** — see Phase 8)
- [ ] A domain you control, with DNS managed somewhere you can add A records
- [ ] API keys ready for whatever is enabled in `.env`: Anthropic (AI Brain /
      Polymarket LLM), Polymarket wallet, Hyperliquid, Lighter
- [ ] This repo accessible from the VM (`gh auth login` or a deploy key)

## Phase 1 — Provision the VM

**Requirements (hard):** amd64 — Wine/MT5 is x86-only, no ARM instances.

**Sizing:** container limits sum to ~11 GB (MT5 4G, Celery 3G, Django 2G,
Postgres 1G, Redis+Beat 1G) plus K3s overhead and the future monitoring stack.

| Spec | Minimum | Recommended |
|---|---|---|
| vCPU | 4 | 8 |
| RAM | 16 GB | 16 GB |
| Disk | 80 GB NVMe | 160+ GB |

**Suggested:** Hetzner CPX41 (8 vCPU AMD, 16 GB, 240 GB NVMe, ~€30/mo),
Falkenstein or Nuremberg region — EU placement keeps broker latency low.
DigitalOcean/Vultr equivalents work the same. OS: **Ubuntu 24.04 LTS**, with
your SSH public key set at creation (never password auth).

**Gate:** `ssh root@<ip>` works with your key.

## Phase 2 — Harden the host

```bash
adduser deploy && usermod -aG sudo deploy
rsync -a ~/.ssh /home/deploy/ && chown -R deploy:deploy /home/deploy/.ssh

# SSH: no root login, no passwords
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/; s/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall: only SSH + web
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable

apt update && apt install -y fail2ban unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

**Gate:** `ssh deploy@<ip>` works; `ssh root@<ip>` refused; `ufw status` shows 22/80/443 only.

## Phase 3 — Install Docker + K3s

```bash
# Docker (for building images; k3s itself uses containerd)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy   # re-login afterwards

# K3s with the bundled Traefik ingress controller (the manifests expect it)
curl -sfL https://get.k3s.io | sh -

# kubectl access for the deploy user
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown deploy ~/.kube/config && chmod 600 ~/.kube/config
export KUBECONFIG=~/.kube/config   # add to ~/.bashrc
```

**Gate:** `kubectl get nodes` shows the node `Ready`; `kubectl -n kube-system get pods` shows traefik running.

## Phase 4 — DNS

Create A records pointing at the VM IP (match what you'll put in `.env`):

```
django.mt5.<domain>      → <ip>
api.mt5.<domain>         → <ip>
vnc.mt5.<domain>         → <ip>
dashboard.mt5.<domain>   → <ip>
grafana.mt5.<domain>     → <ip>   (for the later monitoring phase)
```

**Gate:** `dig +short django.mt5.<domain>` returns the VM IP.

## Phase 5 — Clone, configure, build, deploy

```bash
git clone https://github.com/nomubuilders/mt5-quant-server.git && cd mt5-quant-server
cp .env.example .env
vim .env   # real broker creds, strong POSTGRES_PASSWORD, real domains, API keys
           # add: DASHBOARD_DOMAIN=dashboard.mt5.<domain>

k8s/scripts/build-images.sh   # builds mt5/django/dashboard, imports into k3s
k8s/scripts/deploy.sh         # secret from .env + manifests + ingress
kubectl -n mt5-quant get pods -w
```

Expected startup behavior: postgres/redis first; django's migrate
init-container runs once postgres is ready; celery restarts until redis is up
(normal); **MT5 takes up to ~10 minutes on first boot** (Wine init + terminal
install into the `mt5-config` PVC — subsequent restarts are fast).

**Gate:** all pods `Running` and `READY 1/1`;
`kubectl -n mt5-quant exec deploy/django -- python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/v1/bot/status/').status)"` prints `200`.

## Phase 6 — TLS (cert-manager)

```bash
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm install cert-manager jetstack/cert-manager -n cert-manager \
  --create-namespace --set crds.enabled=true

kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: <your-email>
    privateKeySecretRef:
      name: letsencrypt-key
    solvers:
      - http01:
          ingress:
            class: traefik
EOF
```

Then uncomment the `cert-manager.io/cluster-issuer` annotation and `tls:` block
in `k8s/ingress.template.yaml` and re-run `k8s/scripts/deploy.sh`.

**Gate:** `https://dashboard.mt5.<domain>` loads with a valid certificate
(`kubectl get certificate -n mt5-quant` shows `Ready=True`).

## Phase 7 — MT5 terminal login

Open `https://vnc.mt5.<domain>` (KasmVNC, credentials = `CUSTOM_USER`/`PASSWORD`
from `.env`). In the MT5 terminal: log into the **demo** broker account, verify
market watch ticks for the 13 configured symbols.

**Gate:** `curl https://api.mt5.<domain>/health` (or any market-data endpoint)
returns live data; dashboard Overview page shows tick data updating.

## Phase 8 — Go-live gates (in order, no skipping)

1. **Demo account, full cycle**: watch the dashboard + logs through at least one
   complete trade — entry fired by beat, trailing stop ratchets, close detected,
   trade persisted in Postgres.
2. **Restart resilience**: `kubectl -n mt5-quant rollout restart deploy/mt5
   deploy/celery deploy/celery-beat` — confirm MT5 re-logs in from the PVC,
   beat resumes schedules, open demo positions are re-managed within one 15s tick.
3. **Risk limits verified**: confirm the daily-loss halt and per-strategy gates
   trigger on the demo account (they live in the app, not in K8s).
4. Only then switch `.env` to the live account, re-run
   `k8s/scripts/deploy.sh`, and restart the mt5 + django + celery deployments.

## Phase 9 — Backups & monitoring (first week)

- **Postgres**: nightly `pg_dump` CronJob or VM-level snapshots (Hetzner
  snapshots are one click). Test a restore once.
- **Monitoring**: `kube-prometheus-stack` + `loki-stack` Helm charts; import
  the dashboards from `monitoring/dashboards/`. Route alerts (AlertManager →
  email/Pushover configs in `monitoring/configs/alertmanager/` translate
  directly).
- **The one alert that matters**: celery-beat pod not Ready > 2 min — if beat
  is dead, open positions stop being trailed.

---

## Rollback

Images are tagged (`build-images.sh v2`): `kubectl -n mt5-quant set image
deploy/django django=mt5-quant/django:v1` etc. State (Postgres, Wine prefix,
ML models, Redis AOF) lives in PVCs and survives any pod-level rollback.
Worst case: `kubectl delete ns mt5-quant` and redeploy — PVCs are deleted with
the namespace, so snapshot/dump first.
