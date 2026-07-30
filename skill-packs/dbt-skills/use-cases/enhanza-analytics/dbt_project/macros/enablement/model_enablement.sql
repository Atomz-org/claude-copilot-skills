{#-
    Model enablement
    ================
    Enhanza is multi-tenant: one dbt project builds every customer's warehouse, but each
    customer only connects some data sources. A model must therefore decide, at compile
    time, whether it should exist for the current run. dbt expresses that via the `enabled`
    config; the macros here compute the boolean it needs.

    "Which sources are on" comes from the `is_<source>_enabled` run vars, surfaced through
    global_configs('all_available_sources').

    There are three distinct enablement questions. Each has its own macro so the call site
    states which one it is asking:

      source_is_enabled(model_name)    -> "Is THIS model's own source/layer turned on?"
                                          Used by source-specific models (e.g.
                                          tripletex_bi_dim_accounts_staging cares only that
                                          Tripletex is enabled). The dominant case.

      model_is_provided(common_name)   -> "Does ANY enabled source provide this concept?"
                                          Used by unified erp_bi / logic_bi models that merge
                                          a concept (e.g. 'dim_employees') across sources;
                                          they should build only if at least one enabled
                                          source actually supplies it.

      any_source_enabled(source_names) -> "Is at least one of THESE named sources on?"
                                          Used to guard source-specific blocks inside
                                          hand-written logic_bi models (e.g. an Upsales-only
                                          section).
-#}


{#-
    "Is this model's own source/layer turned on?"
    Derives the source from the model name (text before '_bi_') and returns its
    is_<source>_enabled var. The 'logic' layer has no source of its own, so it follows
    is_erp_enabled.
-#}
{%- macro source_is_enabled(model_name) -%}
    {%- set enabled_var_name = 'is_' ~ model_name.split('_bi_')[0] ~ '_enabled' -%}

    {%- if enabled_var_name == 'is_logic_enabled' -%}
        {{ return(var('is_erp_enabled', False) | as_bool) }}
    {%- else -%}
        {{ return(var(enabled_var_name, False) | as_bool) }}
    {%- endif -%}
{%- endmacro -%}


{#-
    "Does any enabled source provide this concept?"
    Looks up the common name (e.g. 'dim_employees') in each enabled source's
    `included_models` list and returns true if any enabled source supplies it.
-#}
{%- macro model_is_provided(common_name) -%}
    {%- set stripped_name = model_alias(remove_staging_from_name(common_name)) -%}
    {%- set all_sources = global_configs('all_available_sources') -%}

    {%- for source_name, source_cfg in all_sources.items() -%}
        {%- if source_cfg['enabled'] -%}
            {%- if stripped_name in source_cfg.get('included_models', []) -%}
                {{ return(true) }}
            {%- endif -%}
        {%- endif -%}
    {%- endfor -%}

    {{ return(false) }}
{%- endmacro -%}


{#-
    "Is at least one of these named sources on?"
    Gated by is_erp_enabled, returns true if any of the passed source keys is enabled.
-#}
{%- macro any_source_enabled(source_names) -%}
    {#- Gate replicates the original is_enabled branch verbatim: a raw truthiness test on
        is_erp_enabled (no `| as_bool`), to avoid any behaviour change. -#}
    {%- if not var('is_erp_enabled', true) -%}
        {{ return(false) }}
    {%- endif -%}

    {%- set all_sources = global_configs('all_available_sources') -%}
    {%- for source_name, source_cfg in all_sources.items() -%}
        {%- if source_cfg['enabled'] and source_name in source_names -%}
            {{ return(true) }}
        {%- endif -%}
    {%- endfor -%}

    {{ return(false) }}
{%- endmacro -%}
