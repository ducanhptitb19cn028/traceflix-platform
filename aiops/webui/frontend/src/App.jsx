import { NavLink, Route, Routes } from "react-router-dom";
import Home from "./pages/Home.jsx";
import OnlineMode from "./pages/OnlineMode.jsx";
import OfflineMode from "./pages/OfflineMode.jsx";
import ResultComparison from "./pages/ResultComparison.jsx";
import PipelineComparison from "./pages/PipelineComparison.jsx";

const links = [
  { to: "/", label: "Home", end: true },
  { to: "/online", label: "🟢 Online Mode" },
  { to: "/offline", label: "🔵 Offline Mode" },
  { to: "/pipelines", label: "🔀 Pipelines" },
  { to: "/comparison", label: "📊 Result Comparison" },
];

export default function App() {
  return (
    <div className="app">
      <header className="navbar">
        <div className="brand">📡 TraceFlix-AIOps</div>
        <nav>
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) => "navlink" + (isActive ? " active" : "")}
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/online" element={<OnlineMode />} />
          <Route path="/offline" element={<OfflineMode />} />
          <Route path="/pipelines" element={<PipelineComparison />} />
          <Route path="/comparison" element={<ResultComparison />} />
        </Routes>
      </main>
    </div>
  );
}
