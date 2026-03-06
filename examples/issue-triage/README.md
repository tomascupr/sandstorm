# Issue Triage

Classify, prioritize, and deduplicate incoming bug reports or exported issues with a consistent
JSON output.

## Features Used

- **`output_format`** -- returns severity, labels, next action, and missing information per item
- **`allowed_tools`** -- restricted to `Read`, `Glob`, and `Grep` for safe analysis of uploaded
  issue exports or support transcripts
- **File uploads** -- send JSON, CSV, Markdown, or copied issue exports into the sandbox

## Quick Start

```bash
cd examples/issue-triage
ds "Triage these incoming bug reports for severity, owner, and next action" \
  -f /path/to/issues.json
```

## More Examples

```bash
# Triage support inbox exports
ds "Group these support tickets by root cause and urgency" \
  -f /path/to/support-export.csv

# Review copied issue markdown
ds "Identify duplicates and propose labels for these issues" \
  -f /path/to/open-issues.md

# Find missing reproduction details
ds "Triage these bug reports and flag which ones need follow-up before engineering can act" \
  -f /path/to/bug-reports.json
```

## Sample Output

```json
{
  "summary": "Processed 12 incoming reports. Two require immediate attention, three are likely duplicates, and four need reproduction details.",
  "triaged_items": [
    {
      "id": "BUG-104",
      "title": "Webhook retries stop after process restart",
      "type": "bug",
      "severity": "high",
      "labels": ["bug", "webhooks", "reliability"],
      "suggested_owner": "backend",
      "next_action": "Reproduce with a minimal restart scenario and inspect retry persistence",
      "missing_info": []
    }
  ],
  "duplicates": [
    {
      "primary_id": "BUG-104",
      "duplicate_ids": ["BUG-099"]
    }
  ]
}
```
