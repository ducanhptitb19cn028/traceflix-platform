import { NavLink, Route, Routes } from "react-router-dom";
import Home from "./pages/Home.jsx";
import OnlineMode from "./pages/OnlineMode.jsx";
import OfflineMode from "./pages/OfflineMode.jsx";
import ResultComparison from "./pages/ResultComparison.jsx";
import PipelineComparison from "./pages/PipelineComparison.jsx";
import Streaming from "./pages/Streaming.jsx";
import LiveML from "./pages/LiveML.jsx";
import LiveLLM from "./pages/LiveLLM.jsx";
import LiveCluster from "./pages/LiveCluster.jsx";
import Melt from "./pages/Melt.jsx";

const links = [
  { to: "/", label: "Home", end: true },
  { to: "/online", label: "🟢 Online Mode" },
  { to: "/offline", label: "🔵 Offline Mode" },
  { to: "/live/ml", label: "🧠 Live ML" },
  { to: "/live/llm", label: "🤖 Live LLM" },
  { to: "/live/cluster", label: "🛰 Live Cluster" },
  { to: "/melt", label: "🔭 MELT" },
  { to: "/streaming", label: "🌊 Live Kafka + LLM" },
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
          <Route path="/live/ml" element={<LiveML />} />
          <Route path="/live/llm" element={<LiveLLM />} />
          <Route path="/live/cluster" element={<LiveCluster />} />
          <Route path="/melt" element={<Melt />} />
          <Route path="/streaming" element={<Streaming />} />
          <Route path="/pipelines" element={<PipelineComparison />} />
          <Route path="/comparison" element={<ResultComparison />} />
        </Routes>
      </main>
    </div>
  );
}
