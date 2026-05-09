-- Google Ads leads are now stored directly in crm_Opportunities.
-- This file is kept only as a reminder that google_ads_leads is no longer used.

-- View Google Ads opportunities:
SELECT id, name, clientName, phone, email, city, ad_id, form_id, createdAt
FROM crm_Opportunities
WHERE source = 'google_ads'
ORDER BY createdAt DESC;
