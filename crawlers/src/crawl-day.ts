import { fetchRacecard } from "./crawlers/racecards.js";
import { fetchRace } from "./crawlers/race.js";
import { generateS3FileName, saveJsonToS3, type EventPhase } from "./utilities/s3-storage.js";

// Pause between race requests so we don't hammer the source site.
const DELAY_MS = 500;
const DAY_MS = 24 * 60 * 60 * 1000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export interface CrawlSummary {
  date: string;
  phase: EventPhase;
  meetings: number;
  racesSaved: number;
  racesFailed: number[];
}

export const ukDate = (offsetDays = 0): string => {
  const date = new Date(Date.now() + offsetDays * DAY_MS);
  return date.toLocaleDateString("en-CA", { timeZone: "Europe/London" });
};

const daysFromToday = (date: string): number => {
  const targetMs = Date.parse(date);
  const todayMs = Date.parse(ukDate(0));
  const differenceMs = targetMs - todayMs;

  return Math.round(differenceMs / DAY_MS);
};

export const crawlDay = async (date: string): Promise<CrawlSummary> => {
  const daysAhead = daysFromToday(date);
  const phase: EventPhase = daysAhead < 0 ? "past" : daysAhead === 0 ? "today" : "future";

  const meetings = await fetchRacecard(date);
  const racecardFileName = generateS3FileName(phase, "racecards", date, "racecards", daysAhead);
  await saveJsonToS3(racecardFileName, meetings);

  const raceIds = meetings.flatMap((meeting) =>
    meeting.races.map((race) => race.race_summary_reference.id)
  );
  console.log(`${date} (${phase}): ${meetings.length} meetings, ${raceIds.length} races`);

  const failed: number[] = [];
  for (const raceId of raceIds) {
    try {
      const race = await fetchRace(raceId);
      const raceFileName = generateS3FileName(phase, "races", date, String(raceId), daysAhead);
      await saveJsonToS3(raceFileName, race);
    } catch (err) {
      console.error(`Race ${raceId} failed:`, err);
      failed.push(raceId);
    }
    await sleep(DELAY_MS);
  }

  const summary = {
    date,
    phase,
    meetings: meetings.length,
    racesSaved: raceIds.length - failed.length,
    racesFailed: failed
  };
  console.log("Done:", summary);
  return summary;
};
