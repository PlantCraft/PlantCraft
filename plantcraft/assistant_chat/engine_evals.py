"""``ChatEngine``'s evaluation runs (``assistant_chat.evals``). Part of ``ChatEngine``
(``assistant_chat.engine``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plantcraft.assistant_chat.engine_common import LOGGER, Reader, Refused
from plantcraft.assistant_chat.evals import Case, build_cases, run_case
from plantcraft.assistant_chat.work_evals import build_work_cases
from plantcraft.i18n import current_language, reset_language, set_language, t


class Evaluation:
    """``ChatEngine``'s evaluation runs."""

    # Evaluation (evals.py)

    def start_eval(
        self,
        username: str,
        profile: str,
        reader: Reader,
        apps: set[str] | None,
        suite: str = "questions",
        context_for: Callable[[Case], tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Ask the evaluation's cases to ``profile``'s model, as ``username``, in the background:
        the questions whose answer is known (evals.py), or each work as its page asks it
        (work_evals.py; ``context_for`` builds a case's context as for a person)."""

        if self.evals is None:
            raise Refused(t("The evaluation is not available here."), 409)
        model, _ = self._model(profile)
        if model is None:
            raise Refused(self.status()["reason"] or t("This specialist has no model now."), 409)
        if self.evals.running():
            raise Refused(t("An evaluation is running. Wait for it to finish."), 409)
        if suite == "works" and context_for is None:
            raise Refused(t("The works' evaluation is not available here."), 409)
        run = self.evals.start(username, profile, getattr(model, "label", ""), suite)
        future = self.executor.submit(
            self._evaluate,
            run["run_id"],
            username,
            profile,
            reader,
            apps,
            current_language(),
            suite,
            context_for,
        )
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)
        return run

    def _evaluate(
        self,
        run_id: int,
        username: str,
        profile: str,
        reader: Reader,
        apps: set[str] | None,
        language: str,
        suite: str = "questions",
        context_for: Callable[[Case], tuple[str, str]] | None = None,
    ) -> None:
        assert self.evals is not None
        token = set_language(language)
        results: list[dict[str, Any]] = []
        total = 0
        try:
            skipped: list[str] = []
            if suite == "works":
                cases, skipped = build_work_cases(reader, self.works)
            else:
                cases = build_cases(reader)
            total = len(cases)
            self.evals.update(run_id, results=results, total=total, skipped=skipped)
            plain = {"chat_id": None, "profile": profile, "audit": {"eval": run_id}}

            def answer(case: Case) -> dict[str, Any]:
                turns = [{"role": "user", "content": case.question}]
                chat, context = plain, ""
                if case.work and context_for is not None:
                    # As the button beside the page's title starts it (work_evals.py).
                    context, work = context_for(case)
                    page = case.page or {}
                    chat = {
                        **plain,
                        "work": work,
                        "context": context,
                        "place": page.get("place", ""),
                        "ref": page.get("subject", ""),
                    }
                done = self.run(
                    chat, username, turns, reader, apps if case.apps is None else case.apps
                )
                return {**done, "context": context}

            for case in cases:
                results.append(run_case(case, answer))
                self.evals.update(run_id, results=results, total=total)
            self.evals.update(run_id, results=results, total=total, state="done")
        except Exception as exc:
            LOGGER.warning("The assistant's evaluation %s stopped: %s", run_id, exc)
            self.evals.update(run_id, results=results, total=total, state="failed", error=str(exc))
        finally:
            reset_language(token)
