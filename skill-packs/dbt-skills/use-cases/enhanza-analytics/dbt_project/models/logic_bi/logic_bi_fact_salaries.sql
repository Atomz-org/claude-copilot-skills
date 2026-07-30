{%- set included_sources = ['fortnox'] -%}

{{ config(
    alias=(model_alias(model.name)),
    enabled = (any_source_enabled(included_sources) | as_bool)
) }}

with transactions as (
  select
    'Attendance' TransactionType 
    , Date
    , Hours
    , CauseCode
    , CauseCodeName
    , OrgIdERP OrgId
    , EmployeeIdERP EmployeeId
    , CostCenterIdERP CostCenterId
    , ProjectIdERP ProjectId
    , DataSource
    , DefaultCurrency
  from {{ ref('erp_bi_fact_attendance_transactions') }}
  union all
  select 
    'Absence' TransactionType 
    , Date
    , if(Hours<>0, Hours, Extent/100*8) Hours
    , CauseCode
    , CauseCodeName
    , OrgIdERP OrgId
    , EmployeeIdERP EmployeeId
    , CostCenterIdERP CostCenterId
    , ProjectIdERP ProjectId
    , DataSource
    , DefaultCurrency
  from {{ ref('erp_bi_fact_absence_transactions') }}
)

-- , vouchers as (
--   select 
--     'AccountVouchers' TransactionType
--     , v.TransactionDate Date
--     , null SalaryCode
--     , cast(null as float64) NumberOfUnits
--     , cast(null as float64) AmountPerUnit
--     , cast(null as float64) TotalSalary
--     , cast(null as float64) SalaryVat
--     , v.Description Comments
--     , cast(null as float64) RegisteredHours	
--     , cast(null as string) CauseCode	
--     , cast(null as string) CauseCodeName	
--     , sum(Amount) SalaryAccountsBalance	
--     , v.OrgIdERP OrgId
--     , 'AllEmplyees' EmployeeId
--     , v.CostCenterIdERP CostCenterId
--     , v.ProjectIdERP ProjectId
--     , v.DataSource
--     , v.DefaultCurrency
--   from {{ ref('erp_bi_fact_vouchers') }} v
--   left join {{ ref('erp_bi_dim_accounts') }} a
--     on a.AccountId=v.AccountId
--   -- joining global chart of accounts and current mapping to get new filtering
--   left join {{ ref('categories_x_mapping') }} cxm
--     on cxm.DimensionIdERP = split(a.AccountId, '-')[offset(0)] || '-' || a.Number
--   where cxm.Level2ID in ('2-1010') --staff costs
--   group by 1,2,3,4,5,6,7,8,9,10,11,13,14,15,16,17,18
-- )

, fin as (
  select 
    coalesce(t.TransactionType, 'SalaryPayment') TransactionType
    , coalesce(st.Date, t.Date) Date
    , cast(SalaryCode as string) SalaryCode
    , NumberOfUnits
    , AmountPerUnit
    , Total TotalSalary
    , VAT SalaryVat
    , Comments
    , t.Hours RegisteredHours
    , t.CauseCode
    , t.CauseCodeName
    -- , null SalaryAccountsBalance
    , coalesce(st.OrgIdERP, t.OrgId) OrgId
    , coalesce(st.EmployeeIdERP, t.EmployeeId) EmployeeId
    , coalesce(st.CostCenterIdERP, t.CostCenterId) CostCenterId
    , coalesce(st.ProjectIdERP, t.ProjectId) ProjectId
    , coalesce(st.DataSource, t.DataSource) DataSource
    , coalesce(st.DefaultCurrency, t.DefaultCurrency) DefaultCurrency
  from {{ ref('erp_bi_fact_salary_transactions') }} st
  full outer join transactions t
    on t.EmployeeId=st.EmployeeIdERP
    and coalesce(t.CostCenterId, 'null')=coalesce(st.CostCenterIdERP, 'null')
    and coalesce(t.ProjectId, 'null')=coalesce(st.ProjectIdERP, 'null')
    and t.Date=st.Date
  -- union all 
  --   select * from vouchers
)

select * from fin
order by `Date` desc