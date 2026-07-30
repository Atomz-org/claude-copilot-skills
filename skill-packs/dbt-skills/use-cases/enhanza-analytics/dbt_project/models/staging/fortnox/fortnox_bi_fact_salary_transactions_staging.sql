{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

select
  st.OrgId
  , st.OrgId || '-' || st.EmployeeId EmployeeId
  , Date
  , cast(SalaryCode as Int64) SalaryCode
  , cast(st.Number as float64) NumberOfUnits
  , cast(Amount as float64) AmountPerUnit
  , cast(Total as float64) Total
  , {{ blank_to_null('Expense') }} ExpenseDetails
  , cast(VAT as float64) VAT
  , {{ blank_to_null('TextRow') }} Comments
  , st.OrgId || '-' || {{ blank_to_null('Expense') }} ExpenseId
  , st.OrgId || '-' || fy.Id || '-' || a.Number AccountId
  , st.OrgId || '-' || coalesce({{ blank_to_null('st.CostCenter') }}, {{ blank_to_null('ee.CostCenter') }}) CostCenterId
  , st.OrgId || '-' || coalesce({{ blank_to_null('st.Project') }}, {{ blank_to_null('ee.Project') }}) ProjectId
from {{ source('fortnox_api', 'salary_transactions') }} st
left join {{ source('fortnox_api', 'financial_years') }} fy
  on fy.OrgId = st.OrgId
  and st.Date between fy.FromDate and fy.ToDate
left join {{ source('fortnox_api', 'expenses') }} e
  on e.Code = st.Expense
  and e.OrgId = st.OrgId
left join {{ source('fortnox_api', 'accounts') }} a
  on a.OrgId = st.OrgId
  and a.Year = fy.Id
  and a.Number = e.Account
left join {{ source('fortnox_api', 'employees') }} ee
  on ee.OrgId = st.OrgId
  and ee.EmployeeId = st.EmployeeId