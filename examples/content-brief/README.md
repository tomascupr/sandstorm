# Content Brief Generator

Generate comprehensive content briefs with SEO research and competitive analysis.

## Features Used

- **`output_format`** — structured brief with title options, keywords, outline, and competitor gaps
- **`max_turns`** — set to 15 to allow thorough web research on the topic
- **`system_prompt`** — content strategist persona that researches what's ranking and finds content gaps
- **WebSearch** — enabled by default, used to research existing content, keywords, and competitor angles

## Quick Start

```bash
cd examples/content-brief
ds "Create a content brief for a blog post about serverless vs containers in 2025"
```

## More Examples

```bash
# Landing page brief
ds "Brief for a landing page targeting enterprise DevOps teams evaluating AI coding tools"

# SEO-focused article
ds "Create a brief for 'how to implement rate limiting in Node.js' targeting mid-level developers"

# Thought leadership
ds "Brief for a LinkedIn article about why most AI agent frameworks will fail"

# Product comparison
ds "Content brief for a comparison page: our product vs Competitor X for data pipeline orchestration"
```

## Sample Output

```json
{
  "title_options": [
    "Serverless vs Containers in 2025: When to Use Each (and When to Use Both)",
    "The Serverless vs Containers Debate Is Over — Here's What Won",
    "Serverless or Containers? A Decision Framework for Modern Teams"
  ],
  "target_audience": "Backend developers and DevOps engineers evaluating architecture options for new projects",
  "primary_keyword": "serverless vs containers",
  "secondary_keywords": [
    "serverless architecture",
    "container orchestration",
    "AWS Lambda vs ECS",
    "when to use serverless",
    "kubernetes alternatives"
  ],
  "search_intent": "commercial",
  "recommended_word_count": 2500,
  "outline": [
    {
      "heading": "The State of Serverless and Containers in 2025",
      "subpoints": ["Market adoption numbers", "Key shifts since 2023"],
      "key_points": [
        "Serverless adoption has grown 40% YoY",
        "Container orchestration complexity is driving serverless migration"
      ]
    },
    {
      "heading": "When Serverless Wins",
      "subpoints": ["Event-driven workloads", "Variable traffic", "Small teams"],
      "key_points": [
        "Cost efficiency for bursty workloads",
        "Zero ops overhead for teams under 10 engineers"
      ]
    },
    {
      "heading": "When Containers Win",
      "subpoints": ["Long-running processes", "GPU workloads", "Complex networking"],
      "key_points": [
        "Predictable performance for latency-sensitive apps",
        "Required for ML inference and GPU workloads"
      ]
    }
  ],
  "competitor_content": [
    {
      "title": "Serverless vs Containers: A Comprehensive Guide",
      "url": "https://example.com/serverless-vs-containers",
      "angle": "Technical comparison with code examples",
      "gap": "No cost analysis or decision framework — just feature comparison"
    }
  ],
  "unique_angle": "Focus on the decision framework rather than the technology comparison — help readers choose based on their team size, traffic patterns, and ops capacity",
  "cta_suggestion": "Download our serverless readiness assessment checklist"
}
```

## Configuration

| Field | Value | Why |
|-------|-------|-----|
| `system_prompt` | Content strategist persona | Researches what's ranking, finds gaps, and produces actionable briefs |
| `model` | `sonnet` | Good balance of research quality and speed |
| `max_turns` | `15` | Enough turns to search, analyze competitor content, and synthesize findings |
| `output_format` | JSON schema with outline and competitor analysis | Directly actionable — hand the output to a writer |

## Customization

- **Add word count per section** — add `estimated_words` to each outline item for more detailed planning
- **Add internal linking** — add a `related_content` field for existing pages to link to/from
- **Adjust depth** — increase `max_turns` for more thorough research, decrease for faster briefs
- **Add tone guidance** — extend the schema with `tone`, `reading_level`, and `brand_voice` fields
