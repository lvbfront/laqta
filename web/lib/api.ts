const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(status: number, code: string | undefined, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function throwApiError(res: Response): Promise<never> {
  let code: string | undefined;
  let message = `Request failed (${res.status})`;
  try {
    const data = await res.json();
    if (data && typeof data.detail === "object" && data.detail !== null) {
      code = data.detail.code;
      message = data.detail.message ?? message;
    } else if (typeof data?.detail === "string") {
      message = data.detail;
    }
  } catch {
    // response wasn't JSON -- fall back to the generic message
  }
  throw new ApiError(res.status, code, message);
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!res.ok) await throwApiError(res);
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Guest-facing
// ---------------------------------------------------------------------------

export interface EventPublic {
  id: string;
  name_ar: string;
  name_en: string;
  consent_text_ar: string;
  consent_text_en: string;
  privacy_mode: "standard" | "strict";
  match_mode: "face" | "code" | "both";
  status: string;
}

export interface MatchResult {
  photo_id: string;
  score: number;
}

export interface MatchResponse {
  guest_session_token: string;
  matches: MatchResult[];
}

export function getEventByToken(qrToken: string): Promise<EventPublic> {
  return getJson<EventPublic>(`/api/events/by-token/${encodeURIComponent(qrToken)}`);
}

export async function matchSelfie(eventId: string, selfie: Blob, consent: boolean): Promise<MatchResponse> {
  const form = new FormData();
  form.append("selfie", selfie, "selfie.jpg");
  form.append("consent", String(consent));
  const res = await fetch(`${API_URL}/api/events/${eventId}/match`, { method: "POST", body: form });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export function getSignedPhotoUrl(
  photoId: string,
  sessionToken: string,
  variant: "preview" | "original" = "preview"
): Promise<{ url: string; expires_in_seconds: number }> {
  return getJson(`/api/guest/photos/${photoId}/url?variant=${variant}`, {
    headers: { Authorization: `Bearer ${sessionToken}` },
  });
}

export function reportNotMe(photoId: string, sessionToken: string): Promise<{ photo_id: string; feedback: string }> {
  return getJson(`/api/guest/matches/${photoId}/not-me`, {
    method: "POST",
    headers: { Authorization: `Bearer ${sessionToken}` },
  });
}

export function requestPhotoRemoval(
  photoId: string,
  sessionToken: string
): Promise<{ photo_id: string; feedback: string }> {
  return getJson(`/api/guest/matches/${photoId}/remove`, {
    method: "POST",
    headers: { Authorization: `Bearer ${sessionToken}` },
  });
}

// ---------------------------------------------------------------------------
// Dashboard (no auth -- see app/api/routes/events.py on the backend)
// ---------------------------------------------------------------------------

export interface EventDetail extends EventPublic {
  qr_token: string;
  starts_at: string | null;
  ends_at: string;
  retention_until: string;
  auto_publish: boolean;
  photo_count: number;
  ready_photo_count: number;
  pending_photo_count: number;
}

export interface PhotoListItem {
  id: string;
  status: "pending" | "processing" | "ready" | "failed";
  published: boolean;
  thumbnail_url: string | null;
  created_at: string;
}

export function getDefaultOrganization(): Promise<{ id: string; name: string }> {
  return getJson("/api/dashboard/organization");
}

export function listOrgEvents(orgId: string): Promise<EventDetail[]> {
  return getJson(`/api/organizations/${orgId}/events`);
}

export function getEvent(eventId: string): Promise<EventDetail> {
  return getJson(`/api/events/${eventId}`);
}

export interface CreateEventInput {
  name_ar: string;
  name_en: string;
  ends_at: string; // ISO datetime
  privacy_mode: "standard" | "strict";
}

export function createEvent(orgId: string, body: CreateEventInput): Promise<EventDetail> {
  return getJson(`/api/organizations/${orgId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listPhotos(eventId: string, status?: string): Promise<PhotoListItem[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return getJson(`/api/events/${eventId}/photos${query}`);
}

export async function uploadPhotos(eventId: string, files: File[]): Promise<void> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const res = await fetch(`${API_URL}/api/events/${eventId}/photos`, { method: "POST", body: form });
  if (!res.ok) await throwApiError(res);
}

export function moderatePhoto(
  eventId: string,
  photoId: string,
  action: "approve" | "reject"
): Promise<{ id: string; status: string; published: boolean }> {
  return getJson(`/api/events/${eventId}/photos/${photoId}/moderate?action=${action}`, { method: "POST" });
}
