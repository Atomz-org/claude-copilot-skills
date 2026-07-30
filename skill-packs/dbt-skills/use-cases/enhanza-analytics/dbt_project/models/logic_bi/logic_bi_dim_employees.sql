{{ config(
    alias=(model_alias(model.name)),
        enabled = any_source_enabled(['fortnox'])
) }}

{% set cxm_cols = ['EmployeeId'] %}

select
  EmployeeIdERP EmployeeId
  , EmployeeName || ' (' || EmployeeNumber || ')' EmployeeName
  , HiringDate
  , FiringDate
  , EmploymentForm
  , case
    when lower(SalaryForm) = 'man' and DataSource = 'Fortnox' then 'Monthly'
    when lower(SalaryForm) = 'tim' and DataSource = 'Fortnox' then 'Hourly'
    else SalaryForm
  end EmployeeSalaryForm
  , JobTitle
  , case
    when PersonelType = 'ARB' and DataSource = 'Fortnox' then 'Blue-collar'
    when PersonelType = 'TJM' and DataSource = 'Fortnox' then 'White-collar'
    else PersonelType
  end PersonelType
  , CurrentMonthlySalary
  , CurrentHourlyPay
  , {{ blank_to_null('PersonalIdentityNumber') }} PersonalIdentityNumber
  , {{ blank_to_null('City') }} EmployeeCity
  , {{ blank_to_null('Country') }} EmployeeCountry
  , ForaType
  , TaxAllowance
  , {{ blank_to_null('ClearingNo') }} ClearingNo
  , d0.DataSource
  , d0.IsActive as isActive
  {{ cxm_select(cxm_cols) }}
from {{ ref('erp_bi_dim_employees') }} d0
{{ cxm_left_join(model_alias("dim_employees"), cxm_cols) }}
order by 1