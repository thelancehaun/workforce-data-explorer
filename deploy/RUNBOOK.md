# Oracle VM deployment — runbook

Goal: the hosted MCP server moves to an always-on Oracle Always Free VM at
`https://mcp.beaconturn.com/mcp`. No sleeping, no cold starts, no keep-alive,
$0/month. Render stays untouched until the new server is verified, so there is
no moment where the public URL is broken.

## Architecture

```
Internet ──HTTPS──▶ Caddy (ports 80/443, auto-TLS via Let's Encrypt)
                      │ reverse proxy
                      ▼
              mcp_server.py --http --host 127.0.0.1 --port 8080
              (systemd service, non-root user, auto-restart)
```

- VM: Ampere A1, 1 OCPU / 6 GB, Ubuntu 24.04 (within the 2 OCPU / 12 GB
  Always Free allowance)
- The MCP app binds 127.0.0.1 only — never exposed directly. Caddy is the only
  thing on the public ports and terminates TLS. (`--host` already exists in
  mcp_server.py; no code change needed.)
- Python 3.13 via deadsnakes PPA + the pinned requirements.txt — the exact
  combination verified locally, avoiding a repeat of the mcp-2.0 surprise.

## Security review

| Surface | Decision |
|---|---|
| Open ports | 22 (SSH, key-only), 80 (ACME + redirect), 443 (TLS). Everything else blocked at BOTH the Oracle security list and the instance iptables. |
| Instance firewall | Oracle Ubuntu images drop all inbound except 22 in `/etc/iptables/rules.v4` (confirmed via Oracle developer blog). setup_vm.sh inserts 80/443 ACCEPT rules before the REJECT rule and persists with netfilter-persistent. The iSCSI/boot-volume rules Oracle warns never to touch are left alone. |
| SSH | Key-only (cloud image default — no password auth). Key: `~/.ssh/oracle_mcp` on Lance's Mac. |
| App privileges | Dedicated `mcp` system user, no sudo, no shell profile. systemd `Restart=always`. |
| API keys | `/etc/workforce-mcp.env`, root:mcp 640, loaded via systemd `EnvironmentFile`. Never in the repo, never in shell history (scp'd from the Mac's .env-derived file). |
| MCP endpoint auth | None — deliberately public, same as the Render deployment today. |
| OS patching | Ubuntu unattended-upgrades (security) is on by default; leave enabled. |
| Reboot behavior | systemd service + Caddy both `enable`d → full stack survives reboots. |

## Known risks, stated honestly

1. **A1 capacity**: free tenancies sometimes get "out of capacity" at launch.
   provision.sh tries every availability domain; if all fail, we retry later
   or discuss PAYG — no partial state is left behind (script prints what it
   created).
2. **Idle reclamation**: Oracle may reclaim Always Free instances idle 7 days
   (CPU/network/memory all <20%). Real traffic + a 5-min local healthcheck
   cron likely keeps network above the floor, but this is NOT guaranteed.
   Docs do not confirm the popular claim that PAYG upgrade exempts you.
   Mitigation if it ever bites: re-run these same scripts (~15 min rebuild).
   Decision deferred with eyes open.
3. **Cert issuance**: Caddy needs the DNS A record to exist and port 80 open
   before it can get a certificate. The sequence below orders this correctly.

## Sequence (tomorrow)

1. **Lance — 60 seconds, one time**: Oracle console → profile icon →
   **User settings** → **Token and keys** → **Add API Key** → **Paste a public
   key** → paste the key Claude provides → **Add** → copy the "Configuration
   File Preview" text shown → paste it back to Claude. (Steps verified against
   Oracle's API-key docs.)
2. Claude writes `~/.oci/config` from that snippet, runs `deploy/provision.sh`
   → network + VM created, public IP printed. (Every CLI command verified
   against the OCI CLI reference.)
3. **Lance — one DNS record**: `mcp.beaconturn.com` → A record → the IP.
4. Claude: scp env file + `deploy/setup_vm.sh` to the VM, run it, watch Caddy
   obtain the cert, then verify from outside: healthz, MCP initialize,
   tools/list, and a real FRED tool call over https://mcp.beaconturn.com/mcp.
5. Only after (4) passes: update README/About URLs, keep Render as fallback
   for a transition window, then delete the keepalive workflow.

## Rollback

Nothing in steps 1–4 touches Render, the Streamlit app, or the existing
onrender.com URL. If Oracle fails at any point, the status quo is fully
intact.

## Prepared tonight (2026-07-29)

- SSH keypair `~/.ssh/oracle_mcp[.pub]` (VM access)
- API signing keypair `~/.oci/oci_api_key.pem` + `.pub` (CLI auth)
- OCI CLI installed at `~/.oci/clivenv/bin/oci`
- `deploy/provision.sh`, `deploy/setup_vm.sh`, `deploy/Caddyfile`,
  `deploy/workforce-mcp.service` (this folder)
- mcp_server.py `--host` flag confirmed present; local boot on 127.0.0.1
  verified earlier today with the pinned dependency set
