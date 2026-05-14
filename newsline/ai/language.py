"""Language directive appended to user-facing LLM prompts.

Applied to: Scorer (reason / summary / tags), Rewriter (story summary),
Chatter (chat answer). NOT applied to:
  - EntityExtractor — entities stay canonical English so cross-language
    matching still works ("Anthropic" not "安特罗皮克")
  - StorylineMatcher classifier — internal yes/no/which decision, never
    surfaced to the user
"""

from __future__ import annotations

_DIRECTIVES = {
    "en": "",  # default — model already English-biased
    "zh": (
        "\n\nIMPORTANT: Respond entirely in Simplified Chinese (简体中文). "
        "All free-text fields — reason, summary, tags, answers — must be in Chinese. "
        "Keep proper nouns (product names, company names, technical terms) in their "
        "original English form, e.g. 'Anthropic', 'GPT-5', 'TanStack'."
    ),
}


def directive_for(language: str) -> str:
    """Return the trailing instruction for the given language code.

    Unknown languages fall back to no directive (English behavior).
    """
    return _DIRECTIVES.get(language.lower(), "")
