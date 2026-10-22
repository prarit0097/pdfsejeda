# Hostinger deployment record

Date: 2026-10-22. Status: **live and verified** at https://pdf.praritsidana.com.

## Location and isolation

| Item | Value |
| --- | --- |
| Public address | https://pdf.praritsidana.com |
| Server | 187.127.132.106, Ubuntu 24.04.4 LTS |
| Repository | https://github.com/prarit0097/pdfsejeda |
| Application folder | `/opt/pdfnova` |
| Image build revision | `60733fa` |
| Runtime profile revision | `c06399d` |
| Runtime Python | `3.12.15` |
| Compose project / container | `pdfnova` / `pdfnova-web-1` |
| Backend | `127.0.0.1:8086` to container port 8000 |
| Persistent volume | `pdfnova_pdfnova-data` mounted at `/data` |
| Nginx site | `/etc/nginx/sites-available/pdfnova`, enabled by its own symlink |
| ACME webroot | `/var/www/pdfnova-acme` |
| Certificate | `/etc/letsencrypt/live/pdf.praritsidana.com/` |

Existing Docker and Nginx installations were reused. No existing site file was
replaced, no existing application was restarted, and no firewall rule was changed.
After deployment and restart verification, all 15 existing container identities
and all 19 baseline virtual-host responses matched their predeployment records.

## Runtime settings

The private environment is `/opt/pdfnova/.env.hostinger` (mode 600). It contains a
fresh stable secret generated on the server; it is excluded from Git and the image.
Production settings: two processing threads, eight queued tasks, 1.5 CPU limit,
2 GiB memory limit, 256 PID limit, 256 MiB shared memory, nonroot application user,
child-process init and rotated logs (three 10 MB files). One Uvicorn process owns
the in-memory queue. Restart policy is `unless-stopped`.

Uploads are limited to 100 MiB; JSON requests to 64 MiB. File retention is two
hours; task timeout is 900 seconds. The production quota is 20 tasks per IP per hour. It was disabled only for the
private prepublic checks and restored before public activation. Private-network
URL imports remain disabled. `TRUST_PROXY=1` and Uvicorn proxy scheme parsing are
enabled behind the loopback-only host proxy, which overwrites IP/protocol headers
and clears `CF-Connecting-IP`. Do not expose this trusted backend port publicly.

The server's default Debian/Python CDNs stalled during downloads. This build uses
`mirror.sg.gs` for signed Debian packages and an offline wheelhouse for Python.
All 54 Linux wheels were checked against official PyPI SHA-256 hashes recorded in
`wheelhouse/manifest.json`; HTTPS mirrors were used only to transport matching
bytes. No dependency version was downgraded. `PDFNOVA_PYTHON_OFFLINE=1` is set for
this server build. Wheel binaries stay out of Git and the final runtime layers.

## Verification

The initial Linux engine/API/resource checks below were recorded on `14a3907`.
The later UI release is verified separately below; counts are not combined.

- DNS A record points to this server; no conflicting AAAA record was found.
- TLS 1.3 and trusted hostname verification passed from the development PC.
- HTTP redirects to the final HTTPS hostname.
- Let's Encrypt certificate expires 2027-01-20; renewal dry-run passed.
- Existing `certbot.timer` is active; the separate `pdfnova-nginx-reload` deploy
  hook reloads Nginx only when this domain's certificate renews.
- Linux container pytest: 170 passed, 3 warnings (including a read-only copied-test
  cache warning); dependency consistency check passed.
- Linux live HTTP: 58/58 passed, with real LibreOffice, Chromium, Tesseract,
  editor/forms, imports, signed downloads and SSRF rejection.
- Generic browser: 62/62 passed through the private tunnel, then 62/62 passed
  against public HTTPS, including every tool page, actual outputs and mobile layout.
- Editor/forms/workflows/mobile: eight private scenario groups passed; public
  390x844 touch editing, checkbox creation and saved PDF content also passed.
- Eight simultaneous native PDF jobs and two simultaneous HTML jobs passed.
  The observed private test cgroup peak before the final editor run was
  578289664 bytes (about 552 MiB) and 168 PIDs, with zero OOM events.
- Public forged `CF-Connecting-IP`, `X-Real-IP` and `X-Forwarded-For` headers
  did not reset quota: remaining tasks decreased 7, 6, 5 across three real jobs.
  Invalid download signatures were rejected.
- Intentional app restart recovered to healthy; a fresh HTTPS upload, processing
  and downloaded PDF check passed afterward. Production quota was confirmed at 20
  and private-network URL import remained blocked. Test quota usage was reset by
  that restart; the final verification used one task.
- Final existing-app comparison: containers 15/15 preserved; virtual-host
  status/redirect responses 19/19 unchanged. The installed PDFNova Nginx site
  exactly matches the committed `nginx.pdfnova.conf`.

Built image identity:
`sha256:9ae573c4ae749280b49fa0d4358c903a4c38a8ffe15e9aab1b44637ba62c93d5`.
The image's source revision is recorded separately from later proxy/runbook-only
commits; those changes do not rebuild application code. Machine-readable evidence
is in [verification.json](verification.json). These are bounded functional and
concurrency checks, not a guarantee for sustained production load or every PDF.

## Home/editor UI release (60733fa)

The home hero now offers the requested free editing button. It opens the editor
upload screen, where device upload, URL import, drag/drop and a direct blank
PDF action remain available. Upload opens the workspace with visible heading,
blue outlined desktop tools, touch-friendly mobile tools and a centered green
Apply changes button. Asset version URLs changed so existing browsers fetch the
updated CSS and editor JavaScript.

Verification on this release: Windows pytest 170 passed (two existing warnings),
local generic browser 63/63, local editor/forms/workflow/mobile eight groups,
public HTTPS generic browser 63/63 and public mobile actual PDF editing/saving.
The added browser scenario clicks the home CTA, uses the native file chooser,
adds text, saves and checks the downloaded PDF, then opens a blank document.
Desktop toolbar overflow is checked. The live container is healthy; the 15
existing container identities and 19 virtual-host responses remain unchanged.
The previous image is retained locally as `pdfnova-web:release-14a3907` for a
project-only rollback if needed. No proxy or production limit changes were made.

## Operations

SSH using your normal authorized identity, then:

```bash
cd /opt/pdfnova
docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml ps
docker compose --env-file .env.hostinger -p pdfnova -f deploy/hostinger/compose.yml logs --tail=100 web
curl --fail http://127.0.0.1:8086/api/tools
```

To restart only PDFNova, use the same Compose arguments followed by `restart web`.
After changing environment settings, use `up -d` so the container is recreated.
For a reviewed source update, pull the intended revision and run `up -d --build`.
Check health and real processing afterward. Never use Docker prune, `down -v`, or
volume deletion as an update or recovery step on this shared server.

To stop PDFNova, use the same Compose arguments followed by `stop web`. Its volume
and other applications remain intact. A code rollback should restore the chosen
previous image/revision for this project while preserving the private environment
and data volume. In-flight jobs are not durable across process restarts.
