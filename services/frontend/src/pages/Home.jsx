import { Link } from 'react-router-dom';
import { getHome } from '../api.js';
import { useFetch } from '../useFetch.js';
import { useViewer } from '../viewer.jsx';
import TitleList from '../components/TitleList.jsx';
import { ErrorState, SectionHead } from '../components/states.jsx';
import { HomeSkeleton } from '../components/Skeletons.jsx';

function Featured({ featured }) {
  const actors = featured.actors ?? [];
  const reviews = featured.reviews ?? [];

  return (
    <section className="grid gap-x-12 gap-y-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col gap-3">
        <p className="text-[13px] text-ink-muted">Featured this week</p>

        <h1 className="font-serif text-[2.6rem] leading-[1.12] font-semibold tracking-[-0.01em] text-ink text-balance">
          <Link to={`/title/${featured.id}`} className="hover:text-accent">
            {featured.title}
          </Link>
        </h1>

        <p className="text-[15px] leading-relaxed text-ink-soft">
          {featured.releaseYear}
          {actors.length > 0 && <>. Starring {actors.map((a) => a.name).join(' and ')}.</>}
        </p>
      </div>

      {reviews.length > 0 && (
        <ul className="flex flex-col gap-4 border-t border-rule pt-4 lg:border-t-0 lg:pt-0">
          {reviews.map((r) => (
            <li key={r.id} className="flex flex-col gap-1">
              <p className="text-[15px] leading-relaxed text-ink-soft">&ldquo;{r.comment}&rdquo;</p>
              <p className="text-[13px] text-ink-muted">
                {r.reviewer}, {r.rating} out of 5
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function Home() {
  const { viewerId, viewer } = useViewer();
  const state = useFetch(() => getHome(viewerId), [viewerId]);

  if (state.status === 'loading') return <HomeSkeleton />;
  if (state.status === 'error') return <ErrorState error={state.error} />;

  const { data, meta } = state;
  const recommendations = data.user?.recommendations ?? [];
  const trending = data.trending ?? [];

  return (
    <div className="flex flex-col gap-12">
      {data.featured && <Featured featured={data.featured} />}

      <div className="grid gap-x-12 gap-y-10 border-t border-rule pt-10 lg:grid-cols-2">
        <section className="flex min-w-0 flex-col gap-3">
          <SectionHead note={`For ${viewer.name}`}>Recommended for you</SectionHead>
          <TitleList titles={recommendations} ranked />
        </section>

        <section className="flex min-w-0 flex-col gap-3">
          <SectionHead note="Across all viewers">Trending now</SectionHead>
          <TitleList titles={trending} ranked />
        </section>
      </div>

      <p className="border-t border-rule pt-4 text-[13px] text-ink-muted">
        Composed by nine services in {Math.round(meta.ms)} ms, {(meta.bytes / 1024).toFixed(1)} kB
        returned.
      </p>
    </div>
  );
}
