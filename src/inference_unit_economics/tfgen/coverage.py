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
    #: Placements whose definition consists of zero resource blocks, counted
    #: from the generator's committed manifest after verifying every listed
    #: address against the parsed files. An audit caught the earlier prose
    #: asserting "two" where the files held three.
    blockless_placements: tuple[str, ...]
    placements_total: int

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
            "blockless_placements": list(self.blockless_placements),
            "blockless_placements_count": len(self.blockless_placements),
            "placements_total": self.placements_total,
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
    parsed = parse_dir(directory)
    leaves = {}
    for provider, tree in parsed.items():
        leaves.update({f"{provider}:{path}": v for path, v in _flatten(tree).items()})
    blockless, total = _blockless(parsed, directory)
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
        blockless_placements=blockless, placements_total=total,
    )


def _declared_resources(tree: dict) -> set[str]:
    addresses: set[str] = set()
    for block in tree.get("resource", []):
        for rtype, named in block.items():
            # python-hcl2 keeps the source's quote characters inside label
            # keys, so the type and name arrive wearing their own quotes.
            clean_type = rtype.strip('"')
            for name in named:
                if name == "__is_block__":
                    continue
                addresses.add(f"{clean_type}.{name.strip(chr(34))}")
    return addresses


def _blockless(parsed: dict[str, dict], directory: Path) -> tuple[tuple[str, ...], int]:
    """Count the placements with zero resource blocks, against the files.

    The manifest is the generator's claim; this function holds it to the parsed
    reality in both directions. Every address the manifest lists must exist in
    the files, and every resource the files declare must be claimed by some
    placement, so neither a phantom block nor an unclaimed one can skew the
    count."""
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise TerraformError(
            f"no manifest at {manifest_path}; run `make terraform` so the "
            "blockless count is computed rather than asserted"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping = manifest["resources_by_placement"]
    shared = manifest.get("shared_resources", {})
    blockless: list[str] = []
    total = 0
    for provider, placements in mapping.items():
        declared = _declared_resources(parsed.get(provider, {}))
        claimed: set[str] = set(shared.get(provider, []))
        phantom_shared = [a for a in claimed if a not in declared]
        if phantom_shared:
            raise TerraformError(
                f"{provider}: shared resources {phantom_shared} are in the "
                "manifest but not in the parsed files"
            )
        for placement, addresses in placements.items():
            total += 1
            claimed.update(addresses)
            missing_addrs = [a for a in addresses if a not in declared]
            if missing_addrs:
                raise TerraformError(
                    f"{provider}/{placement}: manifest claims {missing_addrs} "
                    "but the parsed files declare no such resource"
                )
            if not addresses:
                blockless.append(f"{provider}/{placement}")
        unclaimed = declared - claimed
        if unclaimed:
            raise TerraformError(
                f"{provider}: resources {sorted(unclaimed)} are declared in the "
                "files and claimed by no placement in the manifest"
            )
    return tuple(sorted(blockless)), total


if __name__ == "__main__":
    print(json.dumps(coverage().to_dict(), indent=2))
