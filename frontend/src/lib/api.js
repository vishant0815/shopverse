// Small fetch wrapper for the Shopverse APIs.
//
// - Every request goes to this same origin; next.config.mjs forwards it to the right service.
// - The access token lives only in memory (never localStorage), so injected scripts can't
//   read it from storage. The refresh token is an httpOnly cookie the browser sends itself.
// - If a request comes back 401, the token is refreshed once and the request retried.

let accessToken = null;
let refreshInFlight = null;
let onSessionEnded = () => {};

export function setAccessToken(token) {
  accessToken = token;
}

export function setSessionEndedHandler(handler) {
  onSessionEnded = handler;
}

export class ApiError extends Error {
  constructor(status, data) {
    super(messageFrom(data) || `Request failed (${status})`);
    this.status = status;
    this.data = data;
    this.code = data?.code || data?.detail?.code;
  }
}

// The services return errors in a few shapes; turn any of them into one readable sentence.
function messageFrom(data) {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (typeof data.detail === "string") return data.detail;
  if (data.detail && typeof data.detail.detail === "string") return data.detail.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join(" ");
  if (Array.isArray(data.non_field_errors)) return data.non_field_errors.join(" ");
  const first = Object.entries(data).find(([, value]) => Array.isArray(value) || typeof value === "string");
  if (first) {
    const [field, value] = first;
    const text = Array.isArray(value) ? value.join(" ") : value;
    return field === "detail" ? text : `${field.replaceAll("_", " ")}: ${text}`;
  }
  return "";
}

// Only one refresh at a time: the refresh token rotates on every use, so two parallel
// refreshes would make the second one fail and log the user out.
export function refreshAccessToken() {
  if (!refreshInFlight) {
    refreshInFlight = fetch("/api/v1/auth/refresh/", { method: "POST", credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) return null;
        const data = await response.json();
        setAccessToken(data.access);
        return data.access;
      })
      .catch(() => null)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function api(path, { method = "GET", body, headers = {}, auth = true, retry = true } = {}) {
  const init = { method, credentials: "same-origin", headers: { Accept: "application/json", ...headers } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (auth && accessToken) init.headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(path, init);

  if (response.status === 401 && auth && retry) {
    const fresh = await refreshAccessToken();
    if (fresh) return api(path, { method, body, headers, auth, retry: false });
    setAccessToken(null);
    onSessionEnded();
  }

  if (response.status === 204) return null;
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}

export function queryString(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
