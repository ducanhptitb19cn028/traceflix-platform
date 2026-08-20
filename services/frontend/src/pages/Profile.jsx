import { getAccount, getUser } from '../api.js';
import { useFetch } from '../useFetch.js';
import { useViewer } from '../viewer.jsx';
import TitleList from '../components/TitleList.jsx';
import { EmptyState, ErrorState, SectionHead } from '../components/states.jsx';
import { ListSkeleton } from '../components/Skeletons.jsx';

/** user-service composes the profile; auth-service is asked separately so the
 *  page shows what each of the two actually contributes. */
async function loadProfile(id) {
  const [profile, account] = await Promise.all([getUser(id), getAccount(id)]);
  return {
    data: { user: profile.data, account: account.data },
    meta: { ms: profile.meta.ms + account.meta.ms, bytes: profile.meta.bytes + account.meta.bytes },
  };
}

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)] gap-4 py-2.5">
      <dt className="text-[13px] text-ink-muted">{label}</dt>
      <dd className="min-w-0 text-[15px] text-ink">{children}</dd>
    </div>
  );
}

export default function Profile() {
  const { viewerId } = useViewer();
  const state = useFetch(() => loadProfile(viewerId), [viewerId]);

  if (state.status === 'loading') return <ListSkeleton rows={4} />;
  if (state.status === 'error') return <ErrorState error={state.error} />;

  const { user, account } = state.data;
  const recommendations = user.recommendations ?? [];

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-ink-muted">user-service, with auth-service</p>
        <h1 className="font-serif text-[2.2rem] leading-tight font-semibold text-ink">
          {user.name}
        </h1>
      </div>

      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
        <section className="flex min-w-0 flex-col gap-3">
          <SectionHead note="Two services">Account</SectionHead>
          <dl className="divide-y divide-rule">
            <Field label="Email">{user.email}</Field>
            <Field label="Tier">{user.tier}</Field>
            <Field label="Username">{account.username}</Field>
            <Field label="Role">{account.role}</Field>
          </dl>
          <p className="text-[13px] text-ink-muted">
            Name, email and tier come from user-service. Username and role are what auth-service
            returns for the same id.
          </p>
        </section>

        <section className="flex min-w-0 flex-col gap-3">
          <SectionHead note={`${recommendations.length} titles`}>Recommended for you</SectionHead>
          {recommendations.length > 0 ? (
            <TitleList titles={recommendations} ranked />
          ) : (
            <EmptyState title="Nothing recommended yet.">
              recommendation-service returned no titles for this profile.
            </EmptyState>
          )}
        </section>
      </div>

      <p className="border-t border-rule pt-4 text-[13px] text-ink-muted">
        Two calls, {Math.round(state.meta.ms)} ms combined.
      </p>
    </div>
  );
}
