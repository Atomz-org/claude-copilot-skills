#!/usr/bin/env python3
"""Render a use-case's ontology and topology as one self-contained HTML page.

The audience is someone who does not know what an ontology is. The page therefore
never says "ontology", "IRI", "conformsTo", or "erp:LineItem" in its own voice — it
says *business thing*, *source system*, *family*, and shows the technical name beside
the plain one so an engineer can still cross-reference. The vocabulary map is
`PLAIN_WORDS` and `humanise()`.

What it draws, and what it refuses to draw
------------------------------------------
This ontology asserts exactly three kinds of edge, and the page draws those three:

    connector --providedBy--> concept     19 systems x 58 concepts, bipartite
    concept   --conformsTo--> core class  the family taxonomy
    concept   --has-->        property    from `mappings`, 92 of them

It does **not** assert foreign keys between concepts. A classic ERD's crow's feet —
`fact_order_rows` -> `dim_customers` — are not in this data, and drawing them from the
`fact_`/`dim_` naming convention would be inventing a contract the model never made
(rule 5 in .claude/rules/analytics-engineering-rules.md). So the entity cards carry
real attributes and the relationship lines are the real `providedBy` edges, drawn as a
hub-and-spoke per concept. Model-level foreign keys *do* exist downstream, derived from
dbt `relationships` tests — `scripts/erd_generator.py` is what draws those, and the two
are complementary rather than alternatives.

Why a generator and not a static file
-------------------------------------
It is a framework, not one page: everything comes from `ontology/index.json`, whose
shape is the same for every use-case, so a use-case scaffolded tomorrow renders with no
new code. `index.json` is already the machine-facing projection the MCP tools read
(see the use-case's `ontology/README.md`), which makes it the right input — the Turtle
is normative but needs a parser, and `rdflib` is optional in this repository.

Standard library only, and the output has **no external references at all**: no CDN, no
webfont, no fetch. It opens from `file://`, from a share, and inside a CSP that blocks
every other host. That matches `public/decision-path.html`, the page this one sits
beside.

Usage:
    python3 scripts/ontology_ui.py --use-case enhanza-analytics
    python3 scripts/ontology_ui.py --use-case enhanza-analytics --check
    python3 scripts/ontology_ui.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paths  # noqa: E402
from _paths import REPO  # noqa: E402

OUT_DIR = REPO / "public"

# Words the page uses instead of the vocabulary's own. The left side is what the data
# says; the right side is what someone who has never seen RDF would say.
PLAIN_WORDS: Dict[str, str] = {
    "erp": "Finance & operations",
    "crm": "Sales & customers",
    "implemented": "Live",
    "planned": "Planned",
    "direct": "copied as-is",
    "renamed": "renamed",
    "derived": "calculated",
    "union": "merged from several",
}

# `dim_` and `fact_` are this project's own convention, not an inference: the layer
# rules in scripts/dbt_manifest_to_graphify.py and the connector scaffolder both use
# them. Naming the split in plain words is the single most useful thing on the page.
KIND_OF_THING = {
    "dim": ("Reference data", "Things you look up — a customer, an article, an account."),
    "fact": ("Activity", "Things that happen and can be counted — an order, an invoice line."),
}


def humanise(token: str) -> str:
    """`erp:LineItem` -> `Line item`; `dim_order_rows` -> `Order rows`.

    Prefix dropped, camelCase split, underscores to spaces, first letter capitalised.
    Acronyms that would read wrong lowercased are held back by `_ACRONYMS`.
    """
    bare = token.split(":", 1)[-1]
    bare = re.sub(r"^(dim|fact)_", "", bare)
    bare = bare.replace("_", " ")
    bare = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", bare)
    words = [w for w in bare.split() if w]
    if not words:
        # Nothing survived the stripping — fall back to the raw token so the card still
        # says *something*. An empty label renders as a blank clickable box, which reads
        # as a rendering bug rather than as missing data.
        return token or "(unnamed)"
    out = []
    for i, word in enumerate(words):
        upper = word.upper()
        if upper in _ACRONYMS:
            out.append(upper)
        elif i == 0:
            out.append(word[:1].upper() + word[1:].lower())
        else:
            out.append(word.lower())
    return " ".join(out)


_ACRONYMS = {"ID", "VAT", "SKU", "URL", "API", "CRM", "ERP", "PO"}


def thing_kind(concept: str) -> Tuple[str, str]:
    """Which half of the star schema a concept sits in, in plain words."""
    prefix = concept.split("_", 1)[0]
    return KIND_OF_THING.get(prefix, ("Other", "Not following the dim_/fact_ convention."))


def build_payload(index: Dict[str, Any]) -> Dict[str, Any]:
    """Reshape `index.json` into exactly what the page renders.

    Done here rather than in JavaScript so the page ships no derivation logic: what the
    browser receives is already the answer, and a test can assert the numbers without a
    DOM. Every field is traceable to `index.json`; nothing is computed that the ontology
    does not already assert.
    """
    connectors = index.get("connectors") or []
    concepts = index.get("concepts") or []
    mappings = index.get("mappings") or []
    models = index.get("models") or []
    gaps = index.get("gaps") or []

    by_key = {c["key"]: c for c in connectors}

    # concept -> its real attributes, from the mappings the ontology actually recorded.
    attrs: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for mapping in mappings:
        slot = attrs.setdefault(mapping["concept"], {})
        prop = mapping["property"]
        entry = slot.setdefault(
            prop,
            {"property": prop, "label": humanise(prop), "sources": [], "transforms": set()},
        )
        entry["sources"].append(
            {"connector": mapping["connector"], "column": mapping["source_column"]}
        )
        entry["transforms"].add(mapping.get("transform") or "direct")

    # concept -> the dbt models that realise it, per connector.
    realised: Dict[str, Dict[str, str]] = {}
    for model in models:
        realised.setdefault(model["concept"], {})[model["connector"]] = model["dbt_model"]

    gap_reason = {g["concept"]: g.get("reason", "") for g in gaps}

    out_concepts: List[Dict[str, Any]] = []
    for concept in concepts:
        name = concept["concept"]
        kind, kind_blurb = thing_kind(name)
        attribute_rows = sorted(
            (
                {
                    "property": a["property"],
                    "label": a["label"],
                    "transforms": sorted(a["transforms"]),
                    "columns": sorted({s["column"] for s in a["sources"]}),
                    "connectors": sorted({s["connector"] for s in a["sources"]}),
                }
                for a in attrs.get(name, {}).values()
            ),
            key=lambda a: (-len(a["connectors"]), a["label"]),
        )
        # `implemented_by` is a claim made by the connector registry; `models` is evidence
        # read out of the dbt project. They disagree on two pairs in enhanza-analytics —
        # seventime/fact_work_orders and tripletex/dim_voucher_series are declared
        # implemented with no model behind them. Neither side is silently preferred: the
        # claim is still shown as live, and the missing evidence is shown beside it. A
        # page that quietly reported 110 or quietly reported 112 would be hiding the only
        # interesting thing here.
        declared = sorted(concept.get("implemented_by") or [])
        has_model = realised.get(name, {})
        out_concepts.append({
            "key": name,
            "label": humanise(name),
            "technical": name,
            "family": humanise(concept["core_class"]),
            "family_key": concept["core_class"],
            "kind": kind,
            "kind_blurb": kind_blurb,
            "live": declared,
            "no_model": [k for k in declared if k not in has_model],
            "planned": sorted(concept.get("planned_by") or []),
            "supplier_count": concept.get("supplier_count") or 0,
            "attributes": attribute_rows,
            "models": has_model,
            "gap": gap_reason.get(name, ""),
        })
    out_concepts.sort(key=lambda c: (-len(c["live"]), c["label"]))

    out_connectors = []
    for connector in connectors:
        key = connector["key"]
        supplies_live = sorted(c["key"] for c in out_concepts if key in c["live"])
        supplies_planned = sorted(c["key"] for c in out_concepts if key in c["planned"])
        out_connectors.append({
            "key": key,
            "label": connector.get("label") or humanise(key),
            "kind": connector.get("kind") or "erp",
            "kind_label": PLAIN_WORDS.get(connector.get("kind") or "erp", "Other"),
            "status": connector.get("status") or "planned",
            "status_label": PLAIN_WORDS.get(connector.get("status") or "planned", "Planned"),
            "region": connector.get("region") or "",
            "currency": connector.get("default_currency") or "",
            "enable_var": connector.get("enable_var") or "",
            "live": supplies_live,
            "planned": supplies_planned,
        })
    out_connectors.sort(key=lambda c: (-len(c["live"]), c["label"]))

    families: Dict[str, int] = {}
    for concept in out_concepts:
        families[concept["family"]] = families.get(concept["family"], 0) + 1

    return {
        "use_case": index.get("use_case", ""),
        "title": index.get("title", index.get("use_case", "")),
        "generated_by": "scripts/ontology_ui.py",
        "source": "ontology/index.json",
        "concepts": out_concepts,
        "connectors": out_connectors,
        "gaps": [
            {
                "concept": g["concept"],
                "label": humanise(g["concept"]),
                "reason": g.get("reason", ""),
                "live": sorted(g.get("implemented_by") or []),
                "planned": sorted(g.get("planned_by") or []),
            }
            for g in sorted(gaps, key=lambda g: (len(g.get("implemented_by") or []), g["concept"]))
        ],
        "families": [
            {"family": name, "count": count}
            for name, count in sorted(families.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "unbacked": sorted(
            (
                {
                    "concept": c["key"],
                    "label": c["label"],
                    "connector": k,
                    "system": (by_key.get(k) or {}).get("label") or humanise(k),
                }
                for c in out_concepts
                for k in c["no_model"]
            ),
            key=lambda r: (r["concept"], r["connector"]),
        ),
        "totals": {
            "connectors": len(out_connectors),
            "connectors_live": sum(1 for c in out_connectors if c["status"] == "implemented"),
            "concepts": len(out_concepts),
            "concepts_live": sum(1 for c in out_concepts if c["live"]),
            "links": sum(len(c["live"]) for c in out_concepts),
            "links_with_model": len(models),
            "links_unbacked": sum(len(c["no_model"]) for c in out_concepts),
            "attributes": sum(len(c["attributes"]) for c in out_concepts),
            "gaps": len(gaps),
        },
    }


# =======================================================================================
# The page
# =======================================================================================

# Colours are the validated reference palette (dataviz skill, references/palette.md).
# Categorical slots 1 and 2 carry the only two-way split on the page (finance vs sales);
# both modes were run through scripts/validate_palette.js and pass every gate — worst
# adjacent CVD dE 24.7 light / 26.8 dark against an >= 8 target. Coverage states use the
# fixed status palette and are *never* colour alone: every cell carries a glyph and a
# text label, which is also what makes the grid readable in the printed/forced-colours
# case where the status hues collapse.
_CSS = """
:root{
  color-scheme:light;
  --plane:#f9f9f7; --surface:#fcfcfb; --surface-2:#f2f2ee;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --line:#e1e0d9; --rule:#c3c2b7; --ring:rgba(11,11,11,0.10);
  --erp:#2a78d6; --crm:#eb6834;
  --live:#0ca30c; --planned:#fab219; --none:#c3c2b7; --crit:#d03b3b;
  --seq-1:#cde2fb; --seq-2:#9ec5f4; --seq-3:#5598e7; --seq-4:#2a78d6; --seq-5:#184f95;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#232322;
    --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
    --line:#2c2c2a; --rule:#383835; --ring:rgba(255,255,255,0.10);
    --erp:#3987e5; --crm:#d95926;
    --none:#383835;
    --seq-1:#104281; --seq-2:#184f95; --seq-3:#256abf; --seq-4:#3987e5; --seq-5:#86b6ef;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#232322;
  --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --rule:#383835; --ring:rgba(255,255,255,0.10);
  --erp:#3987e5; --crm:#d95926;
  --none:#383835;
  --seq-1:#104281; --seq-2:#184f95; --seq-3:#256abf; --seq-4:#3987e5; --seq-5:#86b6ef;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 72px}
h1{font-size:26px;line-height:1.2;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:17px;margin:32px 0 10px;letter-spacing:-.005em}
p.lede{color:var(--ink-2);margin:0 0 4px;max-width:70ch}
.sub{color:var(--muted);font-size:13px;margin:0}
a{color:inherit}

/* ---- KPI row ---- */
.kpis{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:22px 0 4px}
.kpi{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:13px 14px}
.kpi .n{font-size:27px;font-weight:600;letter-spacing:-.02em;display:block;line-height:1.1}
.kpi .l{font-size:12px;color:var(--ink-2);display:block;margin-top:3px}
.kpi .h{font-size:11px;color:var(--muted);display:block;margin-top:2px}

/* ---- controls ---- */
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:20px 0 14px}
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{appearance:none;background:var(--surface);border:1px solid var(--ring);color:var(--ink-2);
  border-radius:999px;padding:6px 13px;font:inherit;font-size:13px;cursor:pointer}
.tab[aria-selected="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.tab:focus-visible,.chip:focus-visible,.card:focus-visible,.cell:focus-visible{outline:2px solid var(--erp);outline-offset:2px}
input[type=search]{flex:1;min-width:180px;background:var(--surface);color:var(--ink);
  border:1px solid var(--ring);border-radius:8px;padding:7px 11px;font:inherit;font-size:13px}
.count{font-size:12px;color:var(--muted)}

/* ---- legend ---- */
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink-2);
  background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:9px 12px;margin-bottom:14px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
.dot.live{background:var(--live)} .dot.planned{background:var(--planned)}
.dot.none{background:var(--none)} .dot.unbacked{background:var(--crit)}
.dot.erp{background:var(--erp)} .dot.crm{background:var(--crm)}

/* ---- ERD cards ---- */
.family{margin:26px 0 8px;display:flex;align-items:baseline;gap:9px}
.family h3{font-size:14px;margin:0;letter-spacing:-.005em}
.family .c{font-size:12px;color:var(--muted)}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(268px,1fr))}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;overflow:hidden;
  text-align:left;font:inherit;color:inherit;cursor:pointer;padding:0;display:block;width:100%}
.card:hover{border-color:var(--rule)}
.card[aria-pressed="true"]{border-color:var(--erp);box-shadow:0 0 0 1px var(--erp)}
.card .hd{padding:11px 13px 9px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:flex-start}
.card .hd .t{flex:1;min-width:0}
.card .nm{font-weight:600;font-size:14px;display:block;letter-spacing:-.005em}
.card .tn{font-size:11px;color:var(--muted);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  display:block;margin-top:2px;overflow-wrap:anywhere}
.badge{font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid var(--ring);
  color:var(--ink-2);white-space:nowrap;flex:none}
.badge.k{background:var(--surface-2)}
.attrs{list-style:none;margin:0;padding:6px 0;max-height:168px;overflow:auto}
.attrs li{display:flex;gap:8px;padding:3px 13px;font-size:12.5px;align-items:baseline}
.attrs .a{flex:1;min-width:0;overflow-wrap:anywhere}
.attrs .m{color:var(--muted);font-size:11px;white-space:nowrap}
.attrs .empty{color:var(--muted);font-style:italic;padding:5px 13px;font-size:12px;display:block}
.sup{display:flex;flex-wrap:wrap;gap:4px;padding:9px 13px;border-top:1px solid var(--line);background:var(--surface-2)}
.chip{font-size:11px;padding:2px 7px;border-radius:6px;border:1px solid var(--ring);
  background:var(--surface);color:var(--ink-2);white-space:nowrap}
.chip.live{border-color:var(--live)} .chip.planned{border-color:var(--planned);border-style:dashed}
.chip.unbacked{border-color:var(--crit);color:var(--crit)}
.chip.more{color:var(--muted);border-style:dotted}

/* ---- detail ---- */
.detail{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px;margin:14px 0 0}
.detail h3{margin:0 0 2px;font-size:16px}
.spoke{width:100%;height:auto;display:block;margin:8px 0 2px;overflow:visible}
.spoke text{font:11px system-ui,-apple-system,sans-serif}
.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;font-size:12.5px;margin-top:10px}
.kv dt{color:var(--muted)} .kv dd{margin:0;overflow-wrap:anywhere}

/* ---- matrix ---- */
.scroll{overflow-x:auto;border:1px solid var(--ring);border-radius:10px;background:var(--surface)}
table{border-collapse:separate;border-spacing:0;font-size:12px;width:max-content;min-width:100%}
th,td{padding:5px 7px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
thead th{position:sticky;top:0;background:var(--surface);z-index:2;font-weight:600;
  color:var(--ink-2);border-bottom:1px solid var(--rule)}
tbody th{position:sticky;left:0;background:var(--surface);z-index:1;font-weight:500;
  border-right:1px solid var(--line);max-width:220px;overflow:hidden;text-overflow:ellipsis}
thead th.rot{height:132px;padding:0;vertical-align:bottom}
thead th.rot>div{width:24px;transform-origin:bottom left;
  transform:translateX(15px) rotate(-60deg);position:relative;left:2px}
thead th.rot span{padding:0 4px;font-weight:500;font-size:11px}
td.cell{text-align:center;font-size:11px;color:var(--muted);cursor:default}
td.cell.live{color:var(--live);font-weight:700} td.cell.planned{color:var(--planned);font-weight:700}
td.cell.unbacked{color:var(--crit);font-weight:700}
tbody tr:hover td,tbody tr:hover th{background:var(--surface-2)}
.tot{color:var(--muted);font-variant-numeric:tabular-nums}

/* ---- lists ---- */
.rows{display:grid;gap:8px}
.row{background:var(--surface);border:1px solid var(--ring);border-radius:9px;padding:11px 13px}
.row .top{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
.row .nm{font-weight:600}
.row .why{color:var(--ink-2);font-size:12.5px;margin-top:3px}
.bar-track{height:5px;background:var(--surface-2);border-radius:3px;overflow:hidden;margin-top:7px}
.bar-fill{height:100%;background:var(--seq-4);border-radius:3px}
.hidden{display:none}
footer{margin-top:44px;padding-top:14px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
@media (max-width:640px){ .wrap{padding:18px 13px 56px} h1{font-size:21px} }
@media print{ .bar,.tab{display:none} .scroll{overflow:visible} }
"""

_JS = r"""
const D = JSON.parse(document.getElementById("payload").textContent);
const $ = (s, r) => (r || document).querySelector(s);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c;
  if (x !== undefined) n.textContent = x; return n; };
const esc = s => String(s == null ? "" : s);

let view = "map", q = "", picked = null;

/* A concept matches on its plain name, its technical name, its family, or any system
   that supplies it — because a reader searching "shopify" means "show me what Shopify
   gives us", not "find a concept literally called shopify". */
function matches(c) {
  if (!q) return true;
  const hay = [c.label, c.technical, c.family, c.kind, ...c.live, ...c.planned,
               ...c.attributes.map(a => a.label + " " + a.columns.join(" "))]
              .join(" ").toLowerCase();
  return hay.includes(q);
}
function matchesConn(c) {
  if (!q) return true;
  return [c.label, c.key, c.kind_label, c.region, c.currency, c.status_label]
    .join(" ").toLowerCase().includes(q);
}

function supplierChips(c) {
  const box = el("div", "sup");
  const live = c.live.slice(0, 6), planned = c.planned.slice(0, 3);
  live.forEach(k => {
    const chip = el("span", "chip live", nameOf(k));
    /* Declared implemented by the registry, but no dbt model was found for the pair.
       Marked rather than dropped: the claim is real, the evidence is missing, and
       which of the two is wrong is not this page's call. */
    if (c.no_model.includes(k)) {
      chip.className = "chip unbacked";
      chip.textContent = nameOf(k) + " (no model)";
      chip.title = "Declared in the connector registry, but no dbt model realises it";
    }
    box.appendChild(chip);
  });
  if (c.live.length > live.length)
    box.appendChild(el("span", "chip more", "+" + (c.live.length - live.length) + " more"));
  planned.forEach(k => box.appendChild(el("span", "chip planned", nameOf(k) + " (planned)")));
  if (!c.live.length && !c.planned.length)
    box.appendChild(el("span", "chip more", "no system supplies this yet"));
  return box;
}
const CONN = {}; D.connectors.forEach(c => CONN[c.key] = c);
const nameOf = k => (CONN[k] && CONN[k].label) || k;

function conceptCard(c) {
  const card = el("button", "card");
  card.type = "button";
  card.setAttribute("aria-pressed", picked === c.key ? "true" : "false");
  card.addEventListener("click", () => { picked = picked === c.key ? null : c.key; render(); });

  const hd = el("div", "hd"), t = el("div", "t");
  t.appendChild(el("span", "nm", c.label));
  t.appendChild(el("span", "tn", c.technical));
  hd.appendChild(t);
  hd.appendChild(el("span", "badge k", c.kind));
  card.appendChild(hd);

  const ul = el("ul", "attrs");
  if (c.attributes.length) {
    c.attributes.forEach(a => {
      const li = el("li");
      li.appendChild(el("span", "a", a.label));
      li.appendChild(el("span", "m", a.transforms.map(t => D.words[t] || t).join(", ")));
      li.title = "From: " + a.columns.join(", ");
      ul.appendChild(li);
    });
  } else {
    ul.appendChild(el("span", "empty", "No field-level mapping recorded yet"));
  }
  card.appendChild(ul);
  card.appendChild(supplierChips(c));
  return card;
}

/* Hub and spoke: the concept in the middle, every system that supplies it around the
   rim. These are the ontology's real `providedBy` edges — the only relationship it
   asserts about a concept. Solid = live, dashed = planned. */
function spoke(c) {
  const NS = "http://www.w3.org/2000/svg";
  const all = c.live.map(k => [k, "live"]).concat(c.planned.map(k => [k, "planned"]));
  const n = all.length;
  const W = 720, rowH = 26, H = Math.max(150, n * rowH + 40);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "spoke");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label",
    c.label + " is supplied by " + c.live.length + " live and " + c.planned.length + " planned systems");
  const cx = 150, cy = H / 2;

  const mk = (t, attrs, txt) => { const e = document.createElementNS(NS, t);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (txt !== undefined) e.textContent = txt; return e; };

  all.forEach(([k, state], i) => {
    const y = 24 + i * rowH, x = 430;
    svg.appendChild(mk("path", {
      d: "M" + (cx + 96) + " " + cy + " C " + (cx + 190) + " " + cy + ", " + (x - 90) + " " + y + ", " + x + " " + y,
      fill: "none", stroke: state === "live" ? "var(--live)" : "var(--planned)",
      "stroke-width": 2, "stroke-dasharray": state === "live" ? "0" : "4 3", opacity: .75
    }));
    svg.appendChild(mk("circle", { cx: x, cy: y, r: 4,
      fill: state === "live" ? "var(--live)" : "var(--planned)" }));
    svg.appendChild(mk("text", { x: x + 10, y: y + 4, fill: "var(--ink)" },
      nameOf(k) + (state === "planned" ? "  (planned)" : "")));
  });
  if (!n) svg.appendChild(mk("text", { x: cx + 110, y: cy + 4, fill: "var(--muted)" },
    "no system supplies this yet"));

  svg.appendChild(mk("rect", { x: cx - 96, y: cy - 21, width: 192, height: 42, rx: 8,
    fill: "var(--surface-2)", stroke: "var(--erp)", "stroke-width": 2 }));
  svg.appendChild(mk("text", { x: cx, y: cy - 3, "text-anchor": "middle",
    fill: "var(--ink)", "font-weight": "600" }, c.label));
  svg.appendChild(mk("text", { x: cx, y: cy + 12, "text-anchor": "middle",
    fill: "var(--muted)", "font-size": "10" }, c.technical));
  return svg;
}

function detail(c) {
  const d = el("div", "detail");
  d.appendChild(el("h3", null, c.label));
  d.appendChild(el("p", "sub", c.kind + " — " + c.kind_blurb));
  d.appendChild(spoke(c));
  const kv = el("dl", "kv");
  const add = (k, v) => { kv.appendChild(el("dt", null, k)); kv.appendChild(el("dd", null, v)); };
  add("Technical name", c.technical);
  add("Family", c.family + "  (" + c.family_key + ")");
  add("Live in", c.live.length ? c.live.map(nameOf).join(", ") : "—");
  add("Planned in", c.planned.length ? c.planned.map(nameOf).join(", ") : "—");
  add("Fields mapped", c.attributes.length
    ? c.attributes.map(a => a.label + " (" + a.columns.join(", ") + ")").join("; ") : "none recorded");
  const models = Object.keys(c.models).sort();
  add("dbt models", models.length ? models.map(k => c.models[k]).join(", ") : "—");
  if (c.gap) add("Flagged", c.gap);
  d.appendChild(kv);
  return d;
}

function renderMap(root) {
  const list = D.concepts.filter(matches);
  $("#count").textContent = list.length + " of " + D.concepts.length + " business things";
  if (picked) {
    const c = D.concepts.find(x => x.key === picked);
    if (c) root.appendChild(detail(c));
  }
  const byFam = {};
  list.forEach(c => (byFam[c.family] = byFam[c.family] || []).push(c));
  Object.keys(byFam).sort((a, b) => byFam[b].length - byFam[a].length || a.localeCompare(b))
    .forEach(fam => {
      const h = el("div", "family");
      const h3 = el("h3", null, fam); h.appendChild(h3);
      h.appendChild(el("span", "c", byFam[fam].length + (byFam[fam].length === 1 ? " thing" : " things")));
      root.appendChild(h);
      const g = el("div", "grid");
      byFam[fam].forEach(c => g.appendChild(conceptCard(c)));
      root.appendChild(g);
    });
  if (!list.length) root.appendChild(el("p", "sub", "Nothing matches that search."));
}

function renderMatrix(root) {
  const cs = D.concepts.filter(matches);
  const conns = D.connectors;
  $("#count").textContent = conns.length + " systems x " + cs.length + " business things";
  const wrap = el("div", "scroll"), table = el("table");
  table.setAttribute("aria-label", "Which source system supplies which business thing");

  const thead = el("thead"), hr = el("tr");
  hr.appendChild(el("th", null, "Source system"));
  cs.forEach(c => { const th = el("th", "rot"); const d = el("div");
    d.appendChild(el("span", null, c.label)); th.appendChild(d);
    th.title = c.technical; hr.appendChild(th); });
  hr.appendChild(el("th", null, "Live"));
  thead.appendChild(hr); table.appendChild(thead);

  const tb = el("tbody");
  conns.forEach(cn => {
    const tr = el("tr");
    const th = el("th", null, cn.label); th.title = cn.key; tr.appendChild(th);
    let live = 0;
    cs.forEach(c => {
      const isLive = c.live.includes(cn.key), isPlan = c.planned.includes(cn.key);
      const unbacked = isLive && c.no_model.includes(cn.key);
      if (isLive) live++;
      const state = unbacked ? "unbacked" : isLive ? "live" : isPlan ? "planned" : "none";
      const glyph = { unbacked: "▲", live: "●", planned: "○", none: "·" }[state];
      const td = el("td", "cell " + state, glyph);
      td.title = cn.label + " → " + c.label + ": " + {
        unbacked: "declared implemented, but no dbt model found",
        live: "live", planned: "planned", none: "not supplied"
      }[state];
      tr.appendChild(td);
    });
    tr.appendChild(el("td", "tot", String(live)));
    tb.appendChild(tr);
  });
  table.appendChild(tb); wrap.appendChild(table); root.appendChild(wrap);
}

function renderSystems(root) {
  const list = D.connectors.filter(matchesConn);
  $("#count").textContent = list.length + " of " + D.connectors.length + " source systems";
  const rows = el("div", "rows");
  const max = Math.max(1, ...D.connectors.map(c => c.live.length));
  list.forEach(c => {
    const r = el("div", "row");
    const top = el("div", "top");
    top.appendChild(el("span", "nm", c.label));
    const b = el("span", "badge"); b.textContent = c.kind_label;
    b.style.borderColor = c.kind === "crm" ? "var(--crm)" : "var(--erp)";
    top.appendChild(b);
    top.appendChild(el("span", "badge k", c.status_label));
    if (c.region) top.appendChild(el("span", "badge k", c.region));
    if (c.currency) top.appendChild(el("span", "badge k", c.currency));
    r.appendChild(top);
    r.appendChild(el("div", "why", c.live.length
      ? "Supplies " + c.live.length + " business thing" + (c.live.length === 1 ? "" : "s") +
        (c.planned.length ? ", " + c.planned.length + " more planned" : "")
      : (c.planned.length ? c.planned.length + " planned, none live yet" : "Nothing mapped yet")));
    const track = el("div", "bar-track"), fill = el("div", "bar-fill");
    fill.style.width = (100 * c.live.length / max) + "%";
    track.appendChild(fill); r.appendChild(track);
    rows.appendChild(r);
  });
  root.appendChild(rows);
  if (!list.length) root.appendChild(el("p", "sub", "Nothing matches that search."));
}

function renderGaps(root) {
  const list = D.gaps.filter(g => !q ||
    (g.label + " " + g.concept + " " + g.reason).toLowerCase().includes(q));
  $("#count").textContent = list.length + " of " + D.gaps.length + " flagged";
  root.appendChild(el("p", "sub",
    "A business thing only one system supplies cannot be compared across systems yet. " +
    "That is a gap in the model, not necessarily a problem with the data."));

  /* The registry and the dbt project disagreeing is a different, sharper problem than a
     single-supplier concept, so it gets its own block rather than being folded in. */
  if (D.unbacked && D.unbacked.length) {
    const h = el("div", "family");
    h.appendChild(el("h3", null, "Declared, but no dbt model found"));
    h.appendChild(el("span", "c", D.unbacked.length + " link" + (D.unbacked.length === 1 ? "" : "s")));
    root.appendChild(h);
    root.appendChild(el("p", "sub",
      "The connector registry says these are implemented; no model in the dbt project " +
      "realises them. One of the two is out of date."));
    const ur = el("div", "rows");
    D.unbacked.forEach(u => {
      const r = el("div", "row"), top = el("div", "top");
      top.appendChild(el("span", "nm", u.system + " → " + u.label));
      const b = el("span", "badge"); b.textContent = "no model";
      b.style.borderColor = "var(--crit)"; b.style.color = "var(--crit)";
      top.appendChild(b);
      r.appendChild(top);
      r.appendChild(el("div", "why", "Registry marks " + u.connector +
        " as implementing " + u.concept + ", but no dbt model was found for the pair."));
      ur.appendChild(r);
    });
    root.appendChild(ur);
    root.appendChild(el("div", "family"));
  }

  const rows = el("div", "rows");
  list.forEach(g => {
    const r = el("div", "row"), top = el("div", "top");
    top.appendChild(el("span", "nm", g.label));
    top.appendChild(el("span", "badge k", g.reason || "flagged"));
    r.appendChild(top);
    r.appendChild(el("div", "why", g.live.length
      ? "Supplied by " + g.live.map(nameOf).join(", ") +
        (g.planned.length ? " · planned in " + g.planned.map(nameOf).join(", ") : "")
      : (g.planned.length ? "Only planned: " + g.planned.map(nameOf).join(", ")
                          : "No system supplies this yet")));
    rows.appendChild(r);
  });
  root.appendChild(rows);
}

function render() {
  const root = $("#view"); root.textContent = "";
  document.querySelectorAll(".tab").forEach(t =>
    t.setAttribute("aria-selected", t.dataset.v === view ? "true" : "false"));
  ({ map: renderMap, matrix: renderMatrix, systems: renderSystems, gaps: renderGaps })[view](root);
}

document.querySelectorAll(".tab").forEach(t =>
  t.addEventListener("click", () => { view = t.dataset.v; picked = null; render(); }));
$("#q").addEventListener("input", e => { q = e.target.value.trim().toLowerCase(); render(); });
render();
"""


def render_html(payload: Dict[str, Any], fragment: bool = False) -> str:
    """One file, no external references: inline CSS, inline JS, data in a JSON island.

    `fragment=True` returns everything that lives inside `<body>` and omits the document
    wrapper, for embedding in a docs site or a host that supplies its own `<head>`. The
    `<style>` moves into the fragment rather than being dropped, because a fragment whose
    styling depends on the host is a fragment that renders differently everywhere.

    The data is a `<script type="application/json">` island rather than a JS literal so
    nothing in it can execute, and `</` is escaped so a value can never close the tag
    early. `json.dumps` with `ensure_ascii=False` keeps the file readable and small.
    """
    payload = dict(payload, words=PLAIN_WORDS)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    totals = payload["totals"]
    title = payload["title"] or payload["use_case"]

    kpis = [
        (totals["connectors"], "Source systems",
         f"{totals['connectors_live']} live, {totals['connectors'] - totals['connectors_live']} planned"),
        (totals["concepts"], "Business things",
         f"{totals['concepts_live']} supplied by at least one system"),
        (totals["links"], "System → thing links",
         f"{totals['links_with_model']} backed by a dbt model"
         + (f", {totals['links_unbacked']} without one" if totals["links_unbacked"] else "")),
        (totals["attributes"], "Fields mapped", "raw column → shared meaning"),
        (totals["gaps"], "Flagged for review", "mostly single-supplier"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><span class="n">{n}</span>'
        f'<span class="l">{_esc(label)}</span><span class="h">{_esc(hint)}</span></div>'
        for n, label, hint in kpis
    )

    body = f"""<style>{_CSS}</style>
<div class="wrap">
<h1>{_esc(title)}</h1>
<p class="lede">Different accounting and sales systems call the same thing by different
names — one calls it <code>CustomerNumber</code>, another <code>customer_id</code>. This
page shows the shared vocabulary underneath: every <strong>business thing</strong> the
project tracks, which <strong>source systems</strong> can supply it, and where the gaps
are.</p>
<p class="sub">Generated from <code>{_esc(payload['source'])}</code> by
<code>{_esc(payload['generated_by'])}</code>. Nothing here is inferred — every link is one
the model already declares.</p>

<div class="kpis">{kpi_html}</div>

<div class="bar" role="tablist" aria-label="Views">
  <div class="tabs">
    <button class="tab" data-v="map" role="tab" aria-selected="true">Map</button>
    <button class="tab" data-v="matrix" role="tab" aria-selected="false">Coverage grid</button>
    <button class="tab" data-v="systems" role="tab" aria-selected="false">Source systems</button>
    <button class="tab" data-v="gaps" role="tab" aria-selected="false">Gaps</button>
  </div>
  <input id="q" type="search" placeholder="Search a thing, a field, or a system…"
         aria-label="Search">
  <span class="count" id="count"></span>
</div>

<div class="legend" id="legend">
  <span><i class="dot live"></i> ● Live — a model exists today</span>
  <span><i class="dot planned"></i> ○ Planned — declared, not built</span>
  <span><i class="dot unbacked"></i> ▲ Declared, but no dbt model found</span>
  <span><i class="dot none"></i> · Not supplied by that system</span>
  <span><i class="dot erp"></i> Finance &amp; operations</span>
  <span><i class="dot crm"></i> Sales &amp; customers</span>
</div>

<div id="view"></div>

<footer>
Every relationship drawn here is one the model asserts: which system supplies which
thing, which family a thing belongs to, and which raw column became which shared field.
Foreign keys between things are a different question, answered by
<code>scripts/erd_generator.py</code> from the dbt tests.
</footer>
</div>
<script type="application/json" id="payload">{data}</script>
<script>{_JS}</script>
"""
    if fragment:
        return body
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} — what we track and where it comes from</title>
<meta name="description" content="Every business thing this project tracks, which source systems supply it, and where the gaps are.">
</head>
<body>
{body}</body>
</html>
"""


def _esc(text: Any) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


# =======================================================================================
# CLI
# =======================================================================================


def out_path_for(slug: str) -> Path:
    return OUT_DIR / f"{slug}-ontology.html"


def build_for(slug: str, fragment: bool = False) -> Optional[Tuple[Path, str]]:
    """Rendered HTML for one use-case, or None when it has no ontology index yet."""
    use_case = _paths.use_case_dir(slug)
    if use_case is None:
        return None
    index_path = use_case / "ontology" / "index.json"
    if not index_path.is_file():
        return None
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return out_path_for(slug), render_html(build_payload(index), fragment=fragment)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Render a use-case's ontology and topology as a self-contained HTML page."
    )
    ap.add_argument("--use-case", help="slug under skill-packs/*/use-cases/")
    ap.add_argument("--all", action="store_true", help="every use-case with an ontology index")
    ap.add_argument("--out", type=Path, help="override the output path (single use-case only)")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 1 if the committed page is stale")
    ap.add_argument("--fragment", action="store_true",
                    help="emit only what goes inside <body>, for embedding")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)

    if not args.use_case and not args.all:
        ap.error("pass --use-case <slug> or --all")

    slugs = _paths.all_use_cases() if args.all else [args.use_case]
    results: List[Dict[str, Any]] = []
    stale = 0

    for slug in slugs:
        built = build_for(slug, fragment=args.fragment)
        if built is None:
            results.append({"use_case": slug, "status": "skip",
                            "reason": "no ontology/index.json — run use_case_sync.py --stage ontology"})
            continue
        path, html = built
        if args.out and not args.all:
            path = args.out
        existing = path.read_text(encoding="utf-8") if path.is_file() else None
        changed = existing != html
        if args.check:
            stale += 1 if changed else 0
            results.append({"use_case": slug, "status": "stale" if changed else "current",
                            "path": _rel(path)})
            continue
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
        results.append({
            "use_case": slug, "status": "changed" if changed else "current",
            "path": _rel(path), "bytes": len(html.encode("utf-8")),
        })

    if args.format == "json":
        print(json.dumps({"results": results}, ensure_ascii=False))
    else:
        for row in results:
            extra = row.get("reason") or row.get("path", "")
            size = f"  ({row['bytes'] // 1024} KB)" if "bytes" in row else ""
            print(f"  {row['status']:<8} {row['use_case']:<28} {extra}{size}")
    return 1 if stale else 0


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    sys.exit(main())
