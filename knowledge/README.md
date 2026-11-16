# PawPal+ Knowledge Base

Short, topic-focused care guides used by the RAG feature. Each file has YAML-style frontmatter:

| Field | Meaning |
|-------|---------|
| `title` | Display title, shown when citing the source |
| `species` | `dog`, `cat`, or `any` |
| `breed` / `life_stage` | Optional, for breed- or age-specific files |
| `tags` | Keywords used for retrieval |
| `source` / `source_url` | Primary source, for citations |
| `source_url_2`, `source_url_3`, ... | Optional additional sources |
| `verified` | How the content was checked |

## Verification status (checked 2026-11-15)

Each claim was compared with the cited pages, and claims a source did not support were removed or reworded.

- **Pages read directly, claims confirmed:** `cat_feeding`, `cat_enrichment_play`, `cat_litter_grooming`, `cat_vaccinations_preventive_care`, `toxic_foods_and_hazards`, `dog_feeding`, `dog_vaccinations_preventive_care`, `dog_nail_care`, `puppy_care`, `medication_administration`, `senior_pet_care`.
- **Partly confirmed:** `dog_exercise` (the AKC page confirms needs vary but gives no minute figures; the 30 min-2 h rule of thumb is labeled as not from the source). `puppy_care` is read directly except for the last ~12,000 characters of one long VCA page.
- **Checked via search-result summaries only:** `golden_retriever` (VCA breed page and GRCA health page). Open the links and confirm the figures before relying on them.
- **Not usable as sources:** AAHA's site (403 for automated fetches), so AAHA-specific claims were removed or are attributed to VCA/Cornell instead.

Each file ends with a `## Suggested tasks` section. These are curated defaults (description, duration, priority, recurrence) so the LLM can map guidance onto PawPal+ tasks. They are suggestions, not claims made by the sources.

**Disclaimer:** this content is general information, not veterinary advice.
