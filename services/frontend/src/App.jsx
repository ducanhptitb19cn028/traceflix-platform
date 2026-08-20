import { NavLink, Route, Routes } from 'react-router-dom';
import { USERS } from './api.js';
import { useViewer } from './viewer.jsx';
import { NotFound } from './components/states.jsx';
import Home from './pages/Home.jsx';
import Search from './pages/Search.jsx';
import Catalogue from './pages/Catalogue.jsx';
import TitleDetail from './pages/TitleDetail.jsx';
import Profile from './pages/Profile.jsx';

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/catalogue', label: 'Catalogue' },
  { to: '/search', label: 'Search' },
  { to: '/profile', label: 'Profile' },
];

function Header() {
  const { viewerId, setViewerId } = useViewer();

  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex max-w-[68rem] flex-wrap items-center gap-x-8 gap-y-3 px-6 py-3">
        <NavLink to="/" className="text-[15px] font-semibold tracking-tight text-ink">
          TraceFlix
        </NavLink>

        <nav aria-label="Main">
          <ul className="flex items-center gap-5">
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `text-[14px] ${
                      isActive
                        ? 'font-medium text-ink underline underline-offset-[6px]'
                        : 'text-ink-muted hover:text-accent'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <label htmlFor="tf-viewer" className="text-[13px] text-ink-muted">
            Viewing as
          </label>
          <select
            id="tf-viewer"
            value={viewerId}
            onChange={(e) => setViewerId(Number(e.target.value))}
            className="rounded-control border border-rule-strong bg-paper px-2 py-1 text-[14px] text-ink"
          >
            {USERS.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}, {u.tier}
              </option>
            ))}
          </select>
        </div>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <div className="min-h-[100dvh]">
      <Header />
      <main className="mx-auto max-w-[68rem] px-6 py-10">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/catalogue" element={<Catalogue />} />
          <Route path="/search" element={<Search />} />
          <Route path="/title/:id" element={<TitleDetail />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}
