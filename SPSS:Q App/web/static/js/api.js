// Thin fetch wrapper. Every endpoint returns JSON or throws with the server's
// own message, so callers can surface something useful rather than "failed".
export async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...options,
  });
  if (res.status === 204) return null;
  const text = await res.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = { detail: text }; }
  if (!res.ok) {
    throw new Error(payload?.detail ?? `Request failed (${res.status})`);
  }
  return payload;
}

export const get = (p) => api(p);
export const post = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body) });
export const del = (p) => api(p, { method: 'DELETE' });
