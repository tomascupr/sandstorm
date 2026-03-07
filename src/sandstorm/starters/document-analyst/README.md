# Document Analyst

Starter for transcripts, reports, PDFs, decks, and other document-heavy workflows.

## Run it

```bash
ds "Summarize this transcript and extract risks plus next steps" -f notes.txt
```

## Example prompts

- Summarize this customer interview and list the strongest product signals.
- Review this incident write-up and extract the unresolved risks.
- Analyze this report and turn it into an executive update.
- Read this process document and list the decisions we still need to make.

## How to customize

1. Add your preferred output style, team jargon, or review checklist to `system_prompt_append`.
2. Update the prompts to match the kinds of documents your team handles most often.
3. Leave the base `system_prompt` alone unless you want to change the document analysis role itself.

For text files, use `-f` with the CLI. For PDF, DOCX, PPTX, or other binary inputs, use the API or Slack upload flow.
