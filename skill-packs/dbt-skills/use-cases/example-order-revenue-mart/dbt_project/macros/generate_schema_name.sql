{#
    Custom schema names returned verbatim — but only for targets that have explicitly
    declared their environment is a separate database, and only after that claim is
    checked.

    dbt's default is `<target_schema>_<custom_schema>`, so a dev run of a model configured
    into `marts` lands in `dbt_alice_marts`. Almost every team overrides that, and the
    override is correct — provided dev and prod are not the same database. Where they are,
    verbatim names mean a laptop `dbt build` writes straight into production's `marts`.
    A comment saying "delete this macro if your environments share a database" does not
    prevent that; nobody reads a macro header before running dbt.

    So the decision is encoded instead, with two fail-closed guards:

    1. Opt-in allowlist. A target absent from `isolated_database_targets` gets dbt's
       prefixing. Adding a target to profiles.yml cannot silently inherit verbatim
       schemas — someone has to make the isolation claim in writing, in version control.

    2. The claim is verified, not trusted. If an isolated target resolves to a database
       named in `production_databases` and is not `production_target`, the run aborts at
       parse time. That is what catches DBT_DUCKDB_PATH or DBT_BQ_PROJECT being repointed
       at production — the failure mode a comment cannot stop.

    All three vars live in dbt_project.yml. Declaring none of them gives you dbt's default
    prefixing everywhere, which is the safe default: this macro cannot make a project less
    safe than not having it.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set isolated_targets  = var('isolated_database_targets', []) -%}
    {%- set production_dbs    = var('production_databases', []) | map('lower') | list -%}
    {%- set production_target = var('production_target', none) -%}

    {%- if custom_schema_name is none -%}
        {{ target.schema }}

    {%- elif target.name in isolated_targets -%}

        {%- if target.name != production_target
               and (target.database or '') | lower in production_dbs -%}
            {{ exceptions.raise_compiler_error(
                "Target '" ~ target.name ~ "' is configured for verbatim custom schema names, "
                ~ "but it resolves to production database '" ~ target.database ~ "'. Verbatim "
                ~ "schemas in a shared database mean this run would write directly into "
                ~ "production tables. Repoint the target at a non-production database, or "
                ~ "remove it from `isolated_database_targets` in dbt_project.yml so it gets "
                ~ "dbt's <target_schema>_<custom_schema> prefixing instead."
            ) }}
        {%- endif -%}

        {{ custom_schema_name | trim }}

    {%- else -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}

{%- endmacro %}
