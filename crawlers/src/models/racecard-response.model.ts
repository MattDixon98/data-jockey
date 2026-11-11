import { Course } from "./course.model.js";

export type RacecardResponse = Meeting[];

export interface Meeting {
  readonly meeting_summary: {
    readonly meeting_reference: {
      readonly id: number;
    },
    readonly date: string;
    readonly status: string;
    readonly course: Course;
    readonly going: string;
    readonly surface_summary: string;
    readonly visible: boolean;
    readonly weather: string;
  },
  readonly races: RacecardRace[];
}

export interface RacecardRace {
  readonly meeting_summary_reference: {
    readonly id: number;
  },
  readonly race_summary_reference: {
    readonly id: number;
  },
  readonly name: string;
  readonly course_name: string;
  readonly course_shortcode: string;
  readonly course_surface: {
      readonly surface: string;
  },
  readonly age: string;
  readonly race_class: string;
  readonly distance: string;
  readonly date: string;
  readonly time: string;
  readonly off_time: string;
  readonly winning_time: string;
  readonly ride_count: number;
  readonly race_stage: string;
  readonly has_video: boolean;
  readonly going: string;
  readonly going_shortcode: string;
  readonly has_handicap: boolean;
  readonly verdict: string;
  readonly hidden: boolean;
}

