/**
 * Every call goes to the frontend host on the page's own origin, which routes
 * the prefix to the service that owns it (see routes.js).
 */
async function get(path) {
  const res = await fetch(path, { cache: 'no-store' });

  if (!res.ok) {
    const err = new Error(
      res.status === 404
        ? 'That record does not exist in the catalogue.'
        : `The service answered ${res.status}.`
    );
    err.status = res.status;
    throw err;
  }

  // The host stamps how long the call took, so timings shown anywhere in the
  // app are measured on one clock rather than against the browser's.
  const hostMs = res.headers.get('x-traceflix-upstream-ms');
  const text = await res.text();

  return {
    data: JSON.parse(text),
    meta: {
      ms: hostMs === null ? null : Number(hostMs),
      bytes: new TextEncoder().encode(text).length,
    },
  };
}

/**
 * gateway-service, the only endpoint that fans out across the whole mesh.
 *
 * A failure here is worth explaining rather than reporting as a bare status:
 * the gateway composes the page in one piece, so a single service failing
 * several hops down empties the whole page, including the parts whose own
 * services are healthy.
 */
export async function getHome(userId) {
  try {
    return await get(`/api/browse?userId=${encodeURIComponent(userId)}`);
  } catch (err) {
    if (err.status >= 500) {
      err.message =
        `The gateway answered ${err.status}. A service below it did not return, and the ` +
        `home page is composed in one piece, so nothing renders even where the remaining ` +
        `services are healthy.`;
    }
    throw err;
  }
}

export const getCatalogue = () => get('/api/catalog');
export const getCatalogueTitle = (id) => get(`/api/catalog/${encodeURIComponent(id)}`);
export const searchTitles = (q) => get(`/api/search?q=${encodeURIComponent(q)}`);
export const getMovie = (id) => get(`/api/movies/${encodeURIComponent(id)}`);
export const getUser = (id) => get(`/api/users/${encodeURIComponent(id)}`);
export const getAccount = (id) => get(`/api/auth/${encodeURIComponent(id)}`);

/** Seeded profiles in user-service. */
export const USERS = [
  { id: 1, name: 'Alice Adams', tier: 'Premium' },
  { id: 2, name: 'Bob Brown', tier: 'Standard' },
  { id: 3, name: 'Carol Clark', tier: 'Premium' },
  { id: 4, name: 'Dave Davis', tier: 'Basic' },
  { id: 5, name: 'Erin Edwards', tier: 'Standard' },
];
