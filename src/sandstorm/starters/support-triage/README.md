# Support Triage

Starter for incoming ticket queues, issue exports, and support operations reviews.

## Run it

```bash
ds "Triage these incoming tickets for urgency and next action" -f tickets.json
```

## Example prompts

- Triage these support tickets and recommend the right owner for each one.
- Group these issue exports by likely root cause and urgency.
- Review this backlog and flag which items need a customer reply today.
- Find duplicate reports and identify the items blocked on missing information.

## How to customize

1. Put your team ownership rules, SLA language, or escalation policies into `system_prompt_append`.
2. Replace the prompt examples with the queue reviews you run most often.
3. Only edit the base `system_prompt` if you need a different triage role or rubric.
