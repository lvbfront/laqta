const TOKEN_KEY = "laqta_session_token";

// Plain localStorage, not a cookie -- the backend's auth is
// bearer-token-in-header on purpose (see api/app/main.py's CORS comment),
// so there's no cookie for the browser to manage here at all.
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // ignore -- worst case the user has to log in again next visit
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}
