"""Source quality: how much of the window the source itself marked bad, substituted or uncertain.

OPC UA, PI and Canary keep a quality with every value. A signal can have a value at every instant
and still be data nobody should trust: the device was in fault (bad), an operator or the
historian typed or held a value (substituted), or the source doubted it (uncertain). This check
reads that per-sample quality (``metadata["quality"]``, PlantCraft API v1 ``"quality": true``)
and shows each share of the window.
"""

from __future__ import annotations

from plantcraft_sdk.methods import Finding, NotEnoughData, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import event, quality_spans, score_band, window, worst_events


@method(
    "sq_source_quality",
    name="Source quality",
    application="linkcraft",
    version="1.0.0",
    maturity="engineering_heuristic",
    min_samples=0,
    formula=(
        "share(q) = time the source marked q / window, for q in bad, substituted, uncertain "
        "(a quality holds until the next one). Bad and substituted time is not data: warning "
        "above warn_share, bad above bad_share. Uncertain time is a warning at most."
    ),
    assumptions=[
        "The source's quality is a fact about the value (OPC UA StatusCode, PI and Canary "
        "quality), kept by the Historian with each sample."
    ],
    limitations=[
        "Needs a source that keeps quality; without it the check does not apply.",
        "Trusts the source: a value marked good can still be wrong (the other checks look "
        "at that).",
    ],
    describe="The source marked {not_good_share:%} of the window not good: bad "
    "{quality_bad:%}, substituted {quality_substituted:%}, uncertain {quality_uncertain:%}.",
)
def source_quality(
    dataset,
    *,
    warn_share: float = param(
        0.01, ge=0, lt=1, help="Share of the window bad or substituted that is a warning."
    ),
    bad_share: float = param(
        0.05,
        gt=0,
        le=1,
        help="Share of the window bad or substituted that makes the data unusable.",
    ),
    warn_uncertain: float = param(
        0.05, gt=0, le=1, help="Share of the window uncertain that is a warning."
    ),
):
    """Share of the window the source marked bad, substituted or uncertain."""

    span = window(dataset)
    if span is None:
        raise NotEnoughData(t("The window is empty."))
    start, end = span
    spans = quality_spans(dataset, start, end)
    if spans is None:
        return Finding(
            score=0,
            status="not_applicable",
            message=t("The source keeps no quality for this signal."),
        )
    duration = (end - start).total_seconds()
    seconds = {
        code: sum((b - a).total_seconds() for a, b in found) for code, found in spans.items()
    }
    shares = {code: value / duration for code, value in seconds.items()}
    unusable = shares["bad"] + shares["substituted"]
    warn = warn_share
    bad = max(bad_share, warn * 1.001)
    score = score_band(unusable, warn, bad, 1.0) if warn > 0 else (100.0 if unusable else 0.0)
    if shares["uncertain"] > 0:
        uncertain = score_band(
            shares["uncertain"], warn_uncertain, max(1.0, warn_uncertain * 1.001)
        )
        score = max(score, min(uncertain, 74.0))
    labels = {
        "bad": t("Bad quality"),
        "substituted": t("Substituted"),
        "uncertain": t("Uncertain"),
    }
    events = [
        (
            (b - a).total_seconds(),
            event(a, b, labels[code], seconds=(b - a).total_seconds(), quality=code),
        )
        for code, found in spans.items()
        for a, b in found
    ]
    return Finding(
        score=score,
        metrics={
            "quality_bad": round(shares["bad"], 4),
            "quality_substituted": round(shares["substituted"], 4),
            "quality_uncertain": round(shares["uncertain"], 4),
            "not_good_share": round(sum(shares.values()), 4),
            "not_good_spans": sum(len(found) for found in spans.values()),
            "apt": unusable < bad,
        },
        events=worst_events(events),
    )
