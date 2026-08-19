const API_BASE = '/api';

/**
 * Thin fetch wrapper: JSON in/out by default, optional multipart body, and
 * an optional bearer token. Throws with the backend's error message (or a
 * generic fallback) on any non-2xx response.
 */
export async function apiRequest(path, { method = 'GET', body, token, isFormData = false } = {}) {
  const headers = {};
  if (!isFormData) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: isFormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    throw new Error('Could not reach the server. Is the backend running?');
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    // Response had no JSON body (e.g. a 204) — that's fine.
  }

  if (!response.ok) {
    throw new Error(data?.error || `Request failed with status ${response.status}`);
  }

  return data;
}
