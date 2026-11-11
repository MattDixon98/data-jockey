import { Prize } from "./prize.model.js";
import { Ride } from "./race-ride.model.js";

export interface RaceResponse {
  readonly race_summary: {
    readonly meeting_summary_reference: {
      readonly id: number;
    },
    readonly race_summary_reference: {
      readonly id: number;
    },
    readonly name: string;
    readonly race_class: string;
    readonly distance: string;
    readonly date: string;
    readonly time: string;
    readonly off_time?: string;
    readonly winning_time?: string;
    readonly ride_count: number;
    readonly going: string;
    readonly going_shortcode: string;
    readonly verdict?: string;
  }
  readonly prizes: {
    readonly prize: Prize[];
  },
  readonly betting_forecast: string;
  readonly rides: Ride[];
  readonly tote_win?: string;
  readonly place_win?: string;
  readonly exacta_win?: string;
  readonly trifecta?: string;
  readonly stewards?: string;
}