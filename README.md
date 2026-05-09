# Facebook Leads to TiDB

This is a Flask application that serves as a middle layer for receiving Facebook webhook leads and storing them in TiDB.

By default the webhook now writes each lead into:

- `facebook_leads`
- `crm_Contacts`
- `crm_Opportunities`
- `ContactsToOpportunities`

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Set environment variables in `.env` or Vercel dashboard:
   - `TIDB_HOST`
   - `TIDB_USER`
   - `TIDB_PASSWORD`
   - `TIDB_DATABASE`
   - `FB_PAGE_ACCESS_TOKEN`
   - `FB_VERIFY_TOKEN`
   - Optional CRM defaults for foreign-key-backed fields:
   - `CRM_DEFAULT_USER_ID`
   - `CRM_DEFAULT_ACCOUNT_ID`
   - `CRM_DEFAULT_CONTACT_TYPE_ID`
   - `CRM_DEFAULT_CAMPAIGN_ID`
   - `CRM_DEFAULT_SALES_STAGE_ID`
   - `CRM_DEFAULT_OPPORTUNITY_TYPE_ID`
3. Run locally: `python app.py`

## Deployment

Deploy to Vercel. The app will be available at the Vercel URL.

## Webhook Setup

Set the webhook URL to `https://your-vercel-url.com/` and verify token to `FB_VERIFY_TOKEN`.

## Field Mapping

The webhook uses the Facebook `leadgen_id` to build deterministic CRM ids:

- Contact id: `fb-contact-<leadgen_id>`
- Opportunity id: `fb-opportunity-<leadgen_id>`

This makes repeat webhook deliveries idempotent and updates the same CRM records instead of creating duplicates.

Current mapping:

- Contact: name, email, phone, website, job title, address fields, tags, notes
- Opportunity: name, contact reference, budget, expected revenue, currency, description

If a CRM default env var is not provided, the related foreign-key column is stored as `NULL`.
