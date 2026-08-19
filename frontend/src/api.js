const configuredBase = import.meta.env.VITE_API_BASE_URL
const API_BASE_URL = configuredBase || `http://${window.location.hostname}:8080`

export async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })

  const isAuthEndpoint = path.startsWith('/api/auth/parent/')
  if (response.status === 401 && !isAuthEndpoint) {
    window.dispatchEvent(new CustomEvent('auth-expired'))
  }

  return response
}
