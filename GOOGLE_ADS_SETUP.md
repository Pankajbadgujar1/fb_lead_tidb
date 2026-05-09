# Google Ads Lead Form → TiDB Setup

## What was added to your existing project

1. `api/google_ads_webhook.py` — new file with all Google Ads webhook logic
2. `api/index.py` — 6 lines added at the bottom to register the new routes
3. `setup_google_leads_table.sql` — run once in TiDB to create the table

## Your new webhook URL (after Vercel deploy)

    POST https://your-project.vercel.app/api/google-leads

## Steps to deploy

### 1. Add env variable to Vercel
Go to Vercel → Your Project → Settings → Environment Variables
Add: GOOGLE_WEBHOOK_TOKEN = any secret string you choose (e.g. "my_google_secret_123")

### 2. Deploy to Vercel
    git add .
    git commit -m "add google ads lead form webhook"
    git push

Vercel auto-deploys from your GitHub push.

### 3. Create TiDB table (optional — auto-creates on first request)
Run setup_google_leads_table.sql in your TiDB dashboard.

### 4. Add webhook URL in Google Ads
Google Ads → Tools & Settings → Conversions → Lead form asset
→ Webhook URL: https://your-project.vercel.app/api/google-leads
→ Key: GOOGLE_WEBHOOK_TOKEN value you set in step 1
→ Click "Send test data" → should show 200 OK

## How lead data flows

1. User fills Google Ads lead form
2. Google sends POST to your webhook URL
3. Your code extracts: full_name, phone, email, city, campaign_id, ad_id, form_id
4. Data is saved to TiDB → google_ads_leads table

## View your leads in TiDB

    SELECT full_name, phone, email, city, created_at
    FROM google_ads_leads
    ORDER BY created_at DESC;
