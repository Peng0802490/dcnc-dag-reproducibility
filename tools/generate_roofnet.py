"""Generate the RoofNet-inspired geometric base graph (before experiment overlays)."""
import argparse
from input_builders import CONSTRUCTION, generate_roofnet, read_json, write_json

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    write_json(args.output, generate_roofnet(read_json(CONSTRUCTION / "roofnet_recipe.json")))
