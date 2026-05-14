# CRM Leads Submit API

This API lets any landing page submit a lead into the CRM. One request creates the complete CRM pipeline:

- `crm_Contacts`
- `crm_Opportunities`
- `ContactsToOpportunities`
- `crm_Leads`

## Endpoint

```http
POST https://fb-leads-tidb.vercel.app/api/crm/leads/submit
```

## Authentication

Authentication is controlled by the backend environment variable:

```env
CRM_INGEST_API_KEY=your-secret-key
```

If `CRM_INGEST_API_KEY` is configured, every request must include:

```http
X-API-Key: your-secret-key
```

If `CRM_INGEST_API_KEY` is not configured, the API accepts requests without this header.

## Headers

```http
Content-Type: application/json
X-API-Key: your-secret-key  # current key = sk_live_9f3b7a2c8d1e_my_crm_ingest_key
```

## Required Fields

At minimum, send:

```json
{
  "full_name": "Rahul Sharma",
  "email": "rahul@example.com",
  "phone": "+919999999999"
}
```

Rules:

- `full_name` or `name` is required.
- At least one of `email` or `phone` is required.
- If `email` is provided, it must contain `@`.

## Recommended Request Body

```json
{
  "source_platform": "twitter",
  "external_lead_id": "client-lead-001",
  "full_name": "Rahul Sharma",
  "email": "rahul@example.com",
  "phone": "+919999999999",
  "city": "Pune",
  "state": "Maharashtra",
  "country": "India",
  "message": "Interested in term life insurance",
  "plan_type": "Term Life Insurance",
  "coverage": "50 Lakhs",
  "income": "6-10 LPA",
  "utm_source": "twitter",
  "utm_medium": "paid",
  "utm_campaign": "life-insurance",
  "utm_content": "creative-1",
  "click_id": "twitter-click-id-123"
}
```

## Field Reference

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `source_platform` | string | No | Example: `twitter`, `facebook`, `google`, `landing_page`. Defaults to `landing_page`. |
| `external_lead_id` | string | No | Unique ID from the client/landing page. If omitted, backend generates one. |
| `full_name` | string | Yes* | Required unless `name` is sent. |
| `name` | string | Yes* | Alternative to `full_name`. |
| `email` | string | Yes* | Required if `phone` is missing. |
| `phone` | string | Yes* | Required if `email` is missing. |
| `phone_number` | string | No | Alternative to `phone`. |
| `mobile_phone` | string | No | Alternative to `phone`. |
| `city` | string | No | Saved into CRM contact, opportunity, and lead fields where available. |
| `state` | string | No | Saved into CRM contact and lead fields. |
| `country` | string | No | Saved into CRM contact and lead fields. |
| `address` | string | No | Saved into CRM contact and lead fields. |
| `company` | string | No | Saved into CRM contact/lead fields. |
| `job_title` | string | No | Saved into CRM contact/lead fields. |
| `message` | string | No | Used in CRM descriptions and notes. |
| `plan_type` | string | No | Can be used as opportunity name/headline. |
| `coverage` | string | No | Preserved in raw/custom data. |
| `income` | string | No | Preserved in raw/custom data. |
| `budget` | number/string | No | Saved as opportunity budget when numeric. |
| `expected_revenue` | number/string | No | Saved as opportunity expected revenue when numeric. |
| `currency` | string | No | Example: `INR`, `USD`. |
| `utm_source` | string | No | Marketing attribution. |
| `utm_medium` | string | No | Marketing attribution. |
| `utm_campaign` | string | No | Marketing attribution and campaign reference. |
| `utm_term` | string | No | Marketing attribution. |
| `utm_content` | string | No | Marketing attribution. |
| `click_id` | string | No | Any ad click ID. |
| `twclid` | string | No | Twitter/X click ID. Alternative to `click_id`. |
| `gclid` | string | No | Google click ID. Alternative to `click_id`. |
| `fbclid` | string | No | Facebook click ID. Alternative to `click_id`. |
| `custom_fields` | object | No | Extra landing-page fields to preserve in CRM JSON fields. |

## Success Response

Status: `201 Created`

```json
{
  "success": true,
  "source_platform": "twitter",
  "external_lead_id": "client-lead-001",
  "contact_id": "twitter-contact-client-lead-001",
  "opportunity_id": "twitter-opportunity-client-lead-001",
  "lead_id": "8b7d3d94-0f65-4b22-9dd4-98a4a53df9c1"
}
```

## Error Responses

Missing or invalid API key:

Status: `401 Unauthorized`

```json
{
  "success": false,
  "error": "Invalid API key."
}
```

Validation error:

Status: `400 Bad Request`

```json
{
  "success": false,
  "error": "full_name or name is required."
}
```

Server/database error:

Status: `500 Internal Server Error`

```json
{
  "success": false,
  "error": "Database error message"
}
```

## JavaScript Fetch Example

```javascript
async function submitLead() {
  const response = await fetch("https://fb-leads-tidb.vercel.app/api/crm/leads/submit", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": "your-secret-key"
    },
    body: JSON.stringify({
      source_platform: "twitter",
      external_lead_id: "client-lead-001",
      full_name: "Rahul Sharma",
      email: "rahul@example.com",
      phone: "+919999999999",
      city: "Pune",
      message: "Interested in term life insurance",
      utm_source: "twitter",
      utm_medium: "paid",
      utm_campaign: "life-insurance"
    })
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || "Lead submission failed");
  }

  return data;
}
```

## PowerShell Test

Without API key:

```powershell
Invoke-RestMethod -Uri "https://fb-leads-tidb.vercel.app/api/crm/leads/submit" -Method POST -ContentType "application/json" -Body '{"source_platform":"twitter","external_lead_id":"client-lead-001","full_name":"Rahul Sharma","email":"rahul@example.com","phone":"+919999999999","city":"Pune","message":"Interested in term life insurance","utm_source":"twitter","utm_medium":"paid","utm_campaign":"life-insurance"}'
```

With API key:

```powershell
Invoke-RestMethod -Uri "https://fb-leads-tidb.vercel.app/api/crm/leads/submit" -Method POST -Headers @{"X-API-Key"="your-secret-key"} -ContentType "application/json" -Body '{"source_platform":"twitter","external_lead_id":"client-lead-001","full_name":"Rahul Sharma","email":"rahul@example.com","phone":"+919999999999","city":"Pune","message":"Interested in term life insurance","utm_source":"twitter","utm_medium":"paid","utm_campaign":"life-insurance"}'
```

## cURL Test

```bash
curl -X POST "https://fb-leads-tidb.vercel.app/api/crm/leads/submit" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{
    "source_platform": "twitter",
    "external_lead_id": "client-lead-001",
    "full_name": "Rahul Sharma",
    "email": "rahul@example.com",
    "phone": "+919999999999",
    "city": "Pune",
    "message": "Interested in term life insurance",
    "utm_source": "twitter",
    "utm_medium": "paid",
    "utm_campaign": "life-insurance"
  }'
```

## OpenAPI / Swagger Spec

Copy the YAML below into https://editor.swagger.io/ or Swagger UI.

```yaml
openapi: 3.0.3
info:
  title: CRM Leads Submit API
  version: 1.0.0
  description: Submit landing-page leads into CRM Contacts, Opportunities, and Leads.
servers:
  - url: https://fb-leads-tidb.vercel.app
paths:
  /api/crm/leads/submit:
    post:
      summary: Submit a landing-page lead
      description: Creates or updates CRM contact and opportunity records, links them, and creates a CRM lead.
      operationId: submitCrmLead
      security:
        - ApiKeyAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/LeadSubmitRequest"
            examples:
              twitterLifeInsuranceLead:
                summary: Twitter/X life insurance lead
                value:
                  source_platform: twitter
                  external_lead_id: client-lead-001
                  full_name: Rahul Sharma
                  email: rahul@example.com
                  phone: "+919999999999"
                  city: Pune
                  state: Maharashtra
                  country: India
                  message: Interested in term life insurance
                  plan_type: Term Life Insurance
                  coverage: 50 Lakhs
                  income: 6-10 LPA
                  utm_source: twitter
                  utm_medium: paid
                  utm_campaign: life-insurance
                  utm_content: creative-1
                  click_id: twitter-click-id-123
      responses:
        "201":
          description: Lead saved successfully
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/LeadSubmitSuccess"
        "400":
          description: Validation error
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
        "401":
          description: Invalid API key
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
        "500":
          description: Server or database error
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
components:
  securitySchemes:
    ApiKeyAuth:
      type: apiKey
      in: header
      name: X-API-Key
      description: Required only when CRM_INGEST_API_KEY is configured on the backend.
  schemas:
    LeadSubmitRequest:
      type: object
      properties:
        source_platform:
          type: string
          example: twitter
        external_lead_id:
          type: string
          example: client-lead-001
        full_name:
          type: string
          example: Rahul Sharma
        name:
          type: string
          example: Rahul Sharma
        email:
          type: string
          format: email
          example: rahul@example.com
        phone:
          type: string
          example: "+919999999999"
        phone_number:
          type: string
          example: "+919999999999"
        mobile_phone:
          type: string
          example: "+919999999999"
        city:
          type: string
          example: Pune
        state:
          type: string
          example: Maharashtra
        country:
          type: string
          example: India
        address:
          type: string
          example: Baner, Pune
        company:
          type: string
          example: Example Pvt Ltd
        job_title:
          type: string
          example: Manager
        message:
          type: string
          example: Interested in term life insurance
        plan_type:
          type: string
          example: Term Life Insurance
        coverage:
          type: string
          example: 50 Lakhs
        income:
          type: string
          example: 6-10 LPA
        budget:
          oneOf:
            - type: number
            - type: string
          example: 50000
        expected_revenue:
          oneOf:
            - type: number
            - type: string
          example: 50000
        currency:
          type: string
          example: INR
        utm_source:
          type: string
          example: twitter
        utm_medium:
          type: string
          example: paid
        utm_campaign:
          type: string
          example: life-insurance
        utm_term:
          type: string
          example: insurance quote
        utm_content:
          type: string
          example: creative-1
        click_id:
          type: string
          example: click-id-123
        twclid:
          type: string
          example: twitter-click-id-123
        gclid:
          type: string
          example: google-click-id-123
        fbclid:
          type: string
          example: facebook-click-id-123
        custom_fields:
          type: object
          additionalProperties: true
          example:
            age: 32
            smoker: No
      anyOf:
        - required: [full_name]
        - required: [name]
      description: At least one of email or phone is also required.
    LeadSubmitSuccess:
      type: object
      properties:
        success:
          type: boolean
          example: true
        source_platform:
          type: string
          example: twitter
        external_lead_id:
          type: string
          example: client-lead-001
        contact_id:
          type: string
          example: twitter-contact-client-lead-001
        opportunity_id:
          type: string
          example: twitter-opportunity-client-lead-001
        lead_id:
          type: string
          example: 8b7d3d94-0f65-4b22-9dd4-98a4a53df9c1
    ErrorResponse:
      type: object
      properties:
        success:
          type: boolean
          example: false
        error:
          type: string
          example: full_name or name is required.
```
