# Contributing

Contributions are welcome through issues and pull requests.

For behavior changes, include:

1. the scientific or interoperability motivation;
2. explicit equations, parameter provenance, and assumptions;
3. tests for deterministic replay and the affected layer;
4. catalog/schema compatibility notes;
5. updated limitations when fidelity changes.

Do not include confidential plant data, credentials, private endpoints,
proprietary models, or copyrighted benchmark implementations. Synthetic and
empirical validation data must have explicit redistribution terms.

Read [AGENTS.md](AGENTS.md) first. Run before submitting:

```bash
make ci     # ruff, simcraft validate-catalog, pytest, python -m build
```
