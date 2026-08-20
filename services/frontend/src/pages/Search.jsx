import { useSearchParams } from 'react-router-dom';
import { useState } from 'react';
import { searchTitles } from '../api.js';
import { useDebounced, useFetch } from '../useFetch.js';
import TitleList from '../components/TitleList.jsx';
import { EmptyState, ErrorState, SectionHead } from '../components/states.jsx';
import { ListSkeleton } from '../components/Skeletons.jsx';

export default function Search() {
  const [params, setParams] = useSearchParams();
  const urlQuery = params.get('q') ?? '';
  const [typed, setTyped] = useState(urlQuery);

  // The query lives in the URL so a search can be linked to and survives reload,
  // but it is only written once typing settles.
  const query = useDebounced(typed.trim(), 300);

  const state = useFetch(
    () => {
      setParams(query ? { q: query } : {}, { replace: true });
      return searchTitles(query);
    },
    [query],
    { skip: query.length === 0 }
  );

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <label htmlFor="q" className="text-[13px] text-ink-muted">
          Search the catalogue
        </label>
        <input
          id="q"
          type="search"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Title keyword"
          autoComplete="off"
          className="w-full max-w-[34rem] rounded-control border border-rule-strong bg-paper px-3 py-2 text-[16px] text-ink placeholder:text-ink-muted"
        />
        <p className="text-[13px] text-ink-muted">
          Handled by search-service, which queries catalog-service.
        </p>
      </div>

      <div aria-live="polite" className="flex flex-col gap-3">
        {state.status === 'idle' && (
          <EmptyState title="Type to search">
            Matching is on the title, so a fragment such as &ldquo;god&rdquo; or
            &ldquo;matrix&rdquo; is enough.
          </EmptyState>
        )}

        {state.status === 'loading' && <ListSkeleton rows={4} heading={false} />}

        {state.status === 'error' && <ErrorState error={state.error} />}

        {state.status === 'ready' && state.data.length === 0 && (
          <EmptyState title={`No title matches “${query}”.`}>
            The seeded catalogue holds twelve titles, so most queries return nothing.
          </EmptyState>
        )}

        {state.status === 'ready' && state.data.length > 0 && (
          <>
            <SectionHead
              note={`${state.data.length} ${state.data.length === 1 ? 'match' : 'matches'} in ${Math.round(state.meta.ms)} ms`}
            >
              Results for &ldquo;{query}&rdquo;
            </SectionHead>
            <TitleList titles={state.data} />
          </>
        )}
      </div>
    </div>
  );
}
