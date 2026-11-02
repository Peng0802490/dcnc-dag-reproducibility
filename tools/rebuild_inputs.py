"""Reconstruct all three inputs and check them against the released experiment instances."""
import argparse
from pathlib import Path
from input_builders import (ROOT, CONSTRUCTION, read_json, write_json, verify_sources,
                            generate_roofnet, apply_capacities, apply_access_dynamics, convert_workflow)


def rebuild(output, check=False):
    output = Path(output).resolve()
    if output == ROOT or output.is_relative_to(ROOT / "inputs"):
        raise ValueError("Choose a generated-output directory outside inputs/")
    verify_sources()
    recipe = read_json(CONSTRUCTION / "roofnet_recipe.json")
    net = generate_roofnet(recipe)
    net = apply_capacities(net, recipe["capacity_seed"])
    net = apply_access_dynamics(net, read_json(ROOT / recipe["access_config"]), recipe["p_on"])
    generated = {recipe["output"]: net}
    for name, recipe in read_json(CONSTRUCTION / "workflow_recipes.json").items():
        generated[recipe["output"]] = convert_workflow(name)
    for rel, data in generated.items():
        if check and data != read_json(ROOT / "inputs" / rel):
            raise ValueError("Reconstructed input differs from the released instance: " + rel)
        write_json(output / rel, data)
    return list(generated)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / "results/rebuilt_inputs")
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    for name in rebuild(args.output, args.check):
        print(("Verified: " if args.check else "Written: ") + name)
