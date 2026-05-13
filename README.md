# newsline

> A personal news radar that tracks **storylines**, learns your taste, and runs locally on your Mac.

newsline is built on the same idea as [Horizon](https://github.com/Thysrael/Horizon) — fetch from many sources, score with AI, deliver a curated briefing — but pushes three things further:

1. **Storyline tracking.** News items are not daily disposable rows; they cluster into stories that grow over time. "GPT-6 announced" and "GPT-6 benchmarks released" attach to the same story, not two unrelated entries on two different days.
2. **Personalization that learns.** A small ranker trained on your reading behavior (opens, dwell, thumbs, saves) reorders the briefing for you specifically.
3. **Local-first, Mac-native.** The pipeline runs in a local Python daemon. A SwiftUI app reads the same SQLite. No server, no account, your data stays on disk.

## Status

🚧 **M0** — bootstrapping. The Python pipeline scaffold is in place; storyline engine, ranker, and Mac app come next.

## Roadmap

- **M0** Python daemon + SQLite + RSS / HN / GitHub scrapers + AI scoring (current)
- **M1** Storyline engine: entity extraction, embedding match, incremental summaries
- **M2** Mac app shell (SwiftUI, three-pane reader)
- **M3** Behavior signals + personal ranker v1
- **M4** Chat over corpus (RAG with story scope)
- **M5** Breaking-news push, multi-modal sources

## Quick start

```bash
git clone https://github.com/<you>/newsline
cd newsline
uv sync                        # or: pip install -e .
cp .env.example .env           # add your LLM API key
cp config.example.json config.json
uv run newsline run            # fetch → score → store
uv run newsline list           # browse scored items
```

## Acknowledgements

The scraper layer is adapted from [Horizon](https://github.com/Thysrael/Horizon) (MIT). See [NOTICE](NOTICE).

## License

[Apache-2.0](LICENSE)
