from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT_ROOT = ROOT / "inputs"
CONFIG_ROOT = INPUT_ROOT / "configs"


def resolve_config_path(config_name: str | Path) -> Path:
    """Resolve explicit, bundled, and pre-v0.1.1 configuration paths."""
    candidate = Path(config_name)
    if candidate.is_file():
        return candidate.resolve()
    anchored = candidate if candidate.is_absolute() else ROOT / candidate
    if anchored.is_file():
        return anchored.resolve()
    try:
        relative = anchored.relative_to(ROOT)
    except ValueError:
        return anchored.resolve()
    if len(relative.parts) == 1 or (
        len(relative.parts) == 2 and relative.parts[0] == "legacy_inputs"
    ):
        return (CONFIG_ROOT / relative.name).resolve()
    return anchored.resolve()
