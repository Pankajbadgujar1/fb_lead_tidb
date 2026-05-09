-- Run this once in your TiDB dashboard or MySQL client
-- to create the google_ads_leads table

CREATE TABLE IF NOT EXISTS google_ads_leads (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    full_name   VARCHAR(255),
    phone       VARCHAR(50),
    email       VARCHAR(255),
    city        VARCHAR(100),
    campaign    VARCHAR(255),
    ad_id       VARCHAR(100),
    form_id     VARCHAR(100),
    raw_data    JSON,
    source      VARCHAR(50) DEFAULT 'google_ads',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- View all Google Ads leads
-- SELECT * FROM google_ads_leads ORDER BY created_at DESC;
