{{ config(alias=(model_alias(model.name))) }}
select
  '1111111111' OrgId
  , cast(null as string) Address
  , cast(null as string) BG
  , cast(null as string) BIC
  , cast(null as string) BranchCode
  , 'Stockholm' City
  , cast(null as string) ContactFirstName
  , cast(null as string) ContactLastName
  , 'Sweden' Country
  , 'SE' CountryCode
  , cast(round(rand() * 100000, 0) as INT64) DatabaseNumber
  , cast(null as string) Domicile
  , cast(null as string) Email
  , cast(null as string) Fax
  , cast(null as string) IBAN
  , 'Demo company #1' Name
  , '111111-1111' OrganizationNumber
  , cast(null as string) PG
  , cast(null as string) Phone1
  , cast(null as string) Phone2
  , TRUE TaxEnabled
  , cast(null as string) VATNumber
  , cast(null as string) VisitAddress
  , cast(null as string) VisitCity
  , cast(null as string) VisitCountry
  , cast(null as string) VisitCountryCode
  , cast(null as string) VisitName
  , cast(null as string) VisitZipCode
  , cast(null as string) WWW
  , cast(round(rand() * 100000, 0) as string) ZipCode
  , current_timestamp() ENZ_CREATED_AT
  , cast(null as timestamp) ENZ_MODIFIED_AT
  , current_timestamp() ENZ_SYNC_TS
  , 'Success' ENZ_DEBUG_INFO