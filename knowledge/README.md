# PawPal+ Knowledge Base

Short, topic-focused care guides used by the RAG feature. Each file has YAML-style frontmatter:

| Field | Meaning |
|-------|---------|
| `title` | Display title, shown when citing the source |
| `species` | `dog`, `cat`, or `any` |
| `breed` / `life_stage` | Optional, for breed- or age-specific files |
| `tags` | Keywords used for retrieval |
| `source` / `source_url` | Where the guidance comes from, for citations |

Each file ends with a `## Suggested tasks` section so the LLM can map guidance onto PawPal+ tasks (description, duration, priority, recurrence).

**Disclaimer:** this content is general information, not veterinary advice.
