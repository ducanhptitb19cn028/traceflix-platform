import { Link } from 'react-router-dom';

/** Something went wrong at a service. Says which, and what to do. */
export function ErrorState({ error, hint }) {
  return (
    <div role="alert" className="flex flex-col gap-2 border-l-2 border-fault pl-4">
      <p className="text-[15px] font-medium text-fault">This page could not be built.</p>
      <p className="max-w-[62ch] text-[15px] leading-relaxed text-ink-soft">{error.message}</p>
      <p className="text-[13px] text-ink-muted">
        {hint ?? 'Restart the service that stopped, then reload.'}
      </p>
    </div>
  );
}

/** Nothing to show, and it is not an error. */
export function EmptyState({ title, children }) {
  return (
    <div className="flex flex-col gap-1.5 border-l-2 border-rule-strong pl-4">
      <p className="text-[15px] font-medium text-ink">{title}</p>
      {children && (
        <p className="max-w-[62ch] text-[15px] leading-relaxed text-ink-soft">{children}</p>
      )}
    </div>
  );
}

export function NotFound() {
  return (
    <div className="flex flex-col gap-3">
      <h1 className="font-serif text-[2rem] leading-tight font-semibold text-ink">
        There is nothing at this address.
      </h1>
      <p className="max-w-[62ch] text-[15px] leading-relaxed text-ink-soft">
        The page you asked for is not part of this application.
      </p>
      <p className="text-[15px]">
        <Link to="/" className="text-accent hover:underline">
          Back to the home page
        </Link>
      </p>
    </div>
  );
}

/** Section heading with an optional note on the right. */
export function SectionHead({ children, note }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-rule-strong pb-2">
      <h2 className="text-[15px] font-semibold text-ink">{children}</h2>
      {note && <p className="text-[13px] text-ink-muted">{note}</p>}
    </div>
  );
}
