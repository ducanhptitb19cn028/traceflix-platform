/**
 * Path prefix to service port.
 *
 * gateway-service exposes only the composed home page, so the pages that read
 * a single service (search, catalogue, a title, a profile) address that service
 * directly. The browser still sees one origin: the frontend host routes by
 * prefix, which is the job an ingress does in the cluster.
 *
 * Shared by the dev server (vite.config.js) and the production host
 * (server.js), so the two cannot drift apart.
 */
export const SERVICE_PORTS = {
  '/api/browse': 8080, // gateway-service, fans out across the mesh
  '/api/movies': 8081,
  '/api/users': 8082,
  '/api/search': 8083,
  '/api/actors': 8084,
  '/api/reviews': 8085,
  '/api/auth': 8086,
  '/api/recommendations': 8087,
  '/api/catalog': 8088,
};

/**
 * The same ownership, addressed the way Kubernetes addresses it.
 *
 * Run locally, the nine services are nine ports on one host. Run in the
 * cluster, each is a pod behind its own Service, so they all listen on 8080 and
 * are told apart by DNS name instead of by port. Same table, other half of the
 * address -- keeping both here is what stops the two deployments drifting.
 */
export const SERVICE_NAMES = {
  '/api/browse': 'gateway-service',
  '/api/movies': 'movie-service',
  '/api/users': 'user-service',
  '/api/search': 'search-service',
  '/api/actors': 'actor-service',
  '/api/reviews': 'review-service',
  '/api/auth': 'auth-service',
  '/api/recommendations': 'recommendation-service',
  '/api/catalog': 'catalog-service',
};

/** Longest prefix wins, so /api/catalog/search is not caught by a shorter key. */
function matchPrefix(pathname) {
  return (
    Object.keys(SERVICE_PORTS)
      .filter((prefix) => pathname === prefix || pathname.startsWith(prefix + '/') || pathname.startsWith(prefix + '?'))
      .sort((a, b) => b.length - a.length)[0] ?? null
  );
}

export function portForPath(pathname) {
  const match = matchPrefix(pathname);
  return match ? SERVICE_PORTS[match] : null;
}

/** Service name that owns the prefix, for the in-cluster deployment. */
export function serviceForPath(pathname) {
  const match = matchPrefix(pathname);
  return match ? SERVICE_NAMES[match] : null;
}
