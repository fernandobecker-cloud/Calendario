const STORAGE_KEY = 'crm_basic_auth'

export function saveCredentials(username, password) {
  const encoded = btoa(`${username}:${password}`)
  sessionStorage.setItem(STORAGE_KEY, encoded)
}

export function clearCredentials() {
  sessionStorage.removeItem(STORAGE_KEY)
}

export function getEncodedCredentials() {
  return sessionStorage.getItem(STORAGE_KEY)
}

export function isStoredAuthenticated() {
  return Boolean(getEncodedCredentials())
}

// Patch window.fetch once at module load — auto-injects Authorization header for /api calls
const _originalFetch = window.fetch.bind(window)
window.fetch = function authFetch(input, init = {}) {
  const creds = getEncodedCredentials()
  if (creds && typeof input === 'string' && input.startsWith('/api')) {
    const headers = new Headers(init.headers || {})
    if (!headers.has('Authorization')) {
      headers.set('Authorization', `Basic ${creds}`)
    }
    return _originalFetch(input, { ...init, headers })
  }
  return _originalFetch(input, init)
}
