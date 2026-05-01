# Examples

Three small scripts that demonstrate the three things Lysos can do.

| Script | What | Needs |
|---|---|---|
| `quickstart.py` | Generate 5 candidate molecules against MRSA via the API | running API server (or HF Space) |
| `score_smiles.py` | Score a single SMILES on all 6 reward dimensions | local install (`pip install -e .[dev]`) — no API needed |
| `find_similar_drugs.py` | Find top-k known antibiotics most similar to a SMILES | running API server with EmbeddingGemma loaded |

## Running locally

```bash
# Start the API server in one terminal:
make api-dev

# In another terminal, run any example:
python examples/quickstart.py
python examples/score_smiles.py "CC1(C)SC2C(NC(=O)C(N)c3ccccc3)C(=O)N2C1C(=O)O"   # ampicillin
python examples/find_similar_drugs.py "CC1(C)SC2C(NC(=O)C(N)c3ccccc3)C(=O)N2C1C(=O)O"
```

## Running against the deployed HF Space

By default `quickstart.py` and `find_similar_drugs.py` hit the deployed
Space at
`https://lablab-ai-amd-developer-hackathon-lysos.hf.space`. Override
with:

```bash
LYSOS_API=http://localhost:7860 python examples/quickstart.py
```
