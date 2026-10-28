"""Counts how much of the bill the infrastructure definition can represent.

The cost model tags every priced line with the quantities its formula consumed.
This module parses the generated Terraform back with python-hcl2 and asks, for
each consumed quantity, whether anything in any file encodes it: an attribute
carrying it, a variable that exists to receive it, or a named price. The
quantities with no home anywhere are the missing cost lines, and their count is
the repository's answer to "the plan looks complete, what is the problem".

The mapping below is explicit and reviewable on purpose. A fuzzy text match
would inflate coverage by crediting a comment; an attribute path either exists
in the parsed tree or it does not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import hcl2

from ..config import TERRAFORM_DIR
from ..costmodel.costing import QUANTITIES


class TerraformError(ValueError):
    """Generated Terraform that cannot be parsed back. The generator is broken."""


def parse_dir(directory: Path = TERRAFORM_DIR) -> dict[str, dict]:
    paths = sorted(directory.glob("*.tf"))
    if not paths:
        raise TerraformError(f"no .tf files under {directory}; run `make terraform`")
    parsed = {}
    for path in paths:
        try:
            with path.open(encoding="utf-8") as handle:
                parsed[path.stem] = hcl2.load(handle)
        except Exception as exc:
            raise TerraformError(f"{path.name} does not parse as HCL: {exc}") from exc
    return parsed


def _flatten(tree, prefix: str = "") -> dict[str, object]:
    """Every leaf in the parsed HCL as dotted-path -> value."""
    leaves: dict[str, object] = {}
    if isinstance(tree, dict):
        for key, value in tree.items():
            leaves.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(tree, list):
        for index, value in enumerate(tree):
            leaves.update(_flatten(value, f"{prefix}[{index}]"))
    else:
        leaves[prefix] = tree
    return leaves


#: quantity -> substrings of a flattened attribute path that would encode it.
#: An empty tuple means: this quantity has no possible home in any resource
#: schema the placements use, which is the structural case rather than an
#: omission of this generator.
REPRESENTATION: dict[str, tuple[str, ...]] = {
    "instance_usd_per_hour": (),            # prices live in the rate card, never in HCL
    "instance_count": ("initial_instance_count", "dedicated_instance_count"),
    "instance_vcpus": ("instance_type",),    # named indirectly, via the type string
    "capacity_rps": (),                      # belongs to the model and the machine
    "traffic_rps": (),                       # belongs to the callers
    "peak_rps": (),
    "autoscale_util_target": ("invocations_per_instance_target",),
    "autoscale_min_instances": ("min_capacity", "min_instance_count"),
    "service_duration_ms": (),
    "billed_duration_ms": (),
    "billing_increment_ms": (),
    "serverless_memory_gb": ("memory_size_in_mb", ".memory", "limits.memory"),
    "serverless_vcpus": (".cpu",),
    "usd_per_gb_second": (),
    "usd_per_vcpu_second": (),
    "usd_per_million_requests": (),
    "data_gb_per_request": (),
    "usd_per_gb_data_processed": (),
    "usd_per_vcpu_hour": (),
    "usd_per_gb_hour": (),
    "batch_rps": (),
    "batch_job_requests": (),
    "job_setup_billed_s": (),
}


@dataclass(frozen=True)
class Coverage:
    """Which bill quantities the generated Terraform can and cannot hold."""

    represented: tuple[str, ...]
    missing: tuple[str, ...]
    #: Of the missing, the ones whose representation tuple is empty: no resource
    #: schema in use could hold them, so no edit to the generator closes the gap.
    structurally_unrepresentable: tuple[str, ...]
    attribute_paths_total: int

    def to_dict(self) -> dict:
        return {
            "represented": list(self.represented),
            "missing": list(self.missing),
            "structurally_unrepresentable": list(self.structurally_unrepresentable),
            "represented_count": len(self.represented),
            "missing_count": len(self.missing),
            "structurally_unrepresentable_count": len(self.structurally_unrepresentable),
            "quantities_total": len(QUANTITIES),
            "attribute_paths_total": self.attribute_paths_total,
        }


def coverage(consumed_quantities: tuple[str, ...] | None = None,
             directory: Path = TERRAFORM_DIR) -> Coverage:
    """Map each quantity the bill consumed against the parsed Terraform."""
    quantities = consumed_quantities or QUANTITIES
    unknown = sorted(set(quantities) - set(REPRESENTATION))
    if unknown:
        raise TerraformError(
            f"the cost model consumes quantities the coverage map does not know "
            f"about: {unknown}. Add them to REPRESENTATION with their possible "
            "homes, or with an empty tuple and a reason."
        )
    leaves = {}
    for provider, tree in parse_dir(directory).items():
        leaves.update({f"{provider}:{path}": v for path, v in _flatten(tree).items()})
    represented, missing, structural = [], [], []
    for quantity in quantities:
        homes = REPRESENTATION[quantity]
        if homes and any(any(home in path for path in leaves) for home in homes):
            represented.append(quantity)
        else:
            missing.append(quantity)
            if not homes:
                structural.append(quantity)
    return Coverage(
        represented=tuple(represented), missing=tuple(missing),
        structurally_unrepresentable=tuple(structural),
        attribute_paths_total=len(leaves),
    )


if __name__ == "__main__":
    print(json.dumps(coverage().to_dict(), indent=2))
