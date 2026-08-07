"""Tests for the per-connector annotation and topology deriver.

Scoped to one connector because adding a connector is when its semantics are actually
being thought about. The properties worth pinning separate "read off a published schema"
from "plausible":

1. **Absence keeps meaning "nobody decided".** `pii: none` is `derive()`'s default when no
   shape matched, not a decision, and emitting it asserts somebody checked.
2. **Contracts and topology want different references.** A column contract must come from
   the loader whose names will exist; an entity graph is a fact about the vendor and
   should come from whichever reference declares the most of it.
3. **A description reaches the column it describes.** The two references differ by one
   mechanical vendor prefix, and a description is the evidence `derive()` weights above
   every name shape — without the bridge almost every facet comes back unset.
4. **A `*_id` naming no declared table is reported, never invented into a relationship.**
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import connector_semantics_derive as csd  # noqa: E402
import lm_propose as lp  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"

needs_cache = pytest.mark.skipif(
    not (csd.ssd.CACHE_DIR / "hubspot.json").exists(),
    reason="hubspot reference cache not refreshed on this branch",
)


def _tables(**spec):
    return {t: [{"name": n, "description": d} for n, d in cols]
            for t, cols in spec.items()}


# ---------------------------------------------------------------------------------------
# Absence means nobody decided
# ---------------------------------------------------------------------------------------


def test_a_column_with_no_pii_shape_gets_no_pii_facet() -> None:
    """`pii: none` is a default, not a decision.

    Emitting it asserts somebody checked this column and cleared it — the same defect as
    tagging an unannotated column `Additive`. The rest of this repository is careful that
    an absent tag reads as undecided; this has to be too.
    """
    annotations, _ = csd.derive_annotations(
        _tables(deal=[("dealname", "The name of the deal.")]), "cite")
    assert annotations
    assert "pii" not in annotations[0].facets


def test_an_email_column_is_direct_pii() -> None:
    annotations, _ = csd.derive_annotations(
        _tables(contact=[("email", "The contact's email.")]), "cite")
    assert annotations[0].facets["pii"] == "direct"


def test_a_column_with_no_description_and_no_name_shape_abstains() -> None:
    """Honestly unannotated rather than emitted blank."""
    annotations, abstained = csd.derive_annotations(_tables(t=[("zzz", "")]), "cite")
    assert annotations == []
    assert abstained and "zzz" in abstained[0]


def test_one_decision_per_column_name_not_per_table() -> None:
    """Annotations are keyed on the column everywhere else here.

    Emitting the same name once per table would let one column be a measure in one and a
    dimension in another — the drift the conformed layer exists to prevent.
    """
    text = csd.render_annotations(
        "toy", "c", "cite",
        [csd.Annotation("email", "contact", {"pii": "direct"}, "", ["e"], "low"),
         csd.Annotation("email", "company", {"pii": "direct"}, "", ["e"], "low")],
        [])
    assert text.count("\n  email:") == 1


# ---------------------------------------------------------------------------------------
# The description bridge
# ---------------------------------------------------------------------------------------


def test_a_description_crosses_the_vendor_prefix() -> None:
    """Fivetran lands `property_email`, dlt lands `email`; the description sits on the
    first and the contract on the second."""
    index = csd.description_index(
        _tables(contact=[("property_email", "The contact's email.")]))
    assert index["email"] == "The contact's email."


def test_a_doc_reference_never_becomes_a_description() -> None:
    """`{{ doc(...) }}` resolves against the vendor's own package, not ours."""
    index = csd.description_index(
        _tables(company=[("property_name", "{{ doc('company_name') }}")]))
    assert "name" not in index


def test_a_borrowed_description_reaches_the_facet_deriver() -> None:
    """Without the bridge the deriver sees a bare name and abstains on nearly everything."""
    annotations, _ = csd.derive_annotations(
        _tables(deal=[("amount", "")]),
        "dlt-cite",
        descriptions={"amount": "The total value of the deal in the deal's currency."},
        description_citation="fivetran-cite",
    )
    assert annotations
    assert annotations[0].definition.startswith("The total value")
    assert any("fivetran-cite" in e for e in annotations[0].evidence)


def test_a_columns_own_description_is_not_overwritten_by_a_borrowed_one() -> None:
    annotations, _ = csd.derive_annotations(
        _tables(deal=[("amount", "Its own description.")]),
        "cite", descriptions={"amount": "A borrowed one."}, description_citation="other")
    assert annotations[0].definition == "Its own description."


# ---------------------------------------------------------------------------------------
# A column name means something only inside its table
# ---------------------------------------------------------------------------------------


def test_a_description_is_taken_from_the_matching_table_not_the_first_one_seen() -> None:
    """`name`, `createdate` and `description` sit on a dozen HubSpot objects with a dozen
    meanings. Measured on the committed reference: 39 of 164 bare names carry more than one
    distinct description, and the flat index handed `company.name` the text "Name of
    Event." — the same class of wrong-entity match `ssd.match_table` refuses by rejecting
    prefix matches."""
    reference = _tables(
        event=[("name", "Name of Event.")],
        company=[("property_name", "The name of the company.")],
    )
    annotations, _ = csd.derive_annotations(
        _tables(company=[("name", "")]), "cite",
        descriptions=csd.description_index(reference),
        description_citation="ref",
        scoped=csd.scoped_description_index(reference),
    )
    assert annotations[0].definition == "The name of the company."
    assert annotations[0].definition_scope == "scoped"


def test_a_singular_plural_table_still_matches() -> None:
    """`ssd.match_table` owns the rule; this only checks it is being asked."""
    reference = _tables(companies=[("name", "The name of the company.")])
    annotations, _ = csd.derive_annotations(
        _tables(company=[("name", "")]), "cite",
        descriptions={}, description_citation="ref",
        scoped=csd.scoped_description_index(reference))
    assert annotations[0].definition == "The name of the company."


def test_a_bare_name_fallback_says_it_may_describe_another_entity() -> None:
    """`product` and `quote` appear in Fivetran's schema not at all, so their columns
    borrow from whatever else declares the same bare name. Measured: all four such
    definitions on the committed proposal are wrong. The evidence has to carry that,
    because a borrowed description otherwise reads as verified."""
    reference = _tables(event=[("name", "Name of Event.")])
    annotations, _ = csd.derive_annotations(
        _tables(product=[("name", "")]), "cite",
        descriptions=csd.description_index(reference), description_citation="ref",
        scoped=csd.scoped_description_index(reference))
    assert annotations[0].definition_scope == "fallback"
    marker = next(e for e in annotations[0].evidence if "FALLBACK" in e)
    assert "`product`" in marker and "another entity" in marker


def test_the_matching_table_wins_even_when_the_bare_index_has_an_answer() -> None:
    """Order of preference, not availability: the flat index almost always has *an*
    answer, which is exactly why it cannot be consulted first."""
    reference = _tables(
        aaa_event=[("subject", "The subject of the email campaign.")],
        ticket=[("subject", "Short summary of ticket.")],
    )
    bare = csd.description_index(reference)
    assert bare["subject"] == "The subject of the email campaign."   # first walked wins
    annotations, _ = csd.derive_annotations(
        _tables(ticket=[("subject", "")]), "cite",
        descriptions=bare, description_citation="ref",
        scoped=csd.scoped_description_index(reference))
    assert annotations[0].definition == "Short summary of ticket."


def test_a_doc_reference_is_excluded_from_both_indexes() -> None:
    reference = _tables(company=[("property_name", "{{ doc('company_name') }}")])
    assert csd.description_index(reference) == {}
    assert csd.scoped_description_index(reference) == {}


# ---------------------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------------------


def test_a_foreign_key_resolves_only_to_a_declared_table() -> None:
    tables = _tables(deal=[("deal_pipeline_id", "")], deal_pipeline=[("pipeline_id", "")])
    relationships, dangling = csd.derive_topology(tables, "cite")
    assert any(r["from_column"] == "deal_pipeline_id" and r["to_table"] == "deal_pipeline"
               for r in relationships)


def test_an_id_naming_no_declared_table_is_reported_never_invented() -> None:
    relationships, dangling = csd.derive_topology(
        _tables(deal=[("owner_id", "")]), "cite")
    assert relationships == []
    assert dangling and "owner" in dangling[0]


def test_a_tables_own_id_is_not_a_self_reference() -> None:
    relationships, _ = csd.derive_topology(_tables(deal=[("deal_id", "")]), "cite")
    assert relationships == []


def test_the_topology_asserts_no_concept() -> None:
    """Which concepts a connector supplies is declared in connectors.yml and generated
    from it; adding one here turns a catalogue expectation into a claim."""
    text = csd.render_topology("toy", "c", "cite", _tables(deal=[("x", "")]), [], [],
                               ["dim_customers"])
    assert "declared_concepts: [dim_customers]" in text
    assert "confirmed: false" in text


# ---------------------------------------------------------------------------------------
# Reference selection
# ---------------------------------------------------------------------------------------


@needs_cache
def test_contracts_and_topology_read_different_references() -> None:
    """The preferred loader names the columns; the richest reference maps the entities.

    Measured: deriving topology from the preferred reference found 0 relationships and 6
    dangling ids, because dlt publishes default properties for 6 CRM objects while
    Fivetran declares 61 tables with real foreign keys.
    """
    preferred, preferred_cite, _ = csd.preferred_tables("hubspot")
    richest, richest_cite, _ = csd.richest_tables("hubspot")
    assert preferred_cite != richest_cite
    assert len(richest) > len(preferred)


@needs_cache
def test_the_real_reference_no_longer_attributes_an_event_description_to_a_company() -> None:
    """The concrete defect, on the data that produced it. `company.name` and
    `ticket.subject` both had a description from a table they have nothing to do with."""
    preferred, cite, _ = csd.preferred_tables("hubspot")
    richest, richest_cite, _ = csd.richest_tables("hubspot")
    annotations, _ = csd.derive_annotations(
        preferred, cite, csd.description_index(richest), richest_cite,
        scoped=csd.scoped_description_index(richest))
    by_key = {(a.table, a.column): a for a in annotations}
    assert by_key[("company", "name")].definition == "The name of the company."
    assert by_key[("ticket", "subject")].definition == "Short summary of ticket."


@needs_cache
def test_the_committed_hubspot_proposals_are_current() -> None:
    """A stale proposal is a derivation nobody can reproduce."""
    payload = csd.run("enhanza-analytics", "hubspot", write=False, check=True)
    assert payload["status"] == "ok", payload.get("reason")
    assert payload["changed"] == [], (
        f"stale: {payload['changed']} — re-run connector_semantics_derive --write"
    )


@needs_cache
def test_the_proposal_promotes_under_its_connector_name() -> None:
    path = lp.proposal_path(ENHANZA, "annotations", source="hubspot")
    assert path.name == "annotations.hubspot.yml"
    if not path.exists():
        pytest.skip("proposal not written on this branch")
    text = path.read_text(encoding="utf-8")
    assert "source: hubspot-reference" in text
    assert "reviewed: false" in text
    assert "NOT AN ARTIFACT" in text
