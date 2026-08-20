import { Link, useParams } from 'react-router-dom';
import { getCatalogueTitle, getMovie } from '../api.js';
import { useFetch } from '../useFetch.js';
import { EmptyState, ErrorState, SectionHead } from '../components/states.jsx';
import { DetailSkeleton } from '../components/Skeletons.jsx';

/**
 * movie-service holds records 1 to 10, catalog-service holds 12. A title only
 * the catalogue knows about is a real state, not an error, so it falls back
 * and says what is missing rather than showing a failure.
 */
async function loadTitle(id) {
  try {
    const { data, meta } = await getMovie(id);
    return { data: { kind: 'movie', movie: data }, meta };
  } catch (err) {
    if (err.status !== 404) throw err;
    const { data, meta } = await getCatalogueTitle(id);
    return { data: { kind: 'catalogue', title: data }, meta };
  }
}

function Reviews({ reviews }) {
  const mean = reviews.reduce((sum, r) => sum + r.rating, 0) / reviews.length;

  return (
    <section className="flex min-w-0 flex-col gap-3">
      <SectionHead note={`${mean.toFixed(1)} average of ${reviews.length}`}>
        Reviews
      </SectionHead>
      <ul className="divide-y divide-rule">
        {reviews.map((r) => (
          <li key={r.id} className="flex flex-col gap-1 py-3">
            <p className="text-[15px] leading-relaxed text-ink-soft">&ldquo;{r.comment}&rdquo;</p>
            <p className="text-[13px] text-ink-muted">
              {r.reviewer}, {r.rating} out of 5
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function TitleDetail() {
  const { id } = useParams();
  const state = useFetch(() => loadTitle(id), [id]);

  if (state.status === 'loading') return <DetailSkeleton />;

  if (state.status === 'error') {
    if (state.error.status === 404) {
      return (
        <div className="flex flex-col gap-3">
          <EmptyState title="No such title.">
            Neither movie-service nor catalog-service holds a record with id {id}.
          </EmptyState>
          <p className="text-[15px]">
            <Link to="/catalogue" className="text-accent hover:underline">
              Browse the catalogue
            </Link>
          </p>
        </div>
      );
    }
    return <ErrorState error={state.error} />;
  }

  const { data, meta } = state;
  const isMovie = data.kind === 'movie';
  const heading = isMovie ? data.movie.title : data.title.name;
  const year = isMovie ? data.movie.releaseYear : data.title.releaseYear;
  const actors = isMovie ? (data.movie.actors ?? []) : [];
  const reviews = isMovie ? (data.movie.reviews ?? []) : [];

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-ink-muted">
          {isMovie ? 'movie-service, with actor-service and review-service' : 'catalog-service'}
        </p>

        <h1 className="font-serif text-[2.4rem] leading-[1.14] font-semibold tracking-[-0.01em] text-ink text-balance">
          {heading}
        </h1>

        <p className="text-[15px] leading-relaxed text-ink-soft">
          {year}
          {!isMovie && <>. {data.title.genre}. Rated {data.title.rating.toFixed(1)}.</>}
        </p>
      </div>

      {isMovie ? (
        <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
          <section className="flex min-w-0 flex-col gap-3">
            <SectionHead note={`${actors.length} credited`}>Cast</SectionHead>
            {actors.length > 0 ? (
              <ul className="divide-y divide-rule">
                {actors.map((a) => (
                  <li key={a.id} className="py-2.5 text-[15px] text-ink">
                    {a.name}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-2.5 text-[15px] text-ink-muted">No cast recorded.</p>
            )}
          </section>

          {reviews.length > 0 ? (
            <Reviews reviews={reviews} />
          ) : (
            <EmptyState title="No reviews yet.">
              review-service holds no entries for this title.
            </EmptyState>
          )}
        </div>
      ) : (
        <EmptyState title="Held by the catalogue only.">
          movie-service has no record for this title, so there is no cast or review to show. Only
          the first ten titles carry one.
        </EmptyState>
      )}

      <p className="border-t border-rule pt-4 text-[13px] text-ink-muted">
        Returned in {Math.round(meta.ms)} ms.
      </p>
    </div>
  );
}
