# Event Photo Delivery Platform — Build Plan

**Working name:** Laqta (لقطة) — placeholder
**One-liner:** Photographers shoot; photos land in a live cloud gallery within seconds; attendees scan a QR, take a selfie, and get only their own photos.
**Market:** Saudi Arabia — weddings, conferences, marathons, university events, Seasons.

---

## 0. Scope decision (read first)

Build **two** matching modes from day one. They serve different customers and one of them carries almost no legal risk.

| Mode | How the attendee is identified | Best for | Risk |
|---|---|---|---|
| **Face match** | Selfie → embedding → vector search | Weddings, conferences, general events | Biometric = sensitive data under PDPL |
| **Code match** | Bib number / badge QR scanned or OCR'd | Marathons, races, ticketed events, schools | Low — no biometrics |

MVP ships face match. Code match is a fast follow and is what lets you sell to sports organizers who won't touch biometrics.

---

## 1. Camera plan

You don't need to own cameras to run the platform — but you need to support the gear photographers already own, and you should own one rig for demos and testing.

### Tier A — Pro body with built-in FTP (the flagship path)

**What it is:** The camera pushes each JPEG straight to your ingest server over Wi-Fi as it's captured. No laptop, no phone, no import step.

**Bodies that support this** (verify per-body, firmware varies):
- Canon: R5 / R5 II, R3, R1, R6 Mark II, 1D X Mark III
- Nikon: Z9, Z8, Z6III, D6 (older bodies via WT-7 transmitter)
- Sony: a1, a9 III, a7 IV, a7R V, a7S III
- Fujifilm: X-H2 / X-H2S, GFX100 II

**Configuration checklist:**
1. Card setup: RAW → slot 1, **Small/Medium JPEG (~2–4 MB)** → slot 2. Only the JPEG is transmitted.
2. Camera Wi-Fi joins the photographer's 5G hotspot (not venue Wi-Fi).
3. FTP settings: server host, port 990 (FTPS implicit) or 21 with explicit TLS, per-event username, generated password, passive mode.
4. Transfer mode: auto-transfer on capture, JPEG only.
5. Set camera clock to KSA time and correct date — timestamps are your fallback matcher and your gallery ordering key.
6. Embed event ID in the IPTC "Job Identifier" or copyright field, so a misrouted upload can be recovered.

**Latency:** ~2–6 seconds shutter-to-gallery on a good 5G connection.
**Failure mode:** camera FTP queues are shallow — if the connection drops for minutes, frames can be skipped. Mitigation: end-of-event "sweep upload" from the card via the desktop agent (Tier C), deduped by MD5.

**Your demo rig:** one used Canon R6 Mark II or Sony a7 IV body + 24–70/2.8. This is the cheapest way to own a body that proves the full flagship path.

---

### Tier B — Any camera + phone bridge

**What it is:** Camera connects to an Android/iOS phone over USB-C or the camera's Wi-Fi; your mobile app pulls each new frame and uploads over mobile data.

**Who it's for:** Photographers on bodies without FTP (Canon R7/R8/R10, Nikon Z5/Z50, Sony a6700, most sub-flagship gear) — this is the majority of the Saudi wedding market.

**Build path:**
- Android first. USB host mode + **libgphoto2** (via a Kotlin/NDK wrapper) gives you event-driven capture notification and file pull for Canon/Nikon/Sony PTP bodies.
- iOS cannot do USB PTP for most cameras — on iOS, fall back to the camera's own Wi-Fi AP + vendor SDK, or ship Android-only for v1.
- Local queue in SQLite: `pending → uploading → done`, retry with exponential backoff, survives app restart and connection loss.
- Foreground service + wake lock; phone on a power bank.

**Latency:** ~5–15 seconds.
**Failure mode:** phone sleeps, USB disconnects, iOS restrictions. Ship Android, be honest about it.

---

### Tier C — Laptop tether (the editing path)

**What it is:** Camera tethered by USB to a laptop running Capture One or Lightroom Classic. Presets are applied on import, JPEGs export to a watch folder, and your **desktop agent** uploads them.

**Who it's for:** High-end weddings and corporate work where the photographer refuses to publish unedited frames. Also the recovery path for every other tier.

**Build path:**
- Cross-platform agent: Python + `watchdog`, packaged with PyInstaller. Or Electron/Tauri if you want a nicer UI.
- Watches a folder, hashes each file (MD5), uploads via your REST API with a resumable multipart, marks done in a local SQLite ledger.
- Bulk mode: point it at the whole SD card after the event to sweep anything the live path missed.

**Latency:** 10–60 seconds depending on the photographer's culling speed.

---

### Tier D — Phone-only

Second shooters, staff, guests. Just a web upload page behind the event QR with a role token. No app install. Cheap to build, and it fills gaps in coverage.

---

### Recommended kit for a single event (what you tell your customers to bring)

- 1 FTP-capable body (Tier A) per primary photographer
- 5G hotspot with a dedicated data SIM — **never** rely on venue Wi-Fi
- Power bank for hotspot + phone
- Backup: a laptop running the desktop agent, as the sweep path
- Printed QR standees, minimum 8×8 cm, placed at entry, near food, and near the exit

---

## 2. System architecture

```
┌─────────────────────────────────────────────────────┐
│  CAPTURE                                            │
│  Tier A: camera → FTPS                              │
│  Tier B: camera → phone app → HTTPS                 │
│  Tier C: camera → laptop → agent → HTTPS            │
│  Tier D: phone → web upload → HTTPS                 │
└──────────────────────┬──────────────────────────────┘
                       ▼
              ┌────────────────┐
              │  INGEST        │  FTPS server + REST upload endpoint
              │  - auth        │  Per-event virtual credentials
              │  - dedupe MD5  │
              │  - write S3    │
              │  - enqueue job │
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │  WORKERS       │  Redis queue
              │  1. thumbnails │  libvips: 300px, 1200px, watermarked preview
              │  2. face detect│  RetinaFace
              │  3. embed      │  ArcFace → 512-d vector
              │  4. index      │  pgvector
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │  MATCH API     │  selfie → embed → cosine search → gallery
              └───────┬────────┘
                      ▼
              ┌────────────────┐
              │  GUEST WEB     │  QR → selfie → my photos → download
              │  PHOTOGRAPHER  │  event setup, live monitor, moderation
              └────────────────┘
```

### Stack

| Layer | Choice | Why |
|---|---|---|
| API | Python 3.11 + FastAPI | Matches your ML stack; async handles upload bursts |
| DB | PostgreSQL 16 + **pgvector** | One database for relational + vector. Don't add FAISS until you outgrow it |
| Queue | Redis + RQ | Simpler than Celery, enough for this |
| Storage | S3-compatible — MinIO in dev, KSA-region object storage in prod | Data residency, see §4 |
| FTP ingest | `pyftpdlib` with a custom authorizer, or pure-ftpd + inotify | Per-event credentials issued by your API |
| Images | `pyvips` | 5–10× faster than Pillow for thumbs |
| Face | **InsightFace `buffalo_l`** (RetinaFace + ArcFace r100, 512-d) | Self-hosted, no data leaves KSA, no per-call cost, strong on masked/angled faces |
| Frontend | Next.js 14 + Tailwind, RTL-first | Arabic default, English toggle |
| Deploy | Docker Compose → single GPU VM to start | A single RTX 4000-class GPU handles thousands of photos/hour |

### Matching details that decide whether this works

- Normalize embeddings, use **cosine similarity**. Start threshold at **0.38**, then tune on a held-out set of real event photos.
- Return matches sorted by score, and show a "not you? remove" control — user feedback is your cheapest evaluation signal.
- Detect faces below ~40px and drop them; background crowd faces cause most false positives.
- Store per-face bounding box + embedding as separate rows. One photo has many faces.
- Quality gate on the selfie: reject blurry, dark, multi-face, or no-face selfies **before** searching, with a clear message. Bad selfies cause most "your app doesn't work" complaints.
- Benchmark on a labeled set you build yourself from a real event. Report precision@k and recall; a miss is far worse than an extra photo.

---

## 3. Data model (core tables)

```
organizations(id, name, cr_number, account_type, created_at)
      -- account_type: 'organizer' | 'photographer'
users(id, org_id, email, password_hash, role)
      -- role: 'owner' | 'staff' | 'photographer' | 'moderator'
events(id, org_id, name_ar, name_en, starts_at, ends_at,
       qr_token, status, retention_until, consent_text_ar, consent_text_en,
       privacy_mode, match_mode, auto_publish, brand_logo_key, sponsor_overlay_key)
      -- privacy_mode: 'standard' | 'strict'
      -- match_mode:   'face' | 'code' | 'both'
photographers(id, org_id, user_id, name, ftp_username, ftp_password_hash)
photos(id, event_id, photographer_id, s3_key, md5, captured_at,
       width, height, status, published, moderated_by)
faces(id, photo_id, bbox, embedding vector(512), det_score)
guests(id, event_id, phone_hash, consent_at, consent_ip, selfie_deleted_at)
guest_faces(id, guest_id, embedding vector(512), expires_at)
matches(id, guest_id, photo_id, score, feedback)
downloads(id, guest_id, photo_id, at)
audit_log(id, actor, action, subject, at)
```

Note what is **absent**: no stored selfie image, no name, no raw phone number.

---

## 4. PDPL compliance, designed in

Biometric identifiers are sensitive personal data under Saudi PDPL. Build these as constraints, not features:

1. **Consent gate before the selfie.** Bilingual, explicit, un-pre-ticked. Log timestamp + IP into `guests`. This log is your defense.
2. **Never persist the selfie.** Compute the embedding in memory, write the vector, discard the image. Set `selfie_deleted_at` immediately.
3. **Expiry.** `guest_faces.expires_at` defaults to event end + 30 days. A nightly job hard-deletes expired vectors. `events.retention_until` purges photos too.
4. **Data residency.** Enforcement now pushes sensitive and personally identifiable data to be stored inside the Kingdom. Host in a KSA region. Do not call a foreign face API — this alone justifies self-hosting InsightFace.
5. **No public gallery, ever.** A guest sees only photos they matched. No browsable album, no sequential IDs, signed URLs with short TTL.
6. **Right to erasure.** One-tap "delete my data" that removes vectors, matches, and download history.
7. **SDAIA registration** as a data controller processing sensitive data, and a named DPO once you're at scale. Get a Saudi lawyer to review the consent text before your first paid event — this is not a place to improvise.
8. **Photographer-side moderation.** A hold queue where uploads land unpublished until approved. Non-negotiable for weddings.

**The women's-events case is your product wedge.** "Nobody can browse; you see only your own face; everything is deleted after 30 days; data never leaves the Kingdom" is a stronger pitch in this market than any feature the international tools offer.

---

## 5. Build phases

**Phase 1 — Core loop (2–3 weeks)**
Upload via REST → S3 → thumbnails → face detect/embed → pgvector → guest page: QR, consent, selfie, matched gallery, download. Seed with a folder of test photos. No FTP yet.

**Phase 2 — Live capture (1–2 weeks)**
FTPS ingest server with per-event credentials. Desktop watch-folder agent. Live gallery that updates as photos land.

**Phase 3 — Product (2–3 weeks)**
Photographer dashboard: create event, generate QR + FTP creds, monitor upload rate, moderation queue. Arabic/RTL. Watermarked previews, clean downloads.

**Phase 4 — Commercial**
Code match (bib/badge) mode. Paid downloads. Multi-photographer events. Android bridge app. Retention/purge automation and the audit log.

---

## 6. Prompt for Claude Code

Copy everything below into Claude Code in an empty repo.

---

> I'm building an event photo delivery platform for the Saudi market. Photographers upload photos live during an event; attendees scan a QR code, submit a selfie, and receive only the photos they appear in, matched by face recognition. I want to build Phase 1: the core matching loop, end to end and running locally.
>
> **Stack (please use exactly this):**
> - Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic
> - PostgreSQL 16 with the pgvector extension
> - Redis + RQ for background jobs
> - MinIO for S3-compatible object storage in development, accessed via boto3
> - InsightFace (`buffalo_l` model pack) for face detection and 512-d ArcFace embeddings
> - pyvips for thumbnailing and watermarking
> - Next.js 14 (App Router) + TypeScript + Tailwind for the frontend, RTL-first with Arabic as the default locale and an English toggle
> - Everything runs under a single `docker compose up`
>
> **What to build:**
>
> 1. **Data model** with Alembic migrations for: `organizations` (with `account_type` of `organizer` or `photographer`), `users` (roles: `owner`, `staff`, `photographer`, `moderator`), `events`, `photographers`, `photos`, `faces` (with a `vector(512)` column and an HNSW index on cosine distance), `guests`, `guest_faces`, `matches`, `downloads`, `audit_log`. Model the schema so no selfie image is ever persisted — only its embedding.
>
>    Events carry a `privacy_mode` of `standard` or `strict`, and an `auto_publish` boolean. When `privacy_mode` is `strict`, `auto_publish` must be forced to false at the database level (check constraint) and photos stay unpublished until a moderator approves them. Enforce this in the API layer too — a strict event must never expose a photo that hasn't been explicitly approved.
>
> 2. **Ingest API:** `POST /api/events/{event_id}/photos` accepting multipart uploads with an MD5 dedupe check. Write the original to MinIO, create a `photos` row with status `pending`, and enqueue a processing job. Support batch uploads.
>
> 3. **Worker pipeline** (RQ job per photo): generate a 300px thumbnail, a 1200px watermarked preview, and keep the original; strip GPS EXIF from all derivatives; run RetinaFace detection; drop faces whose bounding box is under 40px or whose detection score is under 0.5; align each face to a 112×112 crop using the five landmarks via a similarity transform (do not skip alignment — accuracy collapses without it); compute a normalized ArcFace embedding per face; insert `faces` rows; set the photo status to `ready`.
>
> 4. **Match API:** `POST /api/events/{event_id}/match` taking a selfie image and a consent flag. Validate the selfie first (exactly one face, detection score above threshold, not too small or blurry) and return a clear, specific error if it fails. Compute the embedding, run a cosine-similarity search over `faces` scoped to that event, threshold at 0.38 (configurable via env var), group results by photo, take the max score per photo, and return matched photos sorted by score. Create the `guests` row with a consent timestamp, store the embedding in `guest_faces` with `expires_at` set to event end + 30 days, and **never write the selfie to disk or object storage**.
>
> 5. **Delivery API:** signed, short-TTL URLs for previews and originals, scoped to a guest session token. A guest must never be able to enumerate or access photos they didn't match. Log every download.
>
> 6. **Purge job:** a scheduled RQ job that hard-deletes expired `guest_faces` rows and any event data past its retention date, writing to `audit_log`.
>
> 7. **Frontend, three routes:**
>    - `/e/[qr_token]` — guest flow: bilingual consent screen (explicit checkbox, not pre-ticked), then camera/upload selfie capture, then the matched gallery with per-photo download, a "this isn't me" feedback control, and a "remove this photo of me" request that immediately hides the photo from all matches and flags it for the organizer.
>    - `/dashboard/events` — create an event, view its QR code, see live upload count and photo grid.
>    - `/dashboard/events/[id]/moderate` — approve or reject pending photos before they become visible to guests.
>
> 8. **Seed script** that creates a demo event and ingests a local folder of test photos so I can exercise the whole flow immediately.
>
> **Constraints:**
> - All face processing must run locally. Do not call any external face recognition API.
> - There is no "browse all photos" view for anyone, in any role, at any time. Moderators see only the pending queue. Guests see only their own matches. Do not add a gallery-wide browse endpoint even as an admin convenience.
> - No selfie image is ever written to disk, object storage, logs, or a temp file. Compute the embedding in memory and discard.
> - Write pytest tests for the matching logic, the dedupe path, the guest access-scoping rules, and specifically that a strict-mode event never returns an unapproved photo.
> - Include a README with setup steps and the environment variables.
>
> Start by laying out the repo structure and the data model, and check with me before you write the worker pipeline.

---

## 7. Decisions

### 7.1 Business model — two products, one core

The platform is one codebase with two front doors, distinguished by `organizations.account_type`.

**Product A — Organizer (primary, B2B)**
The event organizer pays; guests get their photos free. Sold per event.

| Tier | Fits | Includes |
|---|---|---|
| Starter | up to 300 guests, 2,000 photos | 1 photographer seat, 14-day retention |
| Standard | up to 1,000 guests, 10,000 photos | 3 seats, 30-day retention, branded gallery |
| Premium | 1,000+ guests | unlimited seats, 90-day retention, white-label domain, on-site support |

Add-ons, priced separately: extra photographer seats, **sponsor logo overlay on every photo** (the strongest upsell for corporate and conference clients — the sponsor pays for it, not the organizer), extended retention, same-day highlight reel.

Sales motion: invoice-based, bank transfer, ZATCA-compliant e-invoicing (Fatoora) required — treat this as a Phase 4 blocker before your first corporate invoice, not an afterthought.

**Product B — Photographer (self-serve SaaS)**
Freelance and studio photographers who bring their own clients, mostly weddings. Monthly subscription or event credits, paid by card. They keep the client relationship; the gallery carries *their* brand, not yours.

Payments: Moyasar or Tap Payments for mada, Visa/Mastercard, and Apple Pay. Card-on-file self-serve, no sales call.

**Why both:** the organizer product has the higher deal size and slower cycle; the photographer product gives you volume, distribution, and word-of-mouth inside the photographer community — which is where organizer leads actually come from. The photographer tab is your marketing channel disguised as a revenue line.

### 7.2 Women's events — `privacy_mode: 'strict'`

Supported, and it's the wedge. It is an event-level setting the organizer turns on at creation, not a separate product.

When `privacy_mode = 'strict'`:

- **`auto_publish` is forced off.** Nothing reaches a guest until a moderator approves it. No exceptions, not even for the account owner.
- **No sharing surface.** No share buttons, no public link, no OG preview images, no gallery-wide view for anyone. Signed URLs only, short TTL, single-guest scope.
- **Staff cannot browse after moderation closes.** Once the event ends, admin views show counts and status, not images. Access to originals requires a logged, justified action in `audit_log`.
- **Retention default drops to 7 days** after event end.
- **"Remove me" request.** A guest can flag any photo she appears in for removal. It is immediately hidden from all matches and queued for the organizer. This is a real cultural and legal requirement, not a nicety — build it in Phase 3, not later.
- **Photographer accounts are scoped to the single event** and lose access when it closes.
- **`match_mode = 'code'` is offered as the default** for the most conservative clients: wristband or invitation QR instead of a selfie, so **no biometric data is processed at all**. Face match remains available as an explicit opt-in per guest.

Be honest with clients about the limit: you cannot prevent screenshots. What you can guarantee is that no one is ever shown a photo of someone else, and that everything is destroyed on a fixed schedule. Say exactly that, in writing, in Arabic.

### 7.3 Hosting — dev box now, in-Kingdom before the first real event

**Now (Phase 1–3):** local dev box — an Apple Silicon MacBook with 16GB is sufficient. Postgres, Redis, MinIO, API and worker in Docker Compose (allocate ~8GB to Docker); run the Next.js dev server natively on the host, since containerized Node on macOS gets slow file watching for no benefit. Use `pgvector/pgvector:pg16` for arm64. Run onnxruntime on the **CPU** provider, not CoreML — CoreML is unreliable with InsightFace graphs, and CPU gives ~200–500ms per photo on M-series, which is fine for development. Pick `buffalo_l` and never switch model packs: embeddings from different models aren't comparable, so a switch invalidates every stored vector. Keep the dev test set to a few hundred photos and write a teardown script — 5,000 JPEGs is ~15GB. Rent an hourly GPU (RunPod, Vast.ai) only for throughput benchmarking, then destroy it.

**The rule that makes this safe:** no real attendee face ever touches the dev box. Test with your own face, consenting friends who sign a written form, and a public face dataset for accuracy benchmarks. If you never create real biometric data outside the Kingdom, you never have to move it.

**Before the first paid event:** provision in a Saudi region. As of 31 July 2026 the generally available options are Google Cloud (Dammam, `me-central2`), Oracle Cloud (Jeddah `me-jeddah-1`, Riyadh `me-riyadh-1`), Huawei Cloud (Riyadh), Alibaba Cloud via SCCC (Riyadh), and Tencent Cloud (Riyadh). **AWS and Azure have announced Saudi regions but neither has launched** — do not architect around them. Google Dammam and Oracle Jeddah both offer GPU instances, which you need for self-hosted inference.

Keep the whole stack in Docker Compose so this stays a provisioning task, not a rewrite.
