"""Storyline engine (M1 — not implemented yet).

Plan:
  - Entity extraction (LLM) on each ContentItem
  - Embedding index over story summaries (sqlite-vec)
  - Story matching: embedding similarity + entity overlap + LLM verify
  - Incremental summary update on attach
"""
