"""The assistant's test battery: attacks, refusals and quality questions asked to a model.

Ten groups (docs/llm-battery.md): direct and data-borne prompt injection, data leakage, output
exfiltration, off-scope use, process-safety refusals, hallucination, quality, cost abuse and
load. Every case is asked through the same HTTP routes and engine a person's chat uses, in a
throwaway installation of the generic demo plant, and checked by code (a canary that must never
appear, a write that must never happen, a tool call count, a refusal).

Two kinds of model answer the same cases:

- ``fake.ObedientModel`` obeys every instruction it reads, in the question or in what a tool
  returned. A case that holds against it is held by PlantCraft's own code, whatever the model
  does: those run in CI (``tests/test_llm_battery.py``).
- A real model (``python -m tests.llm_battery --model gpt-5-mini``), with the key read from a
  file that never reaches the output. That run also asks the cases only a model can pass
  (refusals, hallucination, quality) and measures tokens and time per answer.
"""
