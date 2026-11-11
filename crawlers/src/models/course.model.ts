export interface Course {
  readonly course_reference: {
    readonly id: number;
  },
  readonly name: string;
  readonly country: {
    readonly country_reference: {
      readonly id: number;
    },
    readonly short_name: string;
    readonly long_name: string;
  },
  readonly feed_source: string;
}
