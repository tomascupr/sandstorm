# Docs to OpenAPI

Crawl API documentation, extract endpoints and auth requirements, and generate a draft OpenAPI
spec plus a structured summary.

## Features Used

- **WebFetch / WebSearch** -- crawl docs pages directly
- **`output_format`** -- returns a compact endpoint summary and unresolved ambiguities
- **Write tool** -- instructs the agent to save a draft spec to `/home/user/output/openapi.yaml`

## Quick Start

```bash
cd examples/docs-to-openapi
ds "Turn the docs at https://docs.stripe.com/api/subscriptions into a draft OpenAPI spec"
```

## More Examples

```bash
# Internal API portal
ds "Extract a draft OpenAPI spec from our docs portal and note any missing schemas"

# Narrow to a product area
ds "Generate a spec draft for the billing and invoice endpoints only"

# Upgrade existing docs
ds "Read these REST docs, output a draft OpenAPI spec, and list ambiguous fields to review"
```

## Expected Outcome

The agent should:

1. Crawl the documentation pages
2. Infer paths, methods, auth requirements, and major request/response shapes
3. Save a draft spec to `/home/user/output/openapi.yaml`
4. Return a summary with extracted endpoints and open questions

## Sample Output

```json
{
  "summary": "Generated a draft OpenAPI spec with 12 endpoints. Auth and pagination are clear; webhook payload schemas remain ambiguous.",
  "base_url": "https://api.example.com/v1",
  "auth_scheme": "Bearer token",
  "endpoints": [
    {
      "method": "GET",
      "path": "/subscriptions",
      "summary": "List subscriptions"
    }
  ],
  "files_created": ["output/openapi.yaml"],
  "open_questions": ["Webhook event payload examples were not documented"]
}
```
