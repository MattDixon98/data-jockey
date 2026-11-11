export interface Result {
  readonly race_id: string;
  readonly date: string;
  readonly time: string;
  readonly course_name: string;
  readonly course_shortcode: string;
  readonly distance: string;
  readonly run_type: string;
  readonly weight: string;
  readonly position: number;
  readonly runner_count: number;
  readonly bha: number;
  readonly race_class: string;
  readonly race_name: string;
  readonly going: string;
  readonly going_shortcode: string;
  readonly odds: string;
  readonly ride_description: string;
}