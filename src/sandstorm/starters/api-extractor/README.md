# API Extractor

Starter for crawling docs and turning them into a draft API summary and spec.

## Run it

```bash
ds "Turn the docs at https://docs.stripe.com/api/subscriptions into a draft OpenAPI spec"
```

## Example prompts

- Crawl this public docs site and draft an OpenAPI file plus endpoint summary.
- Extract the billing endpoints only and list the major schema gaps.
- Read these API docs and tell me what is still ambiguous before we build an integration.
- Generate a starter spec for this internal portal and call out any missing auth details.

## How to customize

1. Add your API conventions, naming rules, or output expectations to `system_prompt_append`.
2. Update the prompts so they match the product areas you document most often.
3. Only change the base `system_prompt` if you want a different extraction strategy.
