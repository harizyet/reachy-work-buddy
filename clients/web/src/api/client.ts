// The one place the browser talks to the hub. It mirrors the legacy operator
// UI's api(): paths relative to the mount (so /web/ and /hub/web/ both work),
// same-origin cookie, the X-Reachy-CSRF header on every request, no HTTP cache,
// and a 401 handler so an expired session never leaves private data on screen.

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Raised when a 2xx response does not have the shape the client relies on. */
export class ApiShapeError extends Error {
  constructor(what: string) {
    super(`Unexpected response from the hub: ${what}`);
    this.name = 'ApiShapeError';
  }
}

// The page is /web/ (or /hub/web/); its parent is the hub root in both mounts.
export function hubBase(href: string = window.location.href): string {
  return new URL('../', href).pathname.replace(/\/$/, '');
}

let unauthorizedHandler: (() => void) | null = null;

/** Registers the single callback run on any 401. Returns an unregister function. */
export function onUnauthorized(handler: () => void): () => void {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  /** Login failures are 401s that must not look like an expired session. */
  expectUnauthorized?: boolean;
}

export async function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(hubBase() + path, {
    method: options.method ?? 'GET',
    cache: 'no-store',
    credentials: 'same-origin',
    signal: options.signal,
    headers: {
      'X-Reachy-CSRF': '1',
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    if (response.status === 401 && !options.expectUnauthorized) unauthorizedHandler?.();
    let detail: unknown;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      // A gateway failure is not JSON.
    }
    throw new ApiError(
      typeof detail === 'string' && detail ? detail : `Request failed (${response.status})`,
      response.status,
    );
  }
  return (await response.json()) as T;
}
