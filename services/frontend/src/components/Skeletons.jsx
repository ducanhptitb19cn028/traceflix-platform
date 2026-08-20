/**
 * Loading states mirror the shape of what replaces them, so the page does not
 * shift when a service answers.
 */
function Bar({ className = '' }) {
  return <div className={`rounded-control bg-tint ${className}`} />;
}

export function ListSkeleton({ rows = 5, heading = true }) {
  return (
    <section className="flex min-w-0 flex-col gap-3" aria-hidden="true">
      {heading && (
        <div className="border-b border-rule-strong pb-2">
          <Bar className="h-4 w-44" />
        </div>
      )}
      <ul className="divide-y divide-rule">
        {Array.from({ length: rows }, (_, i) => (
          <li key={i} className="flex items-center justify-between gap-4 py-3">
            <Bar className="h-4 w-2/3" />
            <Bar className="h-4 w-8" />
          </li>
        ))}
      </ul>
    </section>
  );
}

export function HomeSkeleton() {
  return (
    <div className="flex flex-col gap-12" aria-hidden="true">
      <div className="grid gap-x-12 gap-y-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          <Bar className="h-3.5 w-32" />
          <Bar className="h-11 w-4/5" />
          <Bar className="h-4 w-3/5" />
        </div>
        <div className="flex flex-col gap-4">
          <Bar className="h-12 w-full" />
          <Bar className="h-12 w-full" />
        </div>
      </div>
      <div className="grid gap-x-12 gap-y-10 border-t border-rule pt-10 lg:grid-cols-2">
        <ListSkeleton />
        <ListSkeleton />
      </div>
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-8" aria-hidden="true">
      <div className="flex flex-col gap-3">
        <Bar className="h-3.5 w-24" />
        <Bar className="h-12 w-3/5" />
        <Bar className="h-4 w-2/5" />
      </div>
      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
        <ListSkeleton rows={2} />
        <ListSkeleton rows={2} />
      </div>
    </div>
  );
}
