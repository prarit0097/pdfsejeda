# Live verification of the remaining unknowns

Done on 2026-10-21. Traffic was that of one normal free user: one 590-byte PDF uploaded, 1 task accepted, 1 task refused at the quota, 2 status polls, 2 downloads of my own result. Nothing was done to provoke 429/430, and no signatures were forged or brute-forced.

## 1. Local file upload [observed]

Session setup is `GET /compress-pdf`. That page sets cookies `clientId` (long-lived) and `_s=60` (the backend node). It also renders `uplid` (e.g. `CR30R10211934`) and the form action `https://www.sejda.com/api/files/upload?_s=&uplid=<uplid>`.

```
POST /api/files/upload-check          (form: uplid=<uplid>)
→ 200 {"status":"ok"}

POST /api/files/upload?_s=&uplid=<uplid>
     multipart: uplid=<uplid>, file=@test.pdf (application/pdf)
     header:    X-FileLocalId: <client-chosen id>
→ 200 {"id":"10a471a3-59d5-45df-b935-bacb93ab6638-Z4MECQ35TKM30BV3_2"}
```

- **Plain PDFs are accepted:** the server takes an unzipped PDF, so the browser's zip wrapping is optional.
- **Id format:** the file id has the same shape as a URL-imported file id: `<uuid>-<16 chars>_<n>`.
- **CORS:** upload responses carry CORS for `https://www.sejda.com` with credentials, `POST` only, and `Content-Range` allowed. The allowed `Content-Range` header matches the chunked protocol.
- **Not tested:** the chunked path (`/api/files/upload-chunked`, for files over 5 MB) was not exercised live; it is known from code only.

## 2. Task → result → download [observed]

```
POST /api/tasks {"type":"compress","files":["<id>"],"uri":"/compress-pdf","failIfOutputSizeNotReduced":false,"userAgent":…,"www":"www60.sejda.com"}
→ 200 "AVKBKEXF-202610211934"    x-ratelimit-remaining: 0   x-ratelimit-wait: 2004

GET /api/tasks/AVKBKEXF-202610211934/change
→ {"status":"Completed","type":"compress","remark":"Your PDF file is already very well compressed",
   "resultFilename":"test.pdf","resultFileSize":864,
   "resultFullUrlPattern":"www.sejda.com/api/tasks/<id>/download/%7B%7Bfilename%7D%7D?s=web-<35 chars>&d=true&_s=60", …}
```

- **Telemetry is optional:** the task was accepted without `cvts`, `pdfjs`, `libsCache`, `consoleLogs` or `traceId`.
- **Task id format:** `<8 chars>-<yyyyMMddHHmm>`, i.e. a random part plus the submit time in UTC.
- **Output is rewritten:** I uploaded a PDF-1.4 file and got back PDF-1.5. This is consistent with SAMBox rewriting every output (agent 3).

## 3. Download signature `s=` [observed properties only]

- **Format:** `web-` + 35 characters of base64-like text (it can include `=`).
- **Stable:** the same value came back on repeated polls, so it is issued once per task, not per request.
- **Bearer link:** the download works with no cookies at all. The link alone grants access until the file is deleted ("after 2 hours").
- **Other parameters:**
  - `d=true` → `content-disposition: attachment`.
  - `_s=<n>` names the backend node holding the result.
  - The response also sends `cache-control: no-store, private` and `x-robots-tag: noindex…`.
- **How it is computed:** server-side, probably an HMAC or random token over task id + filename [inferred]. Not determinable from outside, and I didn't try.

## 4. Error responses

| Code | Body | How known |
|---|---|---|
| **402** | `{"reason":"tasks-per-hour","code":"tasks-per-hour"}` | **observed** |
| **430** | not observed (only appears for traffic Sejda's server flags as suspicious) | client code (below) |
| **429** | not observed (needs request flooding, which I didn't do) | client code (below) |
| **400** | plain-text validation message | client code (agent 2) |

**402 details:** headers `x-ratelimit-remaining: -1` and `x-ratelimit-wait: 1956` (seconds until the window resets). `x-sejda-bf: safe` appeared on this response; it may be a bot/fraud-check verdict [inferred].

**430 / 429 client behaviour:**
- **430:** the client only looks at the status code and opens the captcha (§5).
- **429:** the client ignores the body and shows "Too many attempts. Please try again later".
- **400:** the client shows the response text.

**Quota scope:** the free quota of 3 tasks per hour is counted **per IP/network, not per cookie**. My fresh session (new `clientId`) started at the count left by agent 1's earlier tasks.

## 5. Captcha [observed]

The captcha is **Cloudflare Turnstile**, loaded from `challenges.cloudflare.com/turnstile/v0/api.js?render=explicit`. The flow:
1. The server returns 430 for a task submission.
2. The client opens an iframe at `/captcha`.
3. That page calls `turnstile.render('#cf-turnstile', {action:'taskSubmit', sitekey:…})`.
4. On success it calls `window.top.captchaCallback(token)`.
5. The original task body is resubmitted with `captchaToken` added.

The token is reset after 290 s, because it expires at 300 s. Errors are tracked as `turnstileClientError`.

## 6. Server internals (public signals only)

**Edge [observed]:**
- **Cloudflare in front of everything:** `server: cloudflare`, `cf-ray` (the observed request was served from the DEL PoP), HTTP/3, and NEL reporting.
- **DNS:** `www.sejda.com`, `a.sejda.com` (analytics), `downloads.sejda-cdn.com` and `sejda-cdn.com` all resolve to Cloudflare addresses.

**Backend nodes [observed + inferred]:**
- **Numbered nodes:** the backend is a pool of nodes named `www<N>.sejda.com`; I saw `www23`, `www43` and `www60`. These names have **no public DNS**, so they are internal origin names behind Cloudflare.
- **Sticky sessions [inferred]:** the `_s=<N>` cookie and the `_s` query parameter pin a browser to one node. Uploaded files and results probably live on that node's local storage, which is why the download URL carries `_s` and the task body carries `www`.

**Application layer [inferred]:**
- **Java:** the HttpOnly `JSESSIONID` cookie (agent 1) means a Java servlet container. Agent 3 found the engine is Java + Scala (SAMBox + Sejda SDK + pro modules), so the web backend most likely runs the same engine in-process or as workers.
- **HTML→PDF and Office-grade conversions:** these have no engine in Desktop, so they need extra server-side services. A headless browser for HTML→PDF is the likely candidate [inferred, not confirmed].

**Not knowable from outside:** queue design, node count, storage and cleanup jobs, and the exact HTML→PDF / Office conversion engines.
