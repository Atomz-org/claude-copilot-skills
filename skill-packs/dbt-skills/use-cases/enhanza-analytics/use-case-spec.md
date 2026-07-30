# Use-Case Spec — Enhanza Analytics

**Slug:** enhanza-analytics  
**Requested by:** Enhanza Analytics team  
**Author:** Analytics Engineering  
**Date:** 2026-07-30  
**Status:** Draft  
**Verdict:** Build

## 1. The decision

Every product, finance, or operations analyst will consume governed business metrics from the dbt/Cube stack based on trusted logic-layer models instead of hand-built SQL over raw API extracts.

## 2. Consumer

- Consumer: app.enhanza.com and downstream analytics experiences
- Consumer type: dashboard / semantic layer / app endpoint
- Owner: Enhanza data and product teams
- Freshness: data must be available as soon as the warehouse and dbt layers refresh

## 3. Grain

One row per business event per organization per reporting date.

## 4. Source conventions

- Raw API data should stay in a raw stage and be referenced through source definitions.
- The dbt project should use BigQuery-friendly naming and source aliases that mirror the Enhanza repo conventions.
- The logic layer should expose business-friendly metrics that Cube can consume without re-deriving the same logic.

## 5. Example model inventory

| Layer | Example model names |
|---|---|
| BI | `fortnox_bi_fact_invoices`, `fortnox_bi_dim_articles` |
| Unified | `erp_unified_fact_sales` |
| Logic | `fact_sales`, `dim_customer`, `dim_company` |
| Semantic | Cube views and metrics over the logic layer |

## 6. Quality gates

- Source freshness and contract stability
- Unique and not-null tests on business keys
- Relationships between facts and dimensions
- Semantic metric validation against the logic layer

## 7. Feasibility verdict

**Verdict:** Build

The Enhanza repository already documents the flow from raw sources to BigQuery, dbt, Cube, and the app, so this use case is concrete enough to frame and implement.
