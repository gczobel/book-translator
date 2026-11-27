# LLM access goes through our own small interface, pydantic-ai first

The pipeline depends on one interface of our own: send a prompt, get back a
Pydantic-validated result, and report the tokens and cost spent. The first implementation
uses pydantic-ai. It validates outputs against our schemas, retries when output fails
validation, and covers Anthropic, OpenRouter, OpenAI, Gemini and local Ollama through a model
string. Development uses Claude through an Anthropic Console API key: Sonnet for most
stages, Opus for the whole-book consolidation in S1 and for TK resolution. Each stage's
model is set in config. Every run is checked against a per-book spending cap (default
$10), with a cost estimate before it starts and a hard stop when the cap is reached.

## Considered Options

- **litellm + instructor** (the handoff's leaning): broad provider coverage, but heavy,
  and the structured-output part would be a second library on top.
- **One provider's SDK directly**: the simplest start, but it ties every stage to that
  provider, which goes against the goal of staying provider-agnostic.
- **OpenRouter as the only route**: one key for every model, but it adds a middleman
  between us and the provider. It stays available as just another model string.

## Consequences

- Swapping pydantic-ai for another library means touching one module.
- A claude.ai subscription can't be used. The tool needs an API key.
