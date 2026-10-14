# Deploying SAFI on EC2 (make it reachable for the meeting manager)

Instance: `i-08c2eeb2f974b973d` · Public IP `<EC2_PUBLIC_IP>` ·
DNS `<EC2_PUBLIC_DNS>` · region `us-east-1`.

As of the last check the API was **not reachable from the internet** on 8000/80/443 (connection
timed out). Follow the steps below to diagnose and bring it up publicly.

---

## Step 1 — Connect and become ubuntu
In the AWS console use **EC2 Instance Connect** (or SSM Session Manager), then:
```bash
sudo su - ubuntu
```

## Step 2 — Diagnose (paste this whole block)
```bash
# find the codebase (the folder containing the `safi/` package)
PROJ=$(dirname "$(find "$HOME" /opt /srv -maxdepth 4 -name '__init__.py' -path '*/safi/*' 2>/dev/null | head -1)")
PROJ=$(dirname "$PROJ"); echo "PROJECT DIR: $PROJ"; cd "$PROJ" || echo "!! codebase not found"
python3 --version
python3 -c "import safi, fastapi, uvicorn, anthropic; print('imports OK')" 2>&1 | tail -3
ls -1 agents.yaml .env 2>&1
echo "--- is anything listening on 8000? ---"; (sudo ss -ltnp 2>/dev/null || sudo netstat -ltnp 2>/dev/null) | grep -E ':8000|:80 |:443' || echo "nothing on 8000/80/443"
echo "--- local health check ---"; curl -s -m 5 http://127.0.0.1:8000/health || echo "no local API on 8000"
echo "--- is a safi process running? ---"; pgrep -af "safi api" || echo "no safi api process"
```
This tells you: is the code importable, do `agents.yaml`/`.env` exist, is the server running, is it
bound locally. If `curl 127.0.0.1:8000/health` works but the public probe doesn't → it's the
**security group** (Step 4). If nothing is listening → start it (Step 3).

## Step 3 — Install deps + run it as a managed service (bound to 0.0.0.0)
```bash
cd "$PROJ"
python3 -m pip install -r requirements.txt            # once
# Ensure .env has the secrets (chmod 600 .env):
#   ANTHROPIC_API_KEY=sk-ant-...
#   SAFI_API_KEY=<a-long-random-secret-you-choose>    # callers must send X-API-Key: <this>
#   SAFI_LLM=anthropic
python3 -m safi init-db --config agents.yaml

# install the systemd unit (copy deploy/safi-api.service, edit WorkingDirectory/ExecStart if paths differ):
sudo cp deploy/safi-api.service /etc/systemd/system/safi-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now safi-api
sudo systemctl status safi-api --no-pager
curl -s http://127.0.0.1:8000/health        # expect {"status":"ok",...}
journalctl -u safi-api -n 30 --no-pager      # logs
```

## Step 4 — Open the port in the security group (so the platform can reach it)
In AWS console → EC2 → the instance → **Security** tab → click the security group → **Edit inbound
rules** → **Add rule**:
- Type: **Custom TCP**, Port: **8000**
- Source: the meeting-manager server's IP/CIDR (preferred) — or `0.0.0.0/0` for open testing.

Then from your laptop confirm it's public:
```bash
curl http://<EC2_PUBLIC_IP>:8000/health
```

## Step 5 (recommended for production) — domain + HTTPS
Put Nginx (or a load balancer) in front for TLS so the integrator uses `https://…`:
- Point a DNS record (e.g. `api.yourdomain.com`) at the instance.
- Nginx reverse-proxy `:443` → `127.0.0.1:8000`, with a Let's Encrypt cert (`certbot`).
- Then the base URL you hand over is `https://api.yourdomain.com`.

---

## How to let me verify it automatically
Once Step 4 is done, tell me and I'll `curl http://<EC2_PUBLIC_IP>:8000/health` (and exercise the full
API) from here. Alternatively, if you give me **AWS Access Keys** (Access Key ID + Secret) for the
`131651247675` account — not the console password — I can verify via SSM without opening any port.
