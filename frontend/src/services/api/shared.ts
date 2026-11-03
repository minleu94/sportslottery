export const BASE_URL = "/api"

const LEGACY_AUTH_TOKEN_KEY = "auth_session_token"

function readLegacyAuthToken(): string | null {
  if (typeof window === "undefined") return null
  try {
    return localStorage.getItem(LEGACY_AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

function removeLegacyAuthToken(): void {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY)
  } catch {
    // The in-memory token and HttpOnly cookie remain available when storage is disabled.
  }
}

let cachedAuthToken: string | null = readLegacyAuthToken()

export function setAuthToken(token: string | null) {

  cachedAuthToken = token

  // Keep legacy tokens in memory only; the server's HttpOnly cookie persists the session.
  removeLegacyAuthToken()

}

export function getAuthToken(): string | null {
  return cachedAuthToken

}

export class ApiRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "ApiRequestError"
  }
}

export function authHeaders(existingHeaders: Record<string, string> = {}): Record<string, string> {

  const token = getAuthToken()

  const headers: Record<string, string> = { ...existingHeaders }

  if (token) {

    headers["Authorization"] = `Bearer ${token}`

  }

  return headers

}
