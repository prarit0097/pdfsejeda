# Hostinger deployment record

## Latest SEO/content release — 21d0e18

2026-10-22: deployed seven guides/59 public URLs and PS PDF site-name alias.
Only pdfnova app recreated; real Google verification setting configured privately.
Image:`sha256:f4452f8b5eac8f2f467f1fbd0ac0712ec3fd9dc49ba611e3cf5a300acdfd0440`.
Rollback:`pdfnova-web:release-dee688f`. Healthy/no OOM;15 other container identities
preserved. Public59-page/eight responsive checks passed; local671 Python cases
passed(two warnings), no failures/skips. Historical19-host response comparison,
full staged pool and public PDF smoke not rerun. Google ownership verified;
sitemap accepted but fetch unresolved. No DNS/proxy/firewall change or other app
restart. Current continuation/status:../../marketing/SEO-STATUS.md and sejedarules.md.

Date: 2026-10-22. Status: **live and verified** at https://pdf.praritsidana.com.

## Location and isolation

| Item | Value |
| --- | --- |
| Public address | https://pdf.praritsidana.com |
| Server | 187.127.132.106, Ubuntu 24.04.4 LTS |
| Repository | https://github.com/prarit0097/pdfsejeda |
| Application folder | `/opt/pdfnova` |
| Image build revision | `dee688f` |
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
`sha256:79eab66296efb053f5032bda5e461bc5c1b2e4e00fcebeacf7754ff3626f5cc0`.
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

## Signature release (b01934b)

Sign now opens a saved-signature menu with reuse/remove and New Signature.
The creation dialog offers Type, Draw, Upload Image and Camera; 12 self-hosted
font previews; seven colours; pen width/clear; optional device persistence; and
Original/Transparent A/Transparent B photo previews. Placed signature images can
be moved/resized, rotated, duplicated or deleted, with existing undo and drafts.
These are visual signatures. Photo cleanup uses two documented heuristics;
Original preserves the uploaded picture when cleanup is unsuitable.

Local verification: pytest 170 passed (two existing warnings), generic browser
63/63, existing editor eight groups and dedicated signatures four groups.
The dedicated four-group suite also passed against public HTTPS, checking actual
rendered PDF colour, PDF image transparency masks, saved library reuse/removal,
unchecked/blocked storage, touch drawing and camera handling. Camera coverage uses
a synthetic MediaStream and a denied-permission case; no physical camera was
accessed by the tests. Google Fonts network access was blocked while verifying
all 12 local signature fonts. Licences and hashes are retained with the assets.

The container is healthy. Existing container identities 15/15 and virtual-host
responses 19/19 still match the original baseline. Prior UI image rollback tag:
`pdfnova-web:release-60733fa`. No host proxy, port or quota changes were needed.

## Signature transparency correction (82a374e)

Transparent A now separates pen ink from photographed grey paper using adaptive
ink/paper classification, local background estimation and colour contrast.
Transparent B removes near-white margins while retaining grey paper. All three
previews use the same geometry; the chosen transparent image is trimmed only
for document placement. Processing retains up to 1800 pixels on the longest edge.
These are original cleanup algorithms, not a claim of exact reference parity.

Local Python tests: 170 passed, two existing warnings. Both locally and on public
HTTPS, 9/9 cleanup checks and all four signature scenario groups passed. Checks
cover eight generated photo cases, consistent preview scale, original alpha,
pen retention, grey-paper removal and an actual saved PDF on a yellow background.
The matching original photo was reviewed locally without submitting it for a
server save: sampled grey paper was fully transparent and 99.27% of dark blue
core pixels retained alpha above 180/255. Private images/evidence are not in Git.

Image: `sha256:2a1ad9719f339771ada3599a5994760081e7b7d9c719c25b94342a49282abec8`.
Container healthy, no OOM. Existing 15 container identities and 19 host
status/redirect responses match baseline. Prior signature image rollback tag:
`pdfnova-web:release-b01934b`. Host proxy and dependencies were unchanged.
Previously saved signatures retain their existing pixels; re-upload the original
photo and choose Transparent A to use the corrected cleanup.

## Signature action icons and ink colour (cbb33b6)

Fixed the broad object SVG rule that stretched all three signature action icons
across their toolbar. Rotate, duplicate and delete now have separate fixed-size
icons/buttons. Browser tests verify icon bounds, adjacent button separation,
desktop clicks and mobile duplicate/delete taps.

Cleanup preserves original foreground RGB rather than repainting it with the
darkest ink sample; soft paper edges still use the estimated ink colour to avoid
grey halos. Eight generated photos now check foreground RGB within two levels
of canvas rounding. The matching original photo was reviewed locally: original
and cleaned dark blue foreground mean RGB both [28.5, 26.6, 67.8], median channel
difference zero. No private photo was committed or submitted in a server save.

Local pytest: 170 passed, two warnings. Local and public HTTPS signature groups:
4/4; cleanup checks: 9/9, including actual saved PDF. Image:
`sha256:43a971bf6eb7c0b59e7a5d43b28663f872f5a0b740920a02d9b9b9e720e813af`.
Healthy, no OOM; 15 existing container identities and 19 host status/redirect
responses unchanged. Rollback image: `pdfnova-web:release-82a374e`.
Existing saved signature images retain their old pixels; regenerate from the
original photo to apply corrected colour handling.

## One-time signature placement and full colour preservation (547f072)

One Sign selection now permits one placement. Pending image state clears and
Select mode activates immediately afterward. Blank-page clicks do not paste
more signatures; choosing a saved signature again arms another placement.
Existing rotate/duplicate/delete controls remain available.

Removed the remaining faint-edge recolouring branch. Cleanup now changes alpha
only and retains original RGB throughout, subject to canvas rounding. Regression
includes mixed blue tones that previously hit that branch. It checks the selected
preview crop against the placed PNG and compares placed RGBA pixels exactly with
the saved PDF image, including its transparency mask. Known generated paper masks
check background removal; global neutral-colour counts are avoided because
antialiased blue ink blended over yellow can legitimately form neutral shades.

Local Python: 170 passed, two existing warnings. Local and public HTTPS:
10/10 cleanup/colour/placement checks and 4/4 signature workflow groups, including
desktop/mobile repeated page clicks and explicit signature reselection. Matching
original photo reviewed locally: every retained pixel at alpha >= 140 preserved
RGB within two levels of canvas rounding. No private photo submitted for a server
save or committed to Git. Existing saved PNGs require regeneration to change them.

Image: `sha256:87fd445d9a63ac95e8f97ae284fe5b12c8735b3e02ae452d6f8ce31b792212f1`.
Healthy, no OOM; existing 15 container identities and 19 host status/redirect
responses unchanged. Rollback tag: `pdfnova-web:release-cbb33b6`.

## Signature cursor preview (0fb90e1)

A pending signature now follows the mouse/pen over the document area at its
actual placement size, centred on the pointer. A fixed, pointer-transparent
visual overlay stays aligned while scrolling; it is never added to PDF objects.
It hides after placement, Escape, leaving the document area, browser blur or
editor close. Touch retains direct tap placement. Original PNG pixels and
single-use placement remain unchanged.

Local Python: 170 passed, two existing warnings. Local and public signature
workflow groups: 4/4, including cursor-centre bounds, scroll alignment, Escape,
no hover-created objects, pointer-event passthrough, identical placed PNG and
single placement. Public cleanup/colour/actual saved PDF checks: 10/10.

Image: `sha256:51c6658cc33326ccb5dda4ff49fe28e04e31260b6ea2f5d5bfdec29b5cd7d95b`.
Healthy, no OOM; 15 existing container identities and 19 host status/redirect
responses unchanged. Rollback tag: `pdfnova-web:release-547f072`.

## Full test pool and PDF-to-image validation fix (d74893f)

Added the isolated full regression pool documented in `qa/README.md`. All ten
local integrated stages passed: 576 Python tests (no skips), 43 tool submissions
and 160 option-control interactions at each desktop/mobile viewport, 51 page
shells, existing browser 63, shared groups five, editor eight, signatures four,
cleanup ten, sixteen concurrent jobs and live HTTP/network smoke 58. Counts are
separate overlapping layers. Python statement coverage 78.82%, branches 64.86%.
Hosted CI is configured; a hosted CI success is not claimed.

Testing found that PDF-to-image wrongly shared the required-page-selection rule
with extract/delete. Blank Pages now correctly means all pages; extract/delete
still require a selection. Only this application behavior fix and its asset
cache revision affect the production app. Public desktop and mobile submissions
both downloaded all three generated PNG images with blank Pages.

Image: `sha256:74e72fc18919a22b6d4e936ebc139a51c6e3780918caebcc3de246630d3fd279`.
Healthy, no OOM; 15 existing container identities and 19 host status/redirect
responses unchanged. Rollback: `pdfnova-web:release-0fb90e1`.

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

## Domain branding and search release (dee688f)

The live display name is Prarit Sidana PDF. Only this app's environment was updated
with APP_NAME, trusted SITE_URL and a generated public IndexNow ownership key;
other private values and the stable download secret were preserved. Compatibility
folder/service/storage identifiers remain unchanged.

The new image is `sha256:e274d85bba86ca924a0164b30c3ac34a5f1d0604caa16340c29d80c80360f4ca`.
The preceding image is tagged `pdfnova-web:release-d74893f`; its environment backup
is `/root/.pdfnova-env-before-seo` (mode 600, outside the repository). No Nginx,
firewall, certificate or other application setting changed. Healthy/no OOM;
15/15 pre-existing containers and 19/19 host responses match baseline.

Local verification: 663 Python tests and eleven stage types passed after one
targeted mobile harness retry (see qa/VERIFICATION.md). Public verification was
read-only: 56 sitemap URLs and eight desktop/mobile branding/layout checks passed.
One verified IndexNow batch of 56 public URLs returned HTTP 202; this does not
confirm indexing and is not a Google Search Console registration. Google/Bing
account verification and editorial listings remain pending owner login/email.
Actual publication/notification evidence is in marketing/SEO-STATUS.md and
marketing/seo-verification.json.
