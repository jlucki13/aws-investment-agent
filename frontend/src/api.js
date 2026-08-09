// Thin fetch wrapper around the portfolio monitor API.
//
// No auth is implemented here — the backend currently has no auth of its
// own (CORS is wide open), so there is nothing for the frontend to attach.
// That's a known, accepted gap for this personal-tool stage of the project.

const API_BASE =
  import.meta.env.VITE_API_URL ||
  "https://twvwsuh7v6.execute-api.us-east-1.amazonaws.com/v1";

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json().catch(() => null) : null;

  if (!res.ok) {
    const message = body?.error || `Request failed with status ${res.status}`;
    throw new ApiError(message, res.status);
  }

  return body;
}

// ---- Positions ----

export function getPositions() {
  return request("/positions");
}

export function upsertPosition(ticker, { shares, costBasis }) {
  return request(`/positions/${encodeURIComponent(ticker)}`, {
    method: "PUT",
    body: JSON.stringify({ shares, costBasis }),
  });
}

export function deletePosition(ticker) {
  return request(`/positions/${encodeURIComponent(ticker)}`, {
    method: "DELETE",
  });
}

// ---- Briefs ----

export function getBriefs() {
  return request("/briefs");
}

export function getLatestBrief() {
  return request("/briefs/latest");
}

// ---- Snapshots ----

export function createUploadUrl(filename, contentType) {
  return request("/snapshots/upload-url", {
    method: "POST",
    body: JSON.stringify({ filename, contentType }),
  });
}

export async function uploadSnapshotFile(uploadUrl, file) {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": file.type },
  });
  if (!res.ok) {
    throw new ApiError(`Upload to storage failed with status ${res.status}`, res.status);
  }
}

export function getSnapshots() {
  return request("/snapshots");
}

export function getSnapshot(id) {
  return request(`/snapshots/${encodeURIComponent(id)}`);
}

export function confirmSnapshot(id, positions) {
  return request(`/snapshots/${encodeURIComponent(id)}/confirm`, {
    method: "POST",
    body: JSON.stringify({ positions }),
  });
}

export function rejectSnapshot(id) {
  return request(`/snapshots/${encodeURIComponent(id)}/reject`, {
    method: "POST",
  });
}

export { ApiError, API_BASE };
