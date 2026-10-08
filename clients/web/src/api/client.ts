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

// Authentication generation. Every sign-in, sign-out and session expiry advances it,
// and every request remembers the generation it started in. A response that arrives
// in a later generation is discarded (StaleSessionError) before any caller sees it, so
// a request begun before logout can never restore signed-in UI state or put the old
// owner's data into the cache the next session reads. Advancing also aborts whatever is
// still in flight, which stops the transfer as well as ignoring its result.
let generation = 0;
const inFlight = new Set<AbortController>();

export class StaleSessionError extends Error {
  constructor() {
    super('The session changed while this request was in progress');
    this.name = 'StaleSessionError';
  }
}

export function currentGeneration(): number {
  return generation;
}

export function advanceGeneration(): void {
  generation += 1;
  for (const controller of inFlight) controller.abort();
  inFlight.clear();
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
  const started = generation;
  const controller = new AbortController();
  inFlight.add(controller);
  const caller = options.signal;
  if (caller?.aborted) controller.abort();
  else caller?.addEventListener('abort', () => controller.abort(), { once: true });
  try {
    const response = await fetch(hubBase() + path, {
      method: options.method ?? 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
      headers: {
        'X-Reachy-CSRF': '1',
        ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    if (started !== generation) throw new StaleSessionError();
    if (!response.ok) {
      let detail: unknown;
      try {
        detail = ((await response.json()) as { detail?: unknown }).detail;
      } catch {
        // A gateway failure is not JSON.
      }
      if (started !== generation) throw new StaleSessionError();
      // Only a 401 for the current session ends it; a late 401 for an older one must not sign out a newer login.
      if (response.status === 401 && !options.expectUnauthorized) unauthorizedHandler?.();
      throw new ApiError(
        typeof detail === 'string' && detail ? detail : `Request failed (${response.status})`,
        response.status,
      );
    }
    const data = (await response.json()) as T;
    if (started !== generation) throw new StaleSessionError();
    return data;
  } catch (error) {
    if (started !== generation && !(error instanceof ApiError)) throw new StaleSessionError();
    throw error;
  } finally {
    inFlight.delete(controller);
  }
}
