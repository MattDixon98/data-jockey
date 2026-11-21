import { useQuery } from "@tanstack/react-query";

import type { Meeting, Pick, RaceDetail, ScorecardRow, SnapshotInfo } from "./types";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1/${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const useMeetings = (date: string) =>
  useQuery({ queryKey: ["meetings", date], queryFn: () => get<Meeting[]>(`meetings/?date=${date}`) });

export const useUndervalued = (date: string) =>
  useQuery({ queryKey: ["undervalued", date], queryFn: () => get<Pick[]>(`undervalued/?date=${date}`) });

export const useRace = (raceId: string) =>
  useQuery({ queryKey: ["race", raceId], queryFn: () => get<RaceDetail>(`races/${raceId}/`) });

export const useScorecard = () =>
  useQuery({ queryKey: ["scorecard"], queryFn: () => get<ScorecardRow[]>("scorecard/") });

/** One row per race day and race group, for one view (after_race or site_pick). */
export const useDailyScorecard = (view: string) =>
  useQuery({
    queryKey: ["scorecard", "day", view],
    queryFn: () => get<ScorecardRow[]>(`scorecard/?view=${view}&period_type=day`),
  });

export const useSnapshotInfo = () =>
  useQuery({ queryKey: ["snapshot"], queryFn: () => get<SnapshotInfo>("snapshot/") });
