#!/usr/bin/env bash
# First deployment only: refuse existing directories/projects/ports.
# Run as root after inspecting the shared server. No proxy configuration is changed.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this initial deployment as root."
    exit 1
fi
if [ -e /opt/pdfnova ]; then
    echo "Refusing to overwrite existing /opt/pdfnova. Inspect it before proceeding."
    exit 10
fi
if docker compose ls --format json | grep -q '"Name":"pdfnova"'; then
    echo "Refusing to reuse existing Compose project pdfnova."
    exit 11
fi
if ss -lntH | awk '{print $4}' | grep -q ':8086$'; then
    echo "Port 8086 is occupied. Choose another port before deploying."
    exit 12
fi
if docker volume inspect pdfnova_pdfnova-data >/dev/null 2>&1; then
    echo "Refusing to reuse an existing PDFNova data volume. Inspect it first."
    exit 13
fi

git clone https://github.com/prarit0097/pdfsejeda.git /opt/pdfnova
cd /opt/pdfnova
python3 - <<'PY'
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import time

# Discover existing configured names without printing config or credential values.
configuration = subprocess.run(["nginx", "-T"], capture_output=True, text=True, check=True).stdout
import re
hosts = sorted({name for group in re.findall(r"\bserver_name\s+([^;]+);", configuration)
                for name in group.split() if "." in name and not name.startswith(("www.", "*"))
                and re.fullmatch(r"[A-Za-z0-9.-]+", name)})

def probe(host):
    try:
        connection = http.client.HTTPSConnection("127.0.0.1", timeout=15,
                                               context=ssl._create_unverified_context())
        connection.request("GET", "/", headers={"Host": host})
        response = connection.getresponse()
        result = {"host": host, "status": response.status, "location": response.getheader("Location")}
        response.read(1024)
        connection.close()
        return result
    except Exception as error:
        return {"host": host, "error": type(error).__name__}

containers = [json.loads(line) for line in subprocess.check_output(
    ["docker", "ps", "--format", "json"], text=True).splitlines()]
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    health = list(pool.map(probe, hosts))
Path(".deploy-baseline.json").write_text(json.dumps(
    {"time": time.time(), "containers": containers, "sites": health}, indent=2))
os.chmod(".deploy-baseline.json", 0o600)
environment = Path("deploy/hostinger/env.example").read_text().replace(
    "REPLACE_WITH_A_RANDOM_SECRET", secrets.token_hex(32))
Path(".env.hostinger").write_text(environment)
os.chmod(".env.hostinger", 0o600)
print("Existing containers recorded:", len(containers))
print("Existing virtual hosts checked:", len(health))
print("Generated private environment; secret was not printed.")
PY

docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml config --quiet
git rev-parse HEAD
if ! docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml build > /opt/pdfnova-build.log 2>&1; then
    tail -n 70 /opt/pdfnova-build.log
    exit 20
fi
