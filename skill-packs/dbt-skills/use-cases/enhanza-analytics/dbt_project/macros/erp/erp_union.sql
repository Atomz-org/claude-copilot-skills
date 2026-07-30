{#-
    Registry-driven ERP union
    =========================
    Every `erp_bi_<concept>` model unions the same concept across whichever sources the
    tenant has connected. Before this macro, each of those 30 models carried one
    hand-written block per source:

        {% if var('is_fortnox_enabled', false) %}
            {%- do cfg.update({'fortnox': {'query_ref': ref('fortnox_erp_bi_dim_customers')}}) -%}
        {% endif %}

    That is 82 blocks across 30 files, and onboarding a connector meant editing every
    file that the new source contributes to. Worse, nothing tied those blocks to
    global_configs('all_available_sources') — so the two drifted, silently:

      - `favrit` shipped an adapter and a gate in erp_bi_fact_order_rows while being
        absent from the registry entirely;
      - the registry claimed `xledger` provides `fact_vouchers`, but no
        `xledger_erp_bi_fact_vouchers` model was ever written.

    Neither is detectable by reading one file. The registry is now the single source of
    truth: `included_models` decides which sources a concept unions, and adding a
    connector is a registry entry plus its adapter models — no edits here, and no edits
    to any erp_bi model.

    Conventions this relies on:
      - the adapter model for a source is named `<source>_erp_bi_<concept>`;
      - the source key in `all_available_sources` matches the `is_<source>_enabled` var
        and the adapter's filename prefix;
      - `included_models` lists the concept exactly as it appears after the `erp_bi_`
        prefix (e.g. `fact_invoice_rows`).

    An adapter named in `included_models` but missing from disk fails at parse time with
    dbt's "depends on a node named ... which was not found". That is the intended
    behaviour: drift should break the build, not the numbers.
-#}


{#-
    "Which enabled sources provide this concept?"
    Returns a list of source keys, in registry order.
-#}
{%- macro erp_sources_for(concept) -%}
    {%- set all_sources = global_configs('all_available_sources') -%}
    {%- set provided = [] -%}

    {%- for source_name, source_cfg in all_sources.items() -%}
        {%- if source_cfg['enabled'] and concept in source_cfg.get('included_models', []) -%}
            {{ provided.append(source_name) or "" }}
        {%- endif -%}
    {%- endfor -%}

    {{ return(provided) }}
{%- endmacro -%}


{#-
    Emits the full `select ... union all select ...` body for an erp_bi model.
    `concept` defaults to the model's own name with the `erp_bi_` prefix and any
    `_staging` suffix stripped, so `erp_bi_fact_invoices` resolves to `fact_invoices`.
    Pass it explicitly to keep each model self-describing.
-#}
{%- macro erp_union(concept=none) -%}
    {%- set resolved = concept if concept is not none else erp_concept_from_model_name(model.name) -%}
    {%- set cfg = {} -%}

    {%- for source_name in erp_sources_for(resolved) -%}
        {%- do cfg.update({
            source_name: {'query_ref': ref(source_name ~ '_erp_bi_' ~ resolved)}
        }) -%}
    {%- endfor -%}

    {{ configure_erp(cfg) }}
{%- endmacro -%}


{#-
    `erp_bi_fact_invoices` -> `fact_invoices`
    `erp_bi_dim_stockpoints_staging` -> `dim_stockpoints`
-#}
{%- macro erp_concept_from_model_name(model_name) -%}
    {%- set without_prefix = model_name[7:] if model_name.startswith('erp_bi_') else model_name -%}
    {{ return(remove_staging_from_name(without_prefix)) }}
{%- endmacro -%}
