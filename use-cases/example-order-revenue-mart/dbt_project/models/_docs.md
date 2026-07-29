{% docs region %}
Sales region derived from the customer's country code by the mapping owned by Finance
Analytics: EMEA, AMER, or OTHER.

`OTHER` is the deliberate catch-all for an unmapped country. It is never null, so a new
market shows up as an `accepted_values` failure on this column rather than as a
`not_null` failure three models downstream.

Guest checkouts have no customer and therefore no region. Those rows carry a null region
and are still counted in revenue — see `fct_orders.customer_id`.
{% enddocs %}


{% docs order_status %}
The order's business status, normalized from Shopify's `financial_status`.

Precedence: a refund overrides any fulfillment state. An order that shipped and was then
refunded reports `refunded`, because the finance question this mart answers is "what did
we keep", not "what left the warehouse".

A status Shopify introduces that we have not mapped falls through to `unknown` rather
than null. Shopify has added enum values twice; `unknown` turns that into a loud
`accepted_values` failure instead of silent nulls.

Values: `pending`, `paid`, `fulfilled`, `refunded`, `cancelled`, `unknown`.
{% enddocs %}
