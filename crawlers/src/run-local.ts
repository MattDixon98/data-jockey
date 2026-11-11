import { crawlDay, ukDate } from "./crawl-day.js";

// Usage: npm run dev [YYYY-MM-DD]   (defaults to yesterday)
const date = process.argv[2] ?? ukDate(-1);

if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
  console.error(`Invalid date "${date}", expected YYYY-MM-DD`);
  process.exit(1);
}

await crawlDay(date);
