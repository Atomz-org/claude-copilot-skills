--Purpose: this macro hosts all exceptions, special cases, and other variables to make it more manageable.
--Usage: called in other macros. Return a value (list, string etc.) based on the requested key

{#-
    all_available_sources is the connector registry — the single source of truth for which
    source systems exist and which concepts each one supplies. Five readers depend on it:
    erp_union(), model_is_provided(), any_source_enabled(), add_erp_fields(), and
    source_is_enabled(). A connector with adapter models but no entry here is invisible to
    the unified layer; a concept claimed here with no adapter on disk fails at parse time.
    tests/test_enhanza_connector_registry.py enforces both directions.

    Sources are listed alphabetically. To add one, see CONNECTORS.md.

    Note: comments cannot appear inside the `{% set config = {...} %}` expression below —
    Jinja rejects `{#- -#}` inside a tag — so per-entry notes live here.

      favrit  — `default_currency` deliberately absent. Favrit is multi-currency and the
                tenant default has not been confirmed. add_erp_fields() emits a NULL
                DefaultCurrency for sources without one, same as Tempo. [NEEDS INPUT]

      shopify — `default_currency` is 'SEK' by explicit decision, not by detection. Shopify
                shops are multi-currency and each order carries its own `currency`; the
                adapters pass that through to the Currency column, so DefaultCurrency is
                the tenant fallback only. Revisit if a non-SEK shop is onboarded.

      xledger — `fact_vouchers` was claimed but no xledger_erp_bi_fact_vouchers model
                exists, so erp_bi_fact_vouchers never unioned Xledger while
                model_is_provided('fact_vouchers') answered true for an Xledger-only
                tenant. The claim is removed so the registry matches what is built.
                Restore it in the same commit that adds the adapter.
                [NEEDS INPUT: does Xledger supply vouchers, and should it?]
-#}
{% macro global_configs(key) %}
    {% set config = {
        'all_available_sources': {
            'favrit': {
                'name': 'Favrit',
                'enabled': var('is_favrit_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_accounting',
                    'dim_ratings',
                    'dim_user_locations',
                    'fact_order_rows'
                ]
            },
            'fortnox': {
                'name': 'Fortnox',
                'default_currency': 'SEK',
                'enabled': var('is_fortnox_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_accounts',
                    'dim_articles',
                    'dim_assets_types',
                    'dim_bundle_articles',
                    'dim_company',
                    'dim_cost_centers',
                    'dim_customers',
                    'dim_employees',
                    'dim_expenses',
                    'dim_financial_years',
                    'dim_labels',
                    'dim_meta_data',
                    'dim_pricelists',
                    'dim_prices',
                    'dim_projects',
                    'dim_stockpoints',
                    'dim_supplier_invoice_files',
                    'dim_supplier_items',
                    'dim_suppliers',
                    'dim_voucher_series',
                    'fact_absence_transactions',
                    'fact_asset_rows',
                    'fact_assets',
                    'fact_attendance_transactions',
                    'fact_budgets',
                    'fact_contract_rows',
                    'fact_contracts',
                    'fact_employee_schedules',
                    'fact_employee_wages',
                    'fact_incoming_goods',
                    'fact_invoice_accruals',
                    'fact_invoice_payments',
                    'fact_invoice_rows',
                    'fact_invoices',
                    'fact_locked_period',
                    'fact_offer_rows',
                    'fact_offers',
                    'fact_order_rows',
                    'fact_orders',
                    'fact_production_orders',
                    'fact_purchase_orders',
                    'fact_salary_transactions',
                    'fact_stockbalance',
                    'fact_stocktakings',
                    'fact_supplier_invoice_accruals',
                    'fact_supplier_invoice_rows',
                    'fact_supplier_invoices',
                    'fact_time_reporting_registrations',
                    'fact_vouchers',
                    'fact_rolling_sum'
                ]
            },
            'seventime': {
                'name': 'SevenTime',
                'default_currency': 'SEK',
                'enabled': var('is_seventime_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_articles',
                    'dim_company',
                    'dim_customers',
                    'dim_financial_years',
                    'fact_invoice_rows',
                    'fact_invoices',
                    'fact_offers',
                    'fact_time_reporting_registrations',
                    'fact_work_orders'
                ]
            },
            'shopify': {
                'name': 'Shopify',
                'default_currency': 'SEK',
                'enabled': var('is_shopify_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_articles',
                    'dim_customers',
                    'fact_order_rows',
                    'fact_orders'
                ]
            },
            'tempo': {
                'name': 'Tempo',
                'enabled': var('is_tempo_enabled', 'False') | as_bool,
                'included_models': [
                    'fact_time_reporting_registrations'
                ]
            },
            'tripletex': {
                'name': 'Tripletex',
                'default_currency': 'NOK',
                'enabled': var('is_tripletex_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_accounts',
                    'dim_company',
                    'dim_cost_centers',
                    'dim_customers',
                    'dim_financial_years',
                    'dim_projects',
                    'dim_suppliers',
                    'dim_voucher_series',
                    'fact_invoices',
                    'fact_vouchers'
                ]
            },
            'upsales': {
                'name': 'Upsales',
                'default_currency': 'SEK',
                'enabled': var('is_upsales_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_articles',
                    'dim_company',
                    'dim_customers',
                    'dim_financial_years',
                    'fact_activities',
                    'fact_appointments',
                    'fact_opportunities',
                    'fact_opportunity_rows',
                    'fact_order_rows',
                    'fact_orders'
                ]
            },
            'visma_eaccounting': {
                'name': 'Visma e-Accounting',
                'default_currency': 'SEK',
                'enabled': var('is_visma_eaccounting_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_accounts',
                    'dim_articles',
                    'dim_company',
                    'dim_cost_centers',
                    'dim_customers',
                    'dim_financial_years',
                    'dim_projects',
                    'fact_invoice_rows',
                    'fact_invoices',
                    'fact_vouchers'
                ]
            },
            'visma_economic': {
                'name': 'Visma e-conomic',
                'default_currency': 'DKK',
                'enabled': var('is_visma_economic_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_accounts',
                    'dim_articles',
                    'dim_company',
                    'dim_customers',
                    'dim_financial_years',
                    'dim_suppliers',
                    'fact_invoice_rows',
                    'fact_invoices',
                    'fact_orders',
                    'fact_vouchers'
                ]
            },
            'xledger': {
                'name': 'Xledger',
                'default_currency': 'NOK',
                'enabled': var('is_xledger_enabled', 'False') | as_bool,
                'included_models': [
                    'dim_accounts',
                    'dim_cost_centers',
                    'dim_financial_years',
                    'dim_projects'
                ]
            }
        },

        'erp_columns_rename_and_cast_list': {
            'example endpoint': {
                'new column name|all original columns to rename': 'DATA TYPE for (cast as) function'
            },
            'dim_accounts': {
                'BASAccountClassId|AccountClassId' : None,
                'BASAccountClass|AccountClass' : None,
                'BASMainAccountId|MainAccountId' : None,
                'BASMainAccount|MainAccount' : None,
                'BASSubAccountId|SubAccountId' : None,
                'BASSubAccount|SubAccount' : None,
                'Number' : 'INT64'
            },
            'dim_articles': {
                'ArticleName|Description' : None
            },
            'dim_company': {
                'ErpOrgId|FortnoxId|SeventimeId|TripletexId|VismaId|UpsalesId' : None
            },
            'dim_financial_years': {
                'Id' : 'STRING'
            },
            'dim_stockpoints': {
                'isUsingCompanyAddress|UsingCompanyAddress' : None
            },
            'dim_suppliers': {
                'isActive|Active' : 'BOOL'
            },
            'fact_budgets': {
                'BudgetAmount|Amount' : None
            },
            'fact_incoming_goods': {
                'Date|date' : None,
                'DirectCost|directCost' : None,
                'OrderedQuantity|orderedQuantity' : None,
                'RemainingOrderedQuantity|remainingOrderedQuantity' : None,
                'ReceivedQuantity|receivedQuantity' : None,
                'BackOrderQuantity|backOrderQuantity' : None,
                'TakenQuantity|takenQuantity' : None,
                'InvoicedQuantity|invoicedQuantity' : None,
                'Batch|batch' : None,
                'isReleased|released' : None,
                'isCompleted|completed' : None,
                'isVoided|voided' : None,
                'Note|note' : None
            },
            'fact_purchase_orders': {
                'Id|id' : None,
                'OrderDate|orderDate' : None,
                'DeliveryDate|deliveryDate' : None,
                'PurchaseType|purchaseType' : None,
                'OurReference|ourReference' : None,
                'YourReference|yourReference' : None,
                'ResponseSate|responseState' : None,
                'PurchaseOrderState|purchaseOrderState' : None,
                'MessageToSupplier|messageToSupplier' : None,
                'Note|note' : None,
                'OrderedQuantity|orderedQuantity' : None,
                'ItemUnit|itemUnit' : None,
                'Price|price' : None,
                'OrderRowValue|orderRowValueSek' : None,
                'OrderRowValue_OrigCurrency|orderRowValue' : None,
                'CurrencyRate|currencyRate' : None,
                'RemainingOrderedQuantity|remainingOrderedQuantity' : None,
                'ReceivedQuantity|receivedQuantity' : None,
                'BackOrderQuantity|backOrderQuantity' : None,
                'StockPointId|stockPointId' : None,
                'PurchaseOrderId|purchaseOrderId' : None
            },
            'fact_vouchers': {
                'Amount|Balance' : 'FLOAT64',
                'Account' : 'INT64'
            }
        },
        
        'id_erp_exceptions': [
            'list of columns that should NOT receive ColumnIdERP version',
            'BASAccountClassId', 
            'BASMainAccountId', 
            'BASSubAccountId', 
            'ErpOrgId', 
            'Id', 
            'ModeOfPaymentAccountId', 
            'RegistrationCodeId', 
            'InvoiceBasisId', 
            'ChildId', 
            'AccountCategoryID',
            'AccountCategoryBreakdownID'
        ],
        
        'naming_special_cases': {
            'name of the file in DBT': 'specific user-facing name for BigQuery',
            'fortnox_bi_fact_incoming_goods': 'fact_incominggoods',
            'fortnox_bi_fact_purchase_orders': 'fact_purchaseorders',
            'fortnox_bi_fact_rolling_sum': 'rolling_sum',
            'fortnox_flat_incoming_goods': 'incominggoods',
            'fortnox_reports_rolling_sum_report': 'rolling_sum',
            'fortnox_bi_fact_incoming_goods_staging': 'fortnox_bi_fact_incominggoods',
            'fortnox_bi_fact_purchase_orders_staging': 'fact_purchaseorders',
            'fortnox_bi_fact_rolling_sum_staging': 'fortnox_bi_rolling_sum',
            'fortnox_flat_incoming_goods_staging': 'fortnox_flat_incominggoods',
            'fortnox_reports_rolling_sum_report_staging': 'fortnox_reports_rolling_sum'
        },
        
        'special_enabled_prefixes': [
            'erp_bi', 
            'logic_bi'
        ],
        
        'demo_multi': 3,
        'demo_max_year': 2023
    } %}

    {% if key in config %}
        {{ return(config[key]) }}
    {% else %}
        {{ exceptions.raise_compiler_error("global_configs: key '" ~ key ~ "' not found.") }}
    {% endif %}
{% endmacro %}