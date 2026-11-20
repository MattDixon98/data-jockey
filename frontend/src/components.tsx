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

/**
 * The market favourite(s) of a race, by ride id. Once a race has run the
 * source marks the SP favourite (joint and co-favourites too); before that it's
 * the shortest price on the card, ties all counting. Non-runners never are.
 */
export function marketFavourites(runners: Runner[]): Set<number> {
  const running = runners.filter((runner) => runner.status === "RUNNER");
  const marked = running.filter((runner) => runner.favourite);
  if (marked.length) return new Set(marked.map((runner) => runner.ride_id));
  const prices = running.map((runner) => runner.odds_decimal).filter((price): price is number => price !== null);
  if (!prices.length) return new Set();
  const shortest = Math.min(...prices);
  return new Set(running.filter((runner) => runner.odds_decimal === shortest).map((runner) => runner.ride_id));
}

export const FavouriteBadge = () => (
  <span className="badge favourite" title="The market's favourite: the shortest price in the race">
    ❤️ Favourite
  </span>
);

/** Our model's favourite: the runner it rates most likely to win (rank 1). */
export const isOurFavourite = (runner: Runner): boolean => runner.model_odds?.model_rank === 1;

export const OurFavouriteBadge = () => (
  <span className="badge ours" title="Our favourite: the horse our model rates most likely to win">
    ⭐ Our favourite
  </span>
);

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
