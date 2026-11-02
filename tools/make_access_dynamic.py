"""Apply the original endpoint-incident wireless rule; adapted from the historical helper."""
import argparse
from input_builders import apply_access_dynamics, read_json, write_json

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--p-on", type=float, default=0.8)
    args = p.parse_args()
    write_json(args.output, apply_access_dynamics(read_json(args.input), read_json(args.config), args.p_on))
