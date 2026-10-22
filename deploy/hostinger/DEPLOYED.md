# Hostinger deployment record

Date: 2026-10-22. Status: **build/verification in progress; processing not public yet**.

## Location and isolation

| Item | Value |
| --- | --- |
| Public address | https://pdf.praritsidana.com |
| Server | 187.127.132.106, Ubuntu 24.04.4 LTS |
| Repository | https://github.com/prarit0097/pdfsejeda |
| Application folder | `/opt/pdfnova` |
| Image build revision | `14a3907` |
| Compose project / container | `pdfnova` / `pdfnova-web-1` |
| Backend | `127.0.0.1:8086` to container port 8000 |
| Persistent volume | `pdfnova_pdfnova-data` mounted at `/data` |
| Nginx site | `/etc/nginx/sites-available/pdfnova`, enabled by its own symlink |
| ACME webroot | `/var/www/pdfnova-acme` |
| Certificate | `/etc/letsencrypt/live/pdf.praritsidana.com/` |

Existing Docker and Nginx installations were reused. No existing site file was
replaced, no existing application was restarted, and no firewall rule was changed.
Before first application startup, all 15 existing container identities and all
19 baseline virtual-host responses matched their predeployment records.

## Runtime settings

The private environment is `/opt/pdfnova/.env.hostinger` (mode 600). It contains a
fresh stable secret generated on the server; it is excluded from Git and the image.
Production settings: two processing threads, eight queued tasks, 1.5 CPU limit,
2 GiB memory limit, 256 PID limit, 256 MiB shared memory, nonroot application user,
child-process init and rotated logs (three 10 MB files). One Uvicorn process owns
the in-memory queue. Restart policy is `unless-stopped`.

Uploads are limited to 100 MiB; JSON requests to 64 MiB. File retention is two
hours; task timeout is 900 seconds. The intended production quota is 20 tasks per
IP per hour. It is temporarily disabled while the backend is private for tests;
it must be restored before public processing is enabled. Private-network URL
imports remain disabled. Nginx must overwrite forwarded IP headers and clear
`CF-Connecting-IP` before `TRUST_PROXY=1` is enabled.

The server's default Debian/Python CDNs stalled during downloads. This build uses
`mirror.sg.gs` and `https://mirrors.aliyun.com/pypi/simple/`, keeping Debian package
signatures, Python version pins and HTTPS certificate verification enabled.

## Verification

- DNS A record points to this server; no conflicting AAAA record was found.
- TLS 1.3 and trusted hostname verification passed from the development PC.
- HTTP redirects to the final HTTPS hostname.
- Let's Encrypt certificate expires 2027-01-20; renewal dry-run passed.
- Existing `certbot.timer` is active; the separate `pdfnova-nginx-reload` deploy
  hook reloads Nginx only when this domain's certificate renews.
- Linux image built; private pytest 170 passed, HTTP smoke 58/58, browser 62/62,
  editor/mobile 8 groups, concurrent PDF 8/8 and simultaneous HTML 2/2 passed.
  Cgroup peak before final editor run: 578289664 bytes, 168 PIDs, zero OOM events.
  Public activation verification remains pending.
- Final existing-app comparison after startup: pending.

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
