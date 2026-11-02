# Model Wire Fixtures

Synthetic test payloads for local model runtime simulation (LLM-01):
- `generation_success.json`: Wire response from `/api/generate` with a strictly valid C11 Assessment object.
- `generation_malformed.json`: Wire response containing markdown fences and prose.
- `embeddings_success.json`: Wire response from `/api/embed` with ordered 384-dimensional vectors.

