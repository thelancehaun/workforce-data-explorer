#!/usr/bin/env bash
# Provision the Always Free Oracle VM for the Workforce Data MCP server.
# Runs on Lance's Mac using the OCI CLI in ~/.oci/clivenv (API-key auth via
# ~/.oci/config). Idempotence: names are checked before creating, so a re-run
# after a partial failure reuses what already exists.
# Every CLI flag verified against the OCI CLI reference (2026-07-29).
set -u
OCI=~/.oci/clivenv/bin/oci
PUBKEY=~/.ssh/oracle_mcp.pub

TEN=$(awk -F' *= *' '/^tenancy/{print $2}' ~/.oci/config)
[ -n "$TEN" ] || { echo "ERROR: no tenancy in ~/.oci/config"; exit 1; }
echo "== Tenancy: $TEN"

existing_id() { # $1=resource list cmd suffix, $2=display-name
  $OCI network $1 list -c "$TEN" --query "data[?\"display-name\"=='$2' && \"lifecycle-state\"=='AVAILABLE'] | [0].id" --raw-output 2>/dev/null
}

VCN=$(existing_id vcn mcp-vcn)
if [ -z "$VCN" ] || [ "$VCN" = "null" ]; then
  echo "== Creating VCN"
  VCN=$($OCI network vcn create -c "$TEN" --cidr-blocks '["10.0.0.0/16"]' \
    --display-name mcp-vcn --wait-for-state AVAILABLE --query data.id --raw-output)
fi
echo "VCN: $VCN"

IG=$($OCI network internet-gateway list -c "$TEN" --vcn-id "$VCN" --query 'data[0].id' --raw-output 2>/dev/null)
if [ -z "$IG" ] || [ "$IG" = "null" ]; then
  echo "== Creating internet gateway"
  IG=$($OCI network internet-gateway create -c "$TEN" --vcn-id "$VCN" --is-enabled true \
    --display-name mcp-ig --wait-for-state AVAILABLE --query data.id --raw-output)
fi

RT=$($OCI network vcn get --vcn-id "$VCN" --query 'data."default-route-table-id"' --raw-output)
$OCI network route-table update --rt-id "$RT" --force \
  --route-rules '[{"cidrBlock":"0.0.0.0/0","networkEntityId":"'$IG'"}]' > /dev/null
echo "Route table: default route -> internet gateway"

SL=$($OCI network vcn get --vcn-id "$VCN" --query 'data."default-security-list-id"' --raw-output)
$OCI network security-list update --security-list-id "$SL" --force \
  --ingress-security-rules '[
    {"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
    {"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":80,"max":80}}},
    {"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":443,"max":443}}}]' \
  --egress-security-rules '[{"protocol":"all","destination":"0.0.0.0/0"}]' > /dev/null
echo "Security list: 22/80/443 in, all out"

SUB=$(existing_id subnet mcp-public)
if [ -z "$SUB" ] || [ "$SUB" = "null" ]; then
  echo "== Creating public subnet"
  SUB=$($OCI network subnet create -c "$TEN" --vcn-id "$VCN" --cidr-block 10.0.0.0/24 \
    --display-name mcp-public --wait-for-state AVAILABLE --query data.id --raw-output)
fi
echo "Subnet: $SUB"

echo "== Finding latest Ubuntu 24.04 A1 image"
IMG=$($OCI compute image list -c "$TEN" --operating-system "Canonical Ubuntu" \
  --operating-system-version "24.04" --shape VM.Standard.A1.Flex \
  --sort-by TIMECREATED --sort-order DESC --query 'data[0].id' --raw-output)
echo "Image: $IMG"

INST=$($OCI compute instance list -c "$TEN" --lifecycle-state RUNNING \
  --query "data[?\"display-name\"=='workforce-mcp'] | [0].id" --raw-output 2>/dev/null)
if [ -z "$INST" ] || [ "$INST" = "null" ]; then
  echo "== Launching VM (trying each availability domain)"
  INST=""
  for AD in $($OCI iam availability-domain list --query "data[].name | join(' ', @)" --raw-output); do
    echo "-- trying $AD"
    INST=$($OCI compute instance launch -c "$TEN" --availability-domain "$AD" \
      --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":12}' \
      --image-id "$IMG" --subnet-id "$SUB" --assign-public-ip true \
      --display-name workforce-mcp --ssh-authorized-keys-file "$PUBKEY" \
      --wait-for-state RUNNING --query data.id --raw-output 2>/tmp/oci_launch_err.txt) && break
    echo "   failed: $(tail -1 /tmp/oci_launch_err.txt)"
    INST=""
  done
fi

if [ -n "$INST" ] && [ "$INST" != "null" ]; then
  IP=$($OCI compute instance list-vnics --instance-id "$INST" --query 'data[0]."public-ip"' --raw-output)
  echo "=================================================="
  echo "SUCCESS — instance $INST"
  echo "PUBLIC IP: $IP"
  echo "=================================================="
else
  echo "LAUNCH FAILED in every availability domain — see /tmp/oci_launch_err.txt"
  exit 1
fi
