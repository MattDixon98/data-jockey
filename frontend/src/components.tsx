import { Link } from "react-router-dom";

import { percent, signedPercent } from "./format";
import type { Runner } from "./types";

export function Status({ query, children }: { query: { isLoading: boolean; error: Error | null }; children: React.ReactNode }) {
  if (query.isLoading) return <p className="muted">Loading…</p>;
  if (query.error) return <p className="error">Couldn't load this: {query.error.message}</p>;
  return <>{children}</>;
}

export function ValueBadge({ runner }: { runner: Runner }) {
  const value = runner.model_value;
  if (!value?.undervalued) return null;
  // Experimental: the picks haven't beaten the market yet (see the Track record page).
  const title = "Our model rates this horse's chance above the market's. Experimental: see Track record.";
  return (
    <span className="badge" title={title}>
      🔥 Undervalued {signedPercent(value.edge)}
    </span>
  );
}

/** Our price and chance for a runner, or a dash if it isn't priced. */
export function OurOdds({ runner }: { runner: Runner }) {
  const odds = runner.model_odds;
  if (!odds) return <span className="muted">–</span>;
  return (
    <span title={`${percent(odds.model_prob, 1)} chance`}>
      {odds.model_odds ?? "–"}
      {odds.in_sample && <sup title="Trained on this race, so not a fair test"> *</sup>}
    </span>
  );
}

export const RaceLink = ({ id, children }: { id: number; children: React.ReactNode }) => (
  <Link to={`/races/${id}`}>{children}</Link>
);
