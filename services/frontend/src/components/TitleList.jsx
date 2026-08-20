import { Link } from 'react-router-dom';

/**
 * A listing of titles. `ranked` numbers the rows, which is only honest where
 * the service returned an ordered set (recommendations, trending). Search
 * results and the full catalogue are not ranked, so they are not numbered.
 *
 * catalog-service stores no artwork, so this is a list rather than a grid of
 * covers, and nothing is invented to fill the gap.
 */
export default function TitleList({ titles, ranked = false }) {
  return (
    <ol className="divide-y divide-rule">
      {titles.map((t, i) => (
        <li
          key={t.id}
          className={`grid items-baseline gap-x-4 py-2.5 ${
            ranked
              ? 'grid-cols-[1.5rem_minmax(0,1fr)_auto]'
              : 'grid-cols-[minmax(0,1fr)_auto]'
          }`}
        >
          {ranked && <span className="text-[13px] tabular-nums text-ink-muted">{i + 1}</span>}

          <span className="min-w-0">
            <Link to={`/title/${t.id}`} className="text-[15px] text-ink hover:text-accent hover:underline">
              {t.name}
            </Link>
            <span className="ml-2 text-[13px] text-ink-muted">
              {t.genre}, {t.releaseYear}
            </span>
          </span>

          <span className="text-[15px] font-medium tabular-nums text-ink">
            {t.rating?.toFixed(1) ?? ''}
          </span>
        </li>
      ))}
    </ol>
  );
}
