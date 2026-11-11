import { crawlDay, ukDate } from "./crawl-day.js";

// AWS Lambda entry point. Each scheduled run crawls one date:
//   {"offset": -1}  yesterday → past/      {"offset": 0}  today → today/
//   {"offset": 1..3} upcoming → future/    {"date": "YYYY-MM-DD"} a specific date (backfill)
// Whether a date is past/today/future is worked out from the date itself.
export const handler = async (event: { date?: string; offset?: number } = {}) => {
  return crawlDay(event.date ?? ukDate(event.offset ?? -1));
};
