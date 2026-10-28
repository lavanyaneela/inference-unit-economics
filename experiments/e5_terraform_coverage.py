"""E5: what does the infrastructure definition structurally fail to contain?

The impossibility made countable. The cost model tags every line with the
quantities its formula consumed; this experiment maps each one against the parsed
Terraform and publishes the split. The batch placement, cheapest in E2's table,
contributes the sharpest version: its job is an API call with a lifetime, so it
has no resource block for any quantity to live in at all.
"""

import json
from pathlib import Path

from inference_unit_economics.tfgen.coverage import coverage

OUT = Path(__file__).resolve().parents[1] / "docs" / "experiments"


def main() -> dict:
    result = coverage().to_dict()
    result["experiment"] = "e5_terraform_coverage"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e5_terraform_coverage.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"attribute paths in the generated files: {result['attribute_paths_total']}")
    print(f"quantities the bill consumes: {result['quantities_total']}")
    print(f"representable: {result['represented_count']} "
          f"({', '.join(result['represented'])})")
    print(f"unrepresentable: {result['structurally_unrepresentable_count']}")
    for quantity in result["structurally_unrepresentable"]:
        print(f"  {quantity}")
    return result


if __name__ == "__main__":
    main()
