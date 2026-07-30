#!/usr/bin/env bash
# Configure the Oracle VM to serve the Workforce Data MCP server.
# Run ON THE VM as the default `ubuntu` user:
#   scp -i ~/.ssh/oracle_mcp deploy/setup_vm.sh deploy/Caddyfile deploy/workforce-mcp.service workforce-mcp.env ubuntu@<IP>:
#   ssh -i ~/.ssh/oracle_mcp ubuntu@<IP> 'bash setup_vm.sh'
# Expects workforce-mcp.env (API keys) alongside, scp'd from the Mac.
set -euo pipefail

REPO=https://github.com/thelancehaun/workforce-data-explorer.git
APPDIR=/opt/workforce-mcp

echo "== Swap (needed on 1GB micro instances so pip install doesn't OOM)"
if [ "$(free -m | awk '/^Mem:/{print $2}')" -lt 2048 ] && [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile > /dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
fi

sudo apt-get update -q > /dev/null

echo "== Instance firewall: allow 80/443 (Oracle Ubuntu images block all but 22)"
# Insert before the platform REJECT rule; keep Oracle's iSCSI rules untouched.
REJECT_LINE=$(sudo iptables -L INPUT --line-numbers | awk '/REJECT/{print $1; exit}')
for PORT in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT "${REJECT_LINE:-1}" -p tcp --dport $PORT -j ACCEPT
  fi
done
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q netfilter-persistent iptables-persistent > /dev/null
sudo netfilter-persistent save

echo "== Python 3.13 (deadsnakes) + git"
sudo add-apt-repository -y ppa:deadsnakes/ppa > /dev/null
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3.13 python3.13-venv git > /dev/null

echo "== App user + code"
sudo useradd -r -s /usr/sbin/nologin -d $APPDIR mcp 2>/dev/null || true
sudo mkdir -p $APPDIR
if [ ! -d $APPDIR/.git ]; then
  sudo git clone --depth 1 "$REPO" $APPDIR
else
  sudo git -C $APPDIR pull --ff-only
fi
sudo python3.13 -m venv $APPDIR/.venv
sudo $APPDIR/.venv/bin/pip install --quiet -r $APPDIR/requirements.txt
sudo chown -R mcp:mcp $APPDIR

echo "== Environment file (API keys)"
sudo mv ~/workforce-mcp.env /etc/workforce-mcp.env
sudo chown root:mcp /etc/workforce-mcp.env
sudo chmod 640 /etc/workforce-mcp.env

echo "== systemd service"
sudo mv ~/workforce-mcp.service /etc/systemd/system/workforce-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now workforce-mcp
sleep 5
sudo systemctl --no-pager -l status workforce-mcp | head -12
curl -s -o /dev/null -w "local healthz -> HTTP %{http_code}\n" http://127.0.0.1:8080/healthz

echo "== Caddy (auto-TLS reverse proxy)"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl > /dev/null
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
sudo apt-get update -q > /dev/null
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q caddy > /dev/null
sudo mv ~/Caddyfile /etc/caddy/Caddyfile
sudo systemctl enable caddy
sudo systemctl restart caddy
echo "== Done. Caddy will obtain the certificate once workforcemcp.beaconturn.com resolves to this VM."
