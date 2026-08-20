import { useEffect, useState } from 'react';

/**
 * Runs `load` whenever `deps` change and reports one of four states. A request
 * whose deps changed before it resolved is discarded, so a slow reply cannot
 * overwrite a newer one.
 *
 * `skip` holds the hook at 'idle' without firing, which is what the search page
 * wants before anything has been typed.
 */
export function useFetch(load, deps, { skip = false } = {}) {
  const [state, setState] = useState({ status: skip ? 'idle' : 'loading' });

  useEffect(() => {
    if (skip) {
      setState({ status: 'idle' });
      return undefined;
    }

    let cancelled = false;
    setState({ status: 'loading' });

    load()
      .then(({ data, meta }) => {
        if (!cancelled) setState({ status: 'ready', data, meta });
      })
      .catch((error) => {
        if (!cancelled) setState({ status: 'error', error });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, skip]);

  return state;
}

/** Delays a fast-changing value, so typing does not fire a request per keystroke. */
export function useDebounced(value, ms = 300) {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);

  return settled;
}
