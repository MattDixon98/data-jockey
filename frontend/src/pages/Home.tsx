import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useMeetings, useUndervalued } from "../api";
import { isOurFavourite, OurOdds, RaceLink, Status, ValueBadge } from "../components";
import { addDays, longDate, ordinal, raceTypeLabel, todayUk } from "../format";
import { type SortKeys, useSortable } from "../sort";
import type { Meeting, Pick } from "../types";

const PAGE_SIZE = 10;

/** How far our chance is above the market's, in percentage points. Ranking by
 * the API's `edge` (relative: ours / market's - 1) puts 100/1 outsiders first. */
const gap = (pick: Pick): number => (pick.model_value?.model_prob ?? 0) - (pick.model_value?.market_prob ?? 0);

const PICK_SORT: SortKeys<Pick> = {
  race: (pick) => pick.race.race_time,
  horse: (pick) => pick.horse.name,
  undervalued: (pick) => pick.model_value?.edge,
  market: (pick) => pick.model_value?.market_odds_decimal,
  ours: (pick) => pick.model_odds?.model_odds_decimal,
};

/** Undervalued and our favourite: the horse we rate most likely to win its race. */
const isOurPick = (pick: Pick): boolean => isOurFavourite(pick);

interface PicksTableProps {
  date: string;
  title: string;
  description: React.ReactNode;
  empty: string;
  include?: (pick: Pick) => boolean;
}

/** A day's undervalued runners (all of them, or those `include` keeps), a page
 * at a time: biggest gap between our chance and the market's first, unless a
 * column header says otherwise (a sort covers the whole day, not just the page).
 * Both tables share one /undervalued/ request (same query key). */
function PicksTable({ date, title, description, empty, include }: PicksTableProps) {
  const query = useUndervalued(date);
  const [page, setPage] = useState(0);
  const kept = include ? (query.data ?? []).filter(include) : (query.data ?? []);
  const ranked = [...kept].sort((a, b) => gap(b) - gap(a));
  const { rows: all, header } = useSortable(ranked, PICK_SORT, () => setPage(0));
  const first = page * PAGE_SIZE;
  const picks = all.slice(first, first + PAGE_SIZE);
  const pages = Math.ceil(all.length / PAGE_SIZE);

  return (
    <section className="panel">
      <h2>
        {title} <span className="tag">experimental</span>
      </h2>
      <p className="muted small">
        {description} So far these <Link to="/scorecard">haven't beaten the market</Link>.
      </p>
      <Status query={query}>
        {picks.length ? (
          <table>
            <thead>
              <tr>
                {header("race", "Race")}
                {header("horse", "Horse")}
                {header("undervalued", "Undervalued")}
                {header("market", "Market", "num")}
                {header("ours", "Ours", "num")}
              </tr>
            </thead>
            <tbody>
              {picks.map((pick: Pick) => (
                <tr key={pick.ride_id}>
                  <td>
                    <RaceLink id={pick.race.race_id}>
                      {pick.race.race_time} {pick.race.course?.name}
                    </RaceLink>
                  </td>
                  <td>
                    {pick.horse.name}
                    {pick.finish_position && <div className="muted small">Finished {ordinal(pick.finish_position)}</div>}
                  </td>
                  <td>
                    <ValueBadge runner={pick} />
                  </td>
                  <td className="num">{pick.model_value?.market_odds ?? "–"}</td>
                  <td className="num">
                    <OurOdds runner={pick} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>{empty}</p>
        )}
        {pages > 1 && (
          <div className="pager">
            <button type="button" onClick={() => setPage(page - 1)} disabled={page === 0}>
              ← Previous
            </button>
            <span className="muted small">
              {first + 1}–{first + picks.length} of {all.length}
            </span>
            <button type="button" onClick={() => setPage(page + 1)} disabled={page >= pages - 1}>
              Next →
            </button>
          </div>
        )}
      </Status>
    </section>
  );
}

function MeetingCard({ meeting }: { meeting: Meeting }) {
  return (
    <section className="panel">
      <h2>{meeting.course?.name}</h2>
      <p className="muted">
        {[meeting.going, meeting.surface_summary].filter(Boolean).join(" · ")}
      </p>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Race</th>
            <th>Our pick</th>
            <th className="num">Runners</th>
          </tr>
        </thead>
        <tbody>
          {meeting.races.map((race) => {
            const top = race.runners.find((runner) => runner.model_odds?.model_rank === 1);
            const winner = race.runners.find((runner) => runner.finish_position === 1);
            return (
              <tr key={race.race_id}>
                <td>{race.race_time}</td>
                <td>
                  <RaceLink id={race.race_id}>{race.name}</RaceLink>
                  <div className="muted small">
                    {[raceTypeLabel(race.race_type), race.distance].filter(Boolean).join(" · ")}
                  </div>
                </td>
                <td>
                  {top ? (
                    <>
                      {top.horse.name} (<OurOdds runner={top} />)
                    </>
                  ) : (
                    <span className="muted">–</span>
                  )}
                  {winner && <div className="muted small">Won: {winner.horse.name}</div>}
                </td>
                <td className="num">{race.runners.length}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

export default function Home() {
  const [params, setParams] = useSearchParams();
  const today = todayUk();
  const date = params.get("date") ?? today;
  const meetings = useMeetings(date);
  // Changing day drops the course filter: that course may not race on the new day.
  const go = (to: string) => setParams(to === today ? {} : { date: to });

  // One course at a time. The choice lives in the URL (?course=Ascot) so it
  // survives a refresh and the back button; with none chosen, or one not racing
  // that day, it's the first course in the list.
  const courses = (meetings.data ?? []).map((meeting) => meeting.course?.name ?? "").filter(Boolean);
  const wanted = params.get("course");
  const course = wanted && courses.includes(wanted) ? wanted : courses[0];
  const shown = (meetings.data ?? []).filter((meeting) => meeting.course?.name === course);
  const pickCourse = (name: string) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("course", name);
      return next;
    });

  return (
    <>
      <div className="daybar">
        <button onClick={() => go(addDays(date, -1))} aria-label="Previous day">
          ←
        </button>
        <h1>{longDate(date)}</h1>
        <div className="daybar-end">
          {date !== today && <button onClick={() => go(today)}>Today</button>}
          <button onClick={() => go(addDays(date, 1))} aria-label="Next day">
            →
          </button>
        </div>
      </div>
      {/* Keyed by date so a new day starts back on page 1. */}
      <PicksTable
        key={`picks-${date}`}
        date={date}
        title="Our Top Picks"
        description="Undervalued horses we also rate most likely to win their race."
        empty="No picks on this day."
        include={isOurPick}
      />
      <Status query={meetings}>
        {meetings.data?.length ? (
          <>
            <label className="course-filter">
              Course{" "}
              <select value={course} onChange={(event) => pickCourse(event.target.value)}>
                {courses.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            {shown.map((meeting) => (
              <MeetingCard key={meeting.meeting_id} meeting={meeting} />
            ))}
          </>
        ) : (
          <p>No UK or Irish racing on this day.</p>
        )}
      </Status>
    </>
  );
}
