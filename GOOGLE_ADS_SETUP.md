# Google Ads Lead Form -> CRM Opportunities Setup

## What the webhook does

`POST /api/google-leads` receives Google Ads lead form submissions and saves them directly into `crm_Opportunities`.

The old `google_ads_leads` table is no longer used.

## Webhook URL

```text
POST https://your-project.vercel.app/api/google-leads
```

## Environment Variables

Required:

```text
GOOGLE_WEBHOOK_TOKEN=<secret key configured in Google Ads>
```

Optional CRM defaults used for foreign-key columns:

```text
CRM_DEFAULT_USER_ID=<Users.id>
CRM_DEFAULT_ACCOUNT_ID=<crm_Accounts.id>
CRM_DEFAULT_CAMPAIGN_ID=<crm_campaigns.id>
CRM_DEFAULT_SALES_STAGE_ID=<crm_Opportunities_Sales_Stages.id>
CRM_DEFAULT_OPPORTUNITY_TYPE_ID=<crm_Opportunities_Type.id>
```

Leave optional defaults empty if you do not want to set those CRM references.

## Stored Fields

Google Ads lead data is mapped into `crm_Opportunities`:

```text
name                Google Ads Lead - <name/email/phone/lead_id>
clientName          full name
phone               phone number
email               email
city                city/location/region
ad_id               Google ad_id or creative_id
form_id             Google form_id or lead_form_id
source              google_ads
category            google_ads
description         lead_id/campaign_id/ad_id/form_id summary
custom_fields_data  parsed Google Ads fields and metadata
raw_data            full original webhook payload
```

The CRM `campaign` column is a foreign key, so the webhook uses `CRM_DEFAULT_CAMPAIGN_ID` there. The raw Google `campaign_id` is preserved in `description`, `custom_fields_data`, and `raw_data`.

## View Google Ads Opportunities

```sql
SELECT id, name, clientName, phone, email, city, ad_id, form_id, createdAt
FROM crm_Opportunities
WHERE source = 'google_ads'
ORDER BY createdAt DESC;
```
