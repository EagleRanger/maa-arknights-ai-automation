"""Deterministically resolve verified production recipes before a real run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY = Path(".project-reasoning") / "COMPONENTS.json"


def _index(rows: Any, kind: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{kind}_ROWS_INVALID")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"{kind}_ROW_INVALID")
        if row["id"] in result:
            raise ValueError(f"{kind}_ID_DUPLICATE:{row['id']}")
        result[row["id"]] = row
    return result


def resolve_production_recipes(
    registry_path: Path,
    required_recipes: list[str],
) -> dict[str, Any]:
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("status") != "active":
        raise ValueError("COMPONENT_REGISTRY_NOT_ACTIVE")

    components = _index(data.get("components"), "COMPONENT")
    policies = _index(data.get("acceptance_policies", []), "POLICY")
    recipes = _index(data.get("recipes"), "RECIPE")
    resolved: list[dict[str, Any]] = []

    for recipe_id in required_recipes:
        recipe = recipes.get(recipe_id)
        if recipe is None:
            raise ValueError(f"RECIPE_MISSING:{recipe_id}")
        if recipe.get("status") != "verified" or recipe.get("mode") != "production":
            raise ValueError(
                f"RECIPE_NOT_VERIFIED_PRODUCTION:{recipe_id}:"
                f"{recipe.get('status')}:{recipe.get('mode')}"
            )

        component_ids = recipe.get("components")
        if not isinstance(component_ids, list) or not component_ids:
            raise ValueError(f"RECIPE_COMPONENTS_INVALID:{recipe_id}")
        for component_id in component_ids:
            component = components.get(component_id)
            if component is None:
                raise ValueError(f"RECIPE_COMPONENT_MISSING:{recipe_id}:{component_id}")
            if component.get("status") != "verified" or component.get("frozen") is not True:
                raise ValueError(
                    f"RECIPE_COMPONENT_NOT_FROZEN:{recipe_id}:{component_id}:"
                    f"{component.get('status')}:{component.get('frozen')}"
                )

        policy_ids = recipe.get("acceptance_policies", [])
        if not isinstance(policy_ids, list):
            raise ValueError(f"RECIPE_POLICIES_INVALID:{recipe_id}")
        for policy_id in policy_ids:
            policy = policies.get(policy_id)
            if policy is None or policy.get("status") != "verified":
                raise ValueError(f"RECIPE_POLICY_NOT_VERIFIED:{recipe_id}:{policy_id}")

        resolved.append(
            {
                "id": recipe_id,
                "components": component_ids,
                "acceptance_policies": policy_ids,
            }
        )

    return {
        "status": "PASS",
        "loop_id": data.get("loop_id"),
        "required_recipes": required_recipes,
        "resolved": resolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--recipe", action="append", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    registry_path = (root / args.registry).resolve()
    try:
        registry_path.relative_to(root)
        result = resolve_production_recipes(registry_path, args.recipe)
    except (ValueError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
