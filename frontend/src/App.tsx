import { Link, NavLink, Route, Routes } from "react-router-dom";

import { useSnapshotInfo } from "./api";
import Home from "./pages/Home";
import RacePage from "./pages/RacePage";
import Scorecard from "./pages/Scorecard";

function Footer() {
  const { data } = useSnapshotInfo();
  const built = data ? new Date(data.built_at).toLocaleString("en-GB", { timeZone: "Europe/London" }) : null;
  return (
    <footer>
      <p>
        Race data from Sporting Life. Odds are for information only; this is a hobby project, not betting advice.
        {built && <> Data built {built} (UK time).</>}
      </p>
    </footer>
  );
}

export default function App() {
  return (
    <>
      <header>
        <Link to="/" className="brand">
          Data Jockey
        </Link>
        <nav>
          <NavLink to="/" end>
            Racing
          </NavLink>
          <NavLink to="/scorecard">Track record</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/races/:raceId" element={<RacePage />} />
          <Route path="/scorecard" element={<Scorecard />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
      <Footer />
    </>
  );
}
