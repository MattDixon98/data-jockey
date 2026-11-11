import { Result } from "./race-result.model.js";

export interface Horse {
  readonly horse_reference: {
    readonly id: number;
  },
  readonly name: string;
  readonly slug: string;
  readonly last_ran_days?: string;
  readonly age: number;
  readonly foaled: string;
  readonly sex: {
    readonly type: string;
  }
  readonly previous_results: Result[];
}