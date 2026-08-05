{{ config(alias=(model_alias(model.name)), enabled = source_is_enabled(model.name)) }}


select
  cast(invoiceNumber as int64) InvoiceNo
  , cast(i.OrgId as string) || '-' || cast(invoiceNumber as string) InvoiceId
  , date(invoiceDate) InvoiceDate
  , date(deliveryDate) DeliveryDate
  , date(invoiceDueDate) DueDate
  , if(date(invoiceDueDate) < current_date() and amountOutstanding > 0, TRUE, FALSE) IsDue
  , case
    when ehfSendStatus IS NULL or ehfSendStatus = '' then "NotSent"
    when ehfSendStatus IS NOT NULL then case
      when amountOutstanding = 0 then "Paid"
      when amountOutstanding > 0 then case
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 0
        and 15 then "0-15d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 16
        and 30 then "16-30d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 31
        and 45 then "31-45d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 46
        and 60 then "46-60d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 61
        and 90 then "61-90d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) between 91
        and 120 then "91-120d"
        when ABS(DATE_DIFF(current_date(), date(invoiceDueDate), day)) > 120 then ">120d"
        when invoiceDueDate is null then 'NO_DUE_DATE'
        else 'WHAT?'
      end
      else 'WOW??'
    end
    else "[calc_error]"
  end DueStatus
  , array_length(json_extract_array(reminders)) Reminders
  , cast(isCreditNote as STRING) as isCredit
  , if(ehfSendStatus IS NOT NULL AND ehfSendStatus <> '', TRUE, FALSE) Sent
  , json_extract_scalar(currency, '$.code') Currency
  , cast(1 as FLOAT64) CurrencyRate
  , amountExcludingVat Net
  , amount - amountExcludingVat TotalVAT
  , amount TotalToPay
  , amountOutstanding Balance
  , amountRoundoff RoundOff
  , amount Total
  , {{ blank_to_null('invoiceComment') }} Comments
  , {{ blank_to_null('comment') }} Remarks
  , cast(creditedInvoice as string) CreditInvoiceReference
  , {{ blank_to_null('kid') }} InvoiceOCR
  , i.OrgId
  , i.OrgId || '-' || json_extract_scalar(customer, '$.id') CustomerId
from {{ source('tripletex_api', 'invoice') }} i
where invoiceNumber is not null
  and isCredited is not true
