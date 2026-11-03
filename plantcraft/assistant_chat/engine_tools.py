"""``ChatEngine``'s tool calls: a read of API v1 as the person, the reads made before the model
answers, the proposals of a work and the charts. Part of ``ChatEngine``
(``assistant_chat.engine``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from plantcraft.assistant_access import mcp
from plantcraft.assistant_access.app_tools import AppTool, refs_in
from plantcraft.assistant_chat.charts import _iso, _stats, _when, signal_label, signal_of, unit_of
from plantcraft.assistant_chat.demo import demo_assistant, is_visit
from plantcraft.assistant_chat.engine_common import (
    CHART,
    CHART_POINTS,
    CHART_SIGNALS,
    FUTURE_SLACK,
    HELP,
    LOGGER,
    PREFETCH_MIN,
    Reader,
)
from plantcraft.assistant_chat.toolbox import as_lists, fit, read_help, reads_of, refs_of, summary
from plantcraft.assistant_works import Work
from plantcraft.i18n import t


class ToolCalls:
    """``ChatEngine``'s tool calls."""

    def _tool(
        self,
        name: str,
        arguments: dict[str, Any],
        reader: Reader,
        charts: list[dict[str, Any]],
        refs: list[str],
        step: dict[str, Any],
        chat: dict[str, Any],
        username: str,
        apps: set[str] | None = None,
    ) -> Any:
        if name == CHART:
            checked = self._chart_arguments(arguments)
        elif name == HELP and self.help_docs is not None:
            if not isinstance(arguments, dict) or set(arguments) - {"document_id", "query"}:
                raise ValueError("read_help takes document_id or query")
            checked = {key: str(value)[:120] for key, value in arguments.items() if value}
        else:
            added = self.app_tools.get(name, apps)
            found = mcp.BY_NAME.get(name) or (added.tool() if added else None)
            if found is None:
                raise ValueError(f"Unknown tool: {name}")
            checked = mcp.check_arguments(found, arguments)
        step["summary"] = summary(checked)
        # A public demo visit reads for itself, a few signals a visit (assistant_chat.demo).
        owner = chat.get("username") or username
        demo = demo_assistant() if is_visit(owner) else None
        limit = demo.reads if demo is not None else None
        if not self.reads.spend(owner if demo else username, reads_of(name, checked), limit):
            raise RuntimeError(
                t(
                    "Today's limit of {count} signal reads by the assistant for this person is "
                    "reached. Answer from what was already read and say so; it starts again "
                    "tomorrow.",
                    count=self.reads.daily if limit is None else limit,
                )
            )

        # Only what was read: an id the model guessed and that answered 404 is no source.
        def keep(found: list[str]) -> None:
            before = sum(ref.startswith("signal:") for ref in refs)
            for ref in found:
                if ref not in refs:
                    refs.append(ref)
            after = sum(ref.startswith("signal:") for ref in refs)
            if before < self.bulk_signals <= after:
                # One answer read many signals at once: flagged once, the answer goes on.
                self.audit.record(
                    username,
                    "assistant.bulk_read",
                    f"user:{username}",
                    {
                        "chat_id": chat.get("chat_id"),
                        "signals": after,
                        "flag_at": self.bulk_signals,
                    },
                    app_id="processcraft",
                )

        self.audit.record(
            username,
            "assistant.tool",
            f"tool:{name}",
            {"chat_id": chat.get("chat_id"), "arguments": checked, **chat.get("audit", {})},
            app_id="processcraft",
        )
        if name == CHART:
            drawn = self._chart(checked, reader, charts)
            keep([f"signal:{item['signal']}" for item in drawn["signals"] if item["signal"]])
            return drawn
        if name == HELP and self.help_docs is not None:
            return read_help(*self.help_docs, checked)
        method, path, values = found.request(checked)
        status, payload = reader(method, path, values)
        if status >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise RuntimeError(f"HTTP {status}: {str(detail)[:300]}")
        keep(refs_of(checked))
        if name not in mcp.BY_NAME:
            # An app's tool: its answer is the app's (the documents it cites are sources).
            keep(refs_in(payload))
            return fit(payload)
        if name == "signal_value" and isinstance(payload, dict) and not payload.get("unit"):
            # A value without its unit was given with a made-up one (2026-10-26).
            payload = {**payload, "unit": unit_of(reader, checked["signal_id"])}
        if name in ("read_series", "signal_stats") and isinstance(payload, dict):
            payload = {
                **payload,
                "series": [
                    {**item, "unit": item.get("unit") or unit_of(reader, str(item.get("signal")))}
                    if isinstance(item, dict)
                    else item
                    for item in payload.get("series") or []
                ],
            }
        truncated = getattr(payload, "truncated", False)
        payload = mcp.only_apps(payload, apps)
        if found.shape is not None:
            payload = found.shape(payload, checked)
        if truncated:
            payload = {"note": mcp.TRUNCATED, "answer": payload}
        return fit(payload)

    def _prefetch(
        self,
        asking: list[AppTool],
        asked: str,
        reader: Reader,
        steps: list[dict[str, Any]],
        shown: Callable[[], None],
        chat: dict[str, Any],
        username: str,
        apps: set[str] | None,
    ) -> list[tuple[AppTool, dict[str, Any], Any]]:
        """Each tool of ``asking`` called with the person's question, as the person, before the
        model answers: one step each, as if the model had called it. A tool that fails is left
        out (the model may still call it); its references wait for the answer to name them."""

        question = " ".join(asked.split())[:500]
        if len(question) < PREFETCH_MIN:
            return []
        done: list[tuple[AppTool, dict[str, Any], Any]] = []
        # A page about an asset (Analytics' loop, an alarm's tag): a tool that takes an asset
        # searches about it too, so "why does this loop cycle?" finds the loop's own documents.
        subject = str(chat.get("ref") or "")
        for item in asking:
            arguments = {item.prefetch: question}
            if subject.startswith("asset:") and any(arg.get("key") == "asset" for arg in item.args):
                arguments["asset"] = subject
            step = {"tool": item.name, "title": item.title, "summary": "", "state": "running"}
            steps.append(step)
            shown()
            try:
                value = self._tool(item.name, arguments, reader, [], [], step, chat, username, apps)
            except Exception as exc:
                LOGGER.info("The question could not be searched with %s: %s", item.name, exc)
                steps.remove(step)
                continue
            finally:
                shown()
            step["state"] = "ok"
            done.append((item, arguments, value))
        return done

    def work_of(self, chat: dict[str, Any]) -> Work | None:
        """The work the chat was started for, if it is still offered by the suite."""

        key = chat.get("work") or ""
        return self.works.get(key) if key else None

    def _propose(
        self,
        work: Work,
        arguments: Any,
        proposals: list[dict[str, Any]],
        step: dict[str, Any],
        chat: dict[str, Any],
        username: str,
    ) -> dict[str, Any]:
        """The model proposes the object: PlantCraft checks the fields; a sound proposal becomes
        the card the person creates from (nothing is created here)."""

        given = arguments.get("fields") if isinstance(arguments, dict) else None
        clean, problems = work.check(as_lists(work, given))
        step["summary"] = work.spec.object
        if problems:
            return {"ok": False, "problems": problems[:20]}
        if len(proposals) >= 5:
            return {"ok": False, "problems": ["Five proposals in one answer at most."]}
        # The card carries what it needs to draw itself and create the object wherever the chat
        # is read again (the panel of another page, Desk's Assistant): the fields and the routes.
        public = work.public()
        # A work on one object (change this block) names it in its routes as "{subject}": the
        # id of the chat's object, the last part of an app's (block:linkcraft/<id>).
        subject = str(chat.get("ref") or "").split(":", 1)[-1].rsplit("/", 1)[-1]
        routes = {
            key: (public[key] or "").replace("{subject}", quote(subject, safe="")) or None
            for key in ("create", "open", "form")
        }
        if "{subject}" in "".join(public[key] or "" for key in routes) and not subject:
            return {"ok": False, "problems": ["This work needs the page's object."]}
        proposals.append(
            {
                "work": work.key,
                # The card's words in the person's language (the platform's works are translated).
                "object": public.get("object") or work.spec.object,
                "fields": clean,
                "state": "proposed",
                "card": {**{key: public[key] for key in ("app", "title", "fields")}, **routes},
            }
        )
        self.audit.record(
            username,
            "assistant.proposed",
            f"work:{work.key}",
            {"chat_id": chat.get("chat_id"), "fields": sorted(clean)},
            app_id="processcraft",
        )
        button = f"Continue in the {work.spec.object} form" if public.get("form") else "Create"
        return {
            "ok": True,
            "created": False,
            "shown": (
                f"Nothing is created yet. The person sees the card with a {button} button: say "
                "it is prepared and waits for that button; never say you created it."
            ),
        }

    @staticmethod
    def _chart_arguments(arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        unknown = set(arguments) - {"signal_ids", "start", "end", "title"}
        if unknown:
            raise ValueError(f"unknown arguments: {', '.join(sorted(unknown))}")
        ids = arguments.get("signal_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or not all(isinstance(item, str) and 0 < len(item) <= 300 for item in ids)
        ):
            raise ValueError("signal_ids must be a list of signal ids")
        unique = list(dict.fromkeys(ids))
        if len(unique) > CHART_SIGNALS:
            raise ValueError(f"a chart shows {CHART_SIGNALS} signals at most")
        now = datetime.now(timezone.utc)
        end = _when(arguments.get("end"), now)
        start = _when(arguments.get("start"), end - timedelta(hours=24))
        if start >= end:
            raise ValueError("start must come before end")
        if end > now + FUTURE_SLACK:
            # History ends now. A window that ends hours ahead is "the last hours" written on
            # the wrong clock (the plant's hours with UTC's mark, or UTC's with the plant's
            # offset): it is moved back to end now, the same length (2026-11-03, a chart of
            # 10:18-14:18 at 11:18 on the plant's clock, three hours of it empty).
            start, end = start - (end - now), now
        checked: dict[str, Any] = {"signal_ids": unique, "start": _iso(start), "end": _iso(end)}
        title = arguments.get("title")
        if isinstance(title, str) and title.strip():
            checked["title"] = title.strip()[:120]
        return checked

    @staticmethod
    def _chart(checked: dict[str, Any], reader: Reader, charts: list[dict[str, Any]]) -> Any:
        start = _when(checked["start"], datetime.now(timezone.utc))
        end = _when(checked["end"], datetime.now(timezone.utc))
        step = max(1, int((end - start).total_seconds() // CHART_POINTS))
        status, payload = reader(
            "POST",
            "/api/v1/series",
            {
                "signals": checked["signal_ids"],
                "start": checked["start"],
                "end": checked["end"],
                "step": step,
            },
        )
        if status >= 400 or not isinstance(payload, dict):
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise RuntimeError(f"HTTP {status}: {str(detail)[:300]}")
        series = []
        for item in payload.get("series") or []:
            times = list(item.get("t") or [])[: CHART_POINTS * 2]
            values = list(item.get("v") or [])[: CHART_POINTS * 2]
            signal_id = str(item.get("signal") or "")
            found = signal_of(reader, signal_id)
            series.append(
                {
                    "signal": item.get("signal"),
                    # What the legend says: the tag people know and the signal's description
                    # ("FIC-1003.PV · Recycle flow"), not the source's full id (2026-11-03).
                    "label": signal_label(signal_id, found),
                    "kind": item.get("kind"),
                    "unit": item.get("unit") or str(found.get("unit") or ""),
                    "t": times,
                    "v": values,
                }
            )
        errors = [
            {
                "signal": item.get("signal"),
                "status": item.get("status"),
                "detail": str(item.get("detail"))[:200],
            }
            for item in payload.get("errors") or []
        ]
        if not series:
            raise RuntimeError(
                "No series could be read: "
                + "; ".join(f"{item['signal']}: {item['detail']}" for item in errors)
            )
        charts.append(
            {
                "title": checked.get("title") or "",
                "start": checked["start"],
                "end": checked["end"],
                "step_seconds": step,
                "series": series,
                "errors": errors,
            }
        )
        return {
            "shown": True,
            "chart": len(charts),
            "start": checked["start"],
            "end": checked["end"],
            "step_seconds": step,
            "signals": [
                {"signal": item["signal"], "label": item["label"], **_stats(item["v"])}
                for item in series
            ],
            "errors": errors,
        }
