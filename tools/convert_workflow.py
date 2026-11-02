"""Convert a public workflow structure using the explicit released parameter/adaptation tables."""
import argparse
from input_builders import convert_workflow, verify_sources, write_json

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workflow", choices=["srasearch22", "sipht31"], required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--public-structure", action="store_true",
                   help="Export public nodes/edges only, without service-graph adaptations or workloads.")
    args = p.parse_args()
    verify_sources()
    write_json(args.output, convert_workflow(args.workflow, args.public_structure))
