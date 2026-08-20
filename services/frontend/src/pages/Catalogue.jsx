import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCatalogue } from '../api.js';
import { useFetch } from '../useFetch.js';
import { ErrorState } from '../components/states.jsx';
import { ListSkeleton } from '../components/Skeletons.jsx';

const COLUMNS = [
  { key: 'name', label: 'Title', align: 'left' },
  { key: 'genre', label: 'Genre', align: 'left' },
  { key: 'releaseYear', label: 'Year', align: 'right' },
  { key: 'rating', label: 'Rating', align: 'right' },
];

export default function Catalogue() {
  const state = useFetch(() => getCatalogue(), []);
  const [sort, setSort] = useState({ key: 'rating', desc: true });

  const rows = useMemo(() => {
    if (state.status !== 'ready') return [];
    const copy = [...state.data];
    copy.sort((a, b) => {
      const x = a[sort.key];
      const y = b[sort.key];
      const cmp = typeof x === 'string' ? x.localeCompare(y) : x - y;
      return sort.desc ? -cmp : cmp;
    });
    return copy;
  }, [state, sort]);

  function toggle(key) {
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== 'name' }));
  }

  if (state.status === 'loading') return <ListSkeleton rows={8} />;
  if (state.status === 'error') return <ErrorState error={state.error} />;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-[15px] font-semibold text-ink">The catalogue</h1>
        <p className="text-[13px] text-ink-muted">
          All {state.data.length} titles held by catalog-service, the shared leaf that both
          search-service and recommendation-service read.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[15px]">
          <caption className="sr-only">
            Catalogue titles, sortable by title, genre, year or rating.
          </caption>
          <thead>
            <tr className="border-b border-rule-strong">
              {COLUMNS.map((c) => {
                const active = sort.key === c.key;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : 'none'}
                    className={`pb-2 font-semibold ${c.align === 'right' ? 'text-right' : 'text-left'}`}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(c.key)}
                      className={`text-[13px] ${active ? 'text-ink' : 'text-ink-muted'} hover:text-accent`}
                    >
                      {c.label}
                      {active && <span aria-hidden="true">{sort.desc ? ' ↓' : ' ↑'}</span>}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {rows.map((t) => (
              <tr key={t.id}>
                <td className="py-2.5 pr-4">
                  <Link to={`/title/${t.id}`} className="text-ink hover:text-accent hover:underline">
                    {t.name}
                  </Link>
                </td>
                <td className="py-2.5 pr-4 text-ink-muted">{t.genre}</td>
                <td className="py-2.5 pr-4 text-right tabular-nums text-ink-muted">
                  {t.releaseYear}
                </td>
                <td className="py-2.5 text-right font-medium tabular-nums text-ink">
                  {t.rating.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[13px] text-ink-muted">Returned in {Math.round(state.meta.ms)} ms.</p>
    </div>
  );
}
