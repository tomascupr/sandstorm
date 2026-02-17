# Competitive Analysis

Research and compare competitors with structured scoring and market insights.

## Features Used

- **`output_format`** — structured competitor profiles with features, pricing, strengths, and weaknesses
- **`max_turns`** — set to 20 to allow thorough research across multiple competitor websites
- **`system_prompt`** — strategic analyst persona that cites specific findings from competitor sites
- **WebFetch / WebSearch** — enabled by default, used to crawl competitor websites and gather real-time data

## Quick Start

```bash
cd examples/competitive-analysis
ds "Compare Vercel, Netlify, and Cloudflare Pages as deployment platforms"
```

## More Examples

```bash
# Analyze a market segment
ds "Analyze the competitive landscape for AI code review tools"

# Compare specific products
ds "Compare Stripe, Paddle, and LemonSqueezy for SaaS billing"

# Focus on a niche
ds "Compare Supabase, Firebase, and Neon as backend-as-a-service for startups"

# Regional analysis
ds "Compare food delivery platforms in the European market: Deliveroo, Wolt, and Uber Eats"
```

## Sample Output

```json
{
  "market_segment": "Cloud deployment platforms for frontend developers",
  "competitors": [
    {
      "name": "Vercel",
      "website": "https://vercel.com",
      "positioning": "Frontend cloud platform for building and deploying web applications",
      "target_audience": "Frontend developers and teams using Next.js and React",
      "key_features": [
        "Automatic CI/CD from Git",
        "Edge Functions",
        "Preview deployments",
        "Built-in analytics"
      ],
      "pricing_model": "Freemium with per-seat Pro plan at $20/month",
      "strengths": [
        "Best-in-class Next.js integration",
        "Fast global edge network",
        "Excellent developer experience"
      ],
      "weaknesses": [
        "Vendor lock-in with Next.js optimizations",
        "Costs scale quickly with traffic",
        "Limited backend capabilities"
      ]
    }
  ],
  "comparison_matrix": [
    { "feature": "Free tier bandwidth", "Vercel": "100 GB", "Netlify": "100 GB", "Cloudflare": "Unlimited" },
    { "feature": "Edge functions", "Vercel": "Yes", "Netlify": "Yes", "Cloudflare": "Yes (Workers)" },
    { "feature": "Build minutes (free)", "Vercel": "6000/mo", "Netlify": "300/mo", "Cloudflare": "500/mo" }
  ],
  "market_insights": "The deployment platform market is consolidating around edge-first architectures. Cloudflare's unlimited bandwidth on the free tier is disrupting pricing norms, while Vercel maintains dominance in the React/Next.js ecosystem through deep framework integration.",
  "recommendations": [
    "Startups with Next.js apps should default to Vercel for the best DX",
    "Cost-sensitive projects benefit from Cloudflare Pages' generous free tier",
    "Teams needing form handling and identity should evaluate Netlify's integrated services"
  ]
}
```

## Configuration

| Field | Value | Why |
|-------|-------|-----|
| `system_prompt` | Strategic market analyst | Instructs the agent to cite findings from actual websites, not general knowledge |
| `model` | `sonnet` | Balanced quality for research and synthesis |
| `max_turns` | `20` | Enough turns to fetch and analyze multiple competitor websites |
| `output_format` | JSON schema with competitors array | Structured profiles with scoring, comparison matrix, and recommendations |

## Customization

- **Add scoring** — add a `score` field (1-10) to each competitor for quantitative ranking
- **Track pricing** — expand the `pricing_model` field into a detailed pricing object with tiers
- **Add screenshots** — the agent can take screenshots of competitor sites if you add specific instructions
- **Narrow focus** — modify the system prompt to focus on specific aspects (pricing only, feature parity, etc.)
