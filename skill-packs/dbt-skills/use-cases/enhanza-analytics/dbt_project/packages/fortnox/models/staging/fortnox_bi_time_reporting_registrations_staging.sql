{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}

with json as(
  select
    id
    , OrgId
    , userId
    , documentId
    , workedDate
    , workedHours
    , chargeHours
    , startTime
    , stopTime
    , invoiceText
    , note
    , createdBy
    , updatedBy
    , invoiceBasisId
    , nonInvoiceable
    , childId
    , createdTime
    , unitCost
    , unitPrice
    , documentType
    , nullif(trim(to_json_string(json_extract(costCenter, '$.id')), '"'), 'null') as costCenterId
    , nullif(trim(to_json_string(json_extract(customer, '$.number')), '"'), 'null') as customerId
    , nullif(trim(to_json_string(json_extract(project, '$.id')), '"'), 'null') as projectId
    , nullif(trim(to_json_string(json_extract(service, '$.id')), '"'), 'null') as articleId
    , nullif(trim(to_json_string(json_extract(registrationCode, '$.id')), '"'), 'null') as registrationCodeId
    , nullif(trim(to_json_string(json_extract(registrationCode, '$.name')), '"'), 'null') as registrationCodeName
    , nullif(trim(to_json_string(json_extract(registrationCode, '$.type')), '"'), 'null') as registrationCodeType
  from {{ source('fortnox_api', 'time_reporting_registrations') }}
  ),
final as(
  select
    OrgId
    , registrationCodeId as RegistrationCodeId
    , registrationCodeName as RegistrationCodeName
    , registrationCodeType as RegistrationCodeType
    , userId as UserNo
    , workedDate as WorkedDate
    , workedHours as WorkedHours
    , chargeHours as ChargeHours
    , startTime as StartTime
    , stopTime as StopTime
    , invoiceText as InvoiceText
    , note as Note
    , createdBy as CreatedBy
    , updatedBy as UpdatedBy
    , invoiceBasisId as InvoiceBasisId
    , nonInvoiceable
    , childId as ChildId
    , createdTime as CreatedTime
    , unitCost as UnitCost
    , unitPrice as UnitPrice
    , initcap(documentType) as DocumentType
    , OrgId || '-' || {{ blank_to_null('documentId') }} as DocumentId
    , id as ID
    , OrgId || '-' || {{ blank_to_null('costCenterId') }} as CostCenterId
    , OrgId || '-' || {{ blank_to_null('customerId') }} as CustomerId
    , OrgId || '-' || {{ blank_to_null('projectId') }} as ProjectId
    , OrgId || '-' || {{ blank_to_null('articleId') }} as ArticleId
    , OrgId || '-' || {{ blank_to_null('userId') }} as UserId
  from json
  )
select *
from final