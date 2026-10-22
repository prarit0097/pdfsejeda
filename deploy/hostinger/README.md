# Isolated Hostinger deployment

Status: **deployment in progress; public availability not yet verified**. The
server inventory confirmed an existing Docker/Nginx setup and a free loopback port
8086. The app uses a new `/opt/pdfnova` folder and separate Compose project. DNS
points the user-confirmed `pdf.praritsidana.com` at the server, and its TLS
certificate has been issued. Linux image and processing verification are pending. See the eventual deployment
record for the actual release and verification results.

Use a new application folder, normally `/opt/pdfnova`, a separate Compose project
`pdfnova`, and its own named data volume. If any name/path/port already exists,
inspect it first and choose a new unused one. Do not overwrite another app.

## Inspect before changing the server

Check running containers/Compose projects, systemd services, listeners, existing
reverse proxy, firewall, disk and available RAM/CPU. Do not install or restart a
server-wide Docker daemon/proxy until its existing role has been established.
The current local port 8000 mapping is deliberately not used by this profile.

## Prepare and start (after access and server inspection)

Clone this repository into the chosen **new** folder; do not copy the PC's `.env`,
`.venv`, uploaded documents, QA files or SSH private key. Keep release changes in Git.

From the clone's root:

```bash
cp deploy/hostinger/env.example .env.hostinger
chmod 600 .env.hostinger
# Set SECRET_KEY to a fresh random secret, and review the chosen limits/port.
docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml config --quiet
docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml up -d --build
docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml ps
curl --fail http://127.0.0.1:8086/api/tools
```

The default backend binds **127.0.0.1:8086** for an existing reverse proxy. The
container uses two processing threads, finite admission, upload/quota limits,
CPU/memory/PID limits, rotated logs and a separate data volume. Exact limits must
be chosen after inspecting the shared server. Watch actual memory use during PDF
rendering; limits protect other apps but can make oversized jobs fail.

For temporary public IP access instead of a domain, explicitly change the bind
address and use an unused port, after inspecting existing firewall rules. Do not
expose the loopback backend as an unintended extra public endpoint when using HTTPS.

## Domain and TLS

Create the requested subdomain's A record in the DNS zone you control. A hostname
under `pdf.com` requires control of that parent zone; writing a hostname in a proxy
file does not register it. Remove/correct conflicting AAAA records if needed.

Use the **existing** Nginx/Caddy/Traefik setup. `nginx.conf.example` is only a
reference for an Nginx host, not a command to replace existing configuration.
Enable trusted-forwarded-IP parsing only after the proxy overwrites those headers.
Validate the proxy config before reload; obtain/enable HTTPS only after domain
ownership and routing are working. Never replace another app's virtual host.

## Verify and maintain

- Check service health and all 43 entries in `/api/tools`.
- Run upload/task/poll/download tests and real Word/HTML/OCR conversions on Linux.
- Verify the public hostname and HTTPS, then compare existing apps before/after.
- Record the deployed Git commit, actual app path, port, project/volume, proxy site
  and verification results; never publish environment secrets.
- Update with a reviewed Git revision and rebuild **only** project `pdfnova`.
- Inspect logs with `docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml logs --tail=100 web`.
- Stop only this app with the same Compose arguments and `stop`; restart with `up -d`.
- Do not use `down -v`, Docker prune commands or volume deletion as a routine fix.
- To roll back, use the recorded previous release/image for this project, preserving
  its data volume and existing server applications.

The image bundles LibreOffice, Tesseract and Chromium. These were locally tested
on Windows; a successful server image build and Linux output tests are still needed.

The optional build setting `PDFNOVA_DEBIAN_MIRROR` selects a Debian mirror host
(default `deb.debian.org`). During this deployment, the default CDN stalled;
`mirror.sg.gs` successfully served the signed Debian and security indexes. APT
retains signature checking and uses bounded download timeouts/retries. The proxy
must also clear `CF-Connecting-IP` before enabling `TRUST_PROXY=1`.

`PDFNOVA_PYTHON_PACKAGE_INDEX` can select an HTTPS Python package mirror when the
official CDN cannot complete wheel downloads (default `https://pypi.org/simple`).
Versions remain pinned in `requirements-lock.txt`; TLS verification remains enabled.
Python and browser installations use separate image layers so a browser retry
does not repeat the Python installation.

For this server, Python wheels are now prepared separately from image installation.
`wheelhouse/manifest.json` records 54 official PyPI CPython 3.12/Linux x64 wheel
URLs, sizes and SHA-256 hashes. On the server, run:

```bash
python3 deploy/hostinger/fetch-wheels.py --mirror-prefix https://mirrors.aliyun.com/pypi --mirror-prefix https://pypi.tuna.tsinghua.edu.cn
# Set PDFNOVA_PYTHON_OFFLINE=1 in the private environment after all 54 verify.
```

The optional mirrors only transport bytes; every wheel must match its official
PyPI hash. Missing or mismatched files fail the preparation. Binary wheels stay
out of Git and are bind-mounted only during the image build. Offline pip does not
consult an index and fails if a compatible dependency is missing.
