import { Horse } from "./horse.model.js";
import { Jockey } from "./jockey.model.js";
import { Owner } from "./owner.model.js";
import { Trainer } from "./trainer.model.js";

export interface Ride {
  readonly ride_reference: {
    readonly id: number;
  },
  readonly cloth_number: number;
  readonly finish_position: number;
  readonly ride_status: string;
  readonly horse: Horse;
  readonly handicap: string;
  readonly official_rating?: string;
  readonly owner: Owner;
  readonly trainer: Trainer;
  readonly jockey: Jockey;
  readonly ride_description: string;
  readonly betting: Betting;
  readonly horse_lifetime_stats: HorseLifetimeStats[];
  readonly insights: {
    readonly type?: string;
  }[]
}

interface HorseLifetimeStats {
  readonly ride_id: number;
  readonly run_count: string;
  readonly win_count: string;
  readonly place_count: string;
}

interface Betting {
  readonly favourite: {
    readonly betting_favourite?: string;
  },
  readonly current_odds?: string;
  readonly historical_odds?: string[];
}
