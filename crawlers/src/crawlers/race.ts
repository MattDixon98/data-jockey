import type { RaceResponse } from "../models/race-response.model.js";

export const fetchRace = async (raceId: number): Promise<RaceResponse> => {
  const url = `https://www.sportinglife.com/api/horse-racing/race/${raceId}`;

  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      "User-Agent": "data-jockey/0.1"
    }
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
};