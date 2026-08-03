"""Pins for scripts/dbt_seed_generator.py.

The sample seeds exist so `dbt build` runs with no warehouse. That makes them load-bearing
for every other check that needs a compile, which is why a defect here fails the project
rather than one test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dbt_seed_generator as seeder  # noqa: E402
from _manifest import Manifest  # noqa: E402

# ---------------------------------------------------------------------------------------
# A source a model also writes
# ---------------------------------------------------------------------------------------


def test_a_source_relation_a_model_writes_gets_no_seed():
    """dbt refuses to compile the whole project when two resources claim one relation.

    `app.dimension_categories` is declared as a source *and* maintained by an incremental
    model that merges into it. A seed standing in for the source declares the same
    `(schema, alias)` the model does, and `dbt compile` fails with

        dbt found two resources with the database representation
        "enhanza_sample"."app_demo"."dimension_categories"

    which takes down every model, not just the sample build. It stayed hidden until a
    parser fix let that source's columns resolve for the first time.
    """
    manifest = {
        "metadata": {"project_name": "proj"},
        "nodes": {
            "model.proj.dimension_categories": {
                "resource_type": "model",
                "name": "dimension_categories",
                "config": {"schema": "app"},
                "alias": "dimension_categories",
            }
        },
        "sources": {
            "source.proj.app.dimension_categories": {
                "resource_type": "source",
                "source_name": "app",
                "name": "dimension_categories",
            },
            "source.proj.app.dimension_mapping": {
                "resource_type": "source",
                "source_name": "app",
                "name": "dimension_mapping",
            },
        },
    }

    claimed = seeder._relations_claimed_by_models(Manifest(manifest))

    assert ("app", "dimension_categories") in claimed
    assert ("app", "dimension_mapping") not in claimed, (
        "a source with no model behind it must still get a seed"
    )


def test_the_committed_seeds_never_collide_with_a_model():
    """The gate. Runs against the real project, needs no warehouse."""
    manifest_path = (
        REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
        "/dbt_project/target/manifest.json"
    )
    if not manifest_path.is_file():
        pytest.skip("no manifest")
    man = Manifest.load(str(manifest_path))
    seeds = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/seeds/sample"
    if not seeds.is_dir():
        pytest.skip("no sample seeds")

    claimed = seeder._relations_claimed_by_models(man)
    committed = {
        tuple(p.stem.split("__", 1)) for p in seeds.glob("*.csv") if "__" in p.stem
    }

    assert not (committed & claimed), sorted(committed & claimed)
