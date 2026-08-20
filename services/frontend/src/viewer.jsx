import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { USERS } from './api.js';

const ViewerContext = createContext(null);
const STORAGE_KEY = 'traceflix.viewerId';

/** Who the app is browsing as. Kept out of the URL so a shared link is not tied
 *  to one profile, and remembered between visits. */
export function ViewerProvider({ children }) {
  const [viewerId, setViewerId] = useState(() => {
    const saved = Number(localStorage.getItem(STORAGE_KEY));
    return USERS.some((u) => u.id === saved) ? saved : USERS[0].id;
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(viewerId));
  }, [viewerId]);

  const value = useMemo(
    () => ({
      viewerId,
      setViewerId,
      viewer: USERS.find((u) => u.id === viewerId) ?? USERS[0],
    }),
    [viewerId]
  );

  return <ViewerContext.Provider value={value}>{children}</ViewerContext.Provider>;
}

export function useViewer() {
  const ctx = useContext(ViewerContext);
  if (!ctx) throw new Error('useViewer must be used inside ViewerProvider');
  return ctx;
}
