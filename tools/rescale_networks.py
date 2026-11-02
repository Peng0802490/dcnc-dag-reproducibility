"""Apply the original seeded capacity rule; adapted from the historical helper."""
import argparse
from input_builders import apply_capacities, read_json, write_json

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=20260719)
    args = p.parse_args()
    write_json(args.output, apply_capacities(read_json(args.input), args.seed))
