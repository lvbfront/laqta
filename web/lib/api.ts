import { getToken } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

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
  match_mode: "face" | "code" | "both" | "sequential";
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

export function matchByCode(eventId: string, code: string): Promise<MatchResponse> {
  return getJson<MatchResponse>(`/api/events/${eventId}/match/code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
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
// Auth (see api/app/api/routes/auth.py)
// ---------------------------------------------------------------------------

export interface CurrentUser {
  id: string;
  org_id: string;
  email: string;
  role: "owner" | "staff" | "photographer" | "moderator";
}

export interface AuthResponse {
  session_token: string;
  user: CurrentUser;
}

export function register(input: { org_name: string; email: string; password: string }): Promise<AuthResponse> {
  return getJson<AuthResponse>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function login(input: { email: string; password: string }): Promise<AuthResponse> {
  return getJson<AuthResponse>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function logout(): Promise<void> {
  await fetch(`${API_URL}/api/auth/logout`, { method: "POST", headers: authHeaders() });
}

export function me(): Promise<CurrentUser> {
  return getJson<CurrentUser>("/api/auth/me", { headers: authHeaders() });
}

// ---------------------------------------------------------------------------
// Dashboard (bearer-token auth -- see api/app/api/deps.py on the backend)
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
  current_solo_number: number | null;
}

export interface PhotoListItem {
  id: string;
  status: "pending" | "processing" | "ready" | "failed";
  published: boolean;
  thumbnail_url: string | null;
  codes: string[];
  created_at: string;
}

export function listOrgEvents(orgId: string): Promise<EventDetail[]> {
  return getJson(`/api/organizations/${orgId}/events`, { headers: authHeaders() });
}

export function getEvent(eventId: string): Promise<EventDetail> {
  return getJson(`/api/events/${eventId}`, { headers: authHeaders() });
}

export interface CreateEventInput {
  name_ar: string;
  name_en: string;
  ends_at: string; // ISO datetime
  privacy_mode: "standard" | "strict";
  match_mode: "face" | "code" | "both" | "sequential";
}

export function createEvent(orgId: string, body: CreateEventInput): Promise<EventDetail> {
  return getJson(`/api/organizations/${orgId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
}

export function listPhotos(eventId: string, status?: string): Promise<PhotoListItem[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return getJson(`/api/events/${eventId}/photos${query}`, { headers: authHeaders() });
}

export async function uploadPhotos(eventId: string, files: File[]): Promise<void> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const res = await fetch(`${API_URL}/api/events/${eventId}/photos`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) await throwApiError(res);
}

export function moderatePhoto(
  eventId: string,
  photoId: string,
  action: "approve" | "reject"
): Promise<{ id: string; status: string; published: boolean }> {
  return getJson(`/api/events/${eventId}/photos/${photoId}/moderate?action=${action}`, {
    method: "POST",
    headers: authHeaders(),
  });
}

export function addPhotoCode(
  eventId: string,
  photoId: string,
  code: string
): Promise<{ photo_id: string; codes: string[] }> {
  return getJson(`/api/events/${eventId}/photos/${photoId}/codes`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ code }),
  });
}

export function removePhotoCode(
  eventId: string,
  photoId: string,
  code: string
): Promise<{ photo_id: string; codes: string[] }> {
  return getJson(`/api/events/${eventId}/photos/${photoId}/codes/${encodeURIComponent(code)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

// ---------------------------------------------------------------------------
// FTPS ingest credentials (see api/app/api/routes/ftp_credentials.py)
// ---------------------------------------------------------------------------

export interface FtpCredentialIssued {
  id: string;
  username: string;
  password: string; // plaintext -- shown exactly once, this response only
  created_at: string;
}

export function issueFtpCredential(eventId: string): Promise<FtpCredentialIssued> {
  return getJson(`/api/events/${eventId}/ftp-credentials`, {
    method: "POST",
    headers: authHeaders(),
  });
}

// ---------------------------------------------------------------------------
// Sequential ("photo booth") match mode (see api/app/api/routes/events.py)
// ---------------------------------------------------------------------------

export function nextGuest(eventId: string): Promise<{ current_solo_number: number }> {
  return getJson(`/api/events/${eventId}/next-guest`, {
    method: "POST",
    headers: authHeaders(),
  });
}

// ---------------------------------------------------------------------------
// Desktop watch-folder agent pairing (see api/app/api/routes/agent_pairing.py)
// ---------------------------------------------------------------------------

export interface AgentPairingCodeIssued {
  code: string;
  expires_at: string;
}

export function issueAgentPairingCode(eventId: string): Promise<AgentPairingCodeIssued> {
  return getJson(`/api/events/${eventId}/agent-pairing-codes`, {
    method: "POST",
    headers: authHeaders(),
  });
}
