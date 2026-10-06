# Laqta frontend

Next.js 14 (App Router) + TypeScript + Tailwind, RTL-first, Arabic default
with an English toggle. Runs natively on the host (not in Docker — see
`../CLAUDE.md`); the API runs separately via `docker compose` from the repo
root.

See the repo root [`README.md`](../README.md) for the full picture. Details
specific to this app:

## Setup

```bash
cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL, defaults to http://localhost:8000
npm install
npm run dev
```

Requires the API reachable at `NEXT_PUBLIC_API_URL` (`docker compose up -d
postgres redis minio` + the API running, or `docker compose up api worker`).

## Routes

- `/e/[qr_token]` — guest flow: consent (bilingual text from the event
  record) → selfie capture (`getUserMedia` only -- no file-picker fallback,
  so the selfie can't be a stored photo; if the camera is unavailable or
  denied the guest is told to allow it) → matched gallery (download / "this isn't me" /
  "remove this photo of me").
- `/dashboard/events` — create an event, view its QR + guest link, live
  (polled) upload/processing counts, per-event photo upload.
- `/dashboard/events/[id]/moderate` — approve/reject photos awaiting review.

No auth (see the root README's "Dashboard API" note) — the dashboard
operates against a single implicit "Dev Organization", get-or-created by
the backend on first request.

## i18n

Hand-rolled, not a library — `lib/i18n.ts` (dictionaries) +
`components/LocaleProvider.tsx` (context, persists the choice to
`localStorage`, flips `<html dir/lang>`). Server-rendered markup always
defaults to Arabic/RTL; the toggle only takes effect client-side after
mount, so there's no hydration mismatch. See `lib/i18n.ts` for the string
tables — there's no extraction tooling, just add a key to both `ar` and
`en`.

## Talking to the API

`lib/api.ts` is the only place that calls the backend — typed wrappers per
endpoint, one `ApiError` class carrying the backend's `{code, message}`
error shape through to the UI (see `components/guest/MatchErrorScreen.tsx`
for how match validation error codes become specific on-screen guidance
rather than a generic failure message).
