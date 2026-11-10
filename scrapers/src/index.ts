import { fetchRacecard } from "./scrapers/racecards.js";
import { fetchRace } from "./scrapers/race.js";

const yesterday = new Date();
yesterday.setDate(yesterday.getDate() - 1);

const searchDate = yesterday
  .toISOString()
  .split('T')[0];

const raceCard = await fetchRacecard(searchDate);
const race = await fetchRace("searchDate"); // To implement: Need to loop over the raceCard results and get `race_summary_reference.id`
