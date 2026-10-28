"""Resolution: a signal that moves in coarse steps or in straight lines (quantised or compressed)."""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import Finding, NotEnoughData, ScientificReference, method, param

from linkcraft.i18n import t
from linkcraft.methods.signal._common import is_text, num, numbers, score_band
from linkcraft.methods.signal._common import spread as robust_spread

MAD_TO_SIGMA = 1.4826


def _describe(metrics: dict) -> str:
    return t(
        "Steps of {quantum} against a spread of {spread} ({distinct} distinct values); "
        "{linear} of the samples lie on straight lines.",
        quantum=num(metrics.get("quantum")),
        spread=num(metrics.get("spread")),
        distinct=metrics.get("distinct_values"),
        linear=f"{100 * float(metrics.get('linear_fraction') or 0):.0f}%",
    )


@method(
    "sq_resolution",
    name="Resolution and compression",
    application="linkcraft",
    version="1.0.0",
    maturity="literature_based",
    min_samples=0,
    references=[
        ScientificReference(
            title="The impact of compression on data-driven process analyses",
            authors=["Thornhill, N. F.", "Choudhury, M. A. A. S.", "Shah, S. L."],
            year=2004,
            venue="Journal of Process Control 14(4), 389-398",
            doi="10.1016/j.jprocont.2003.07.002",
        )
    ],
    formula=(
        "quantisation = 5th percentile of the non-zero |steps| / (1.4826 MAD of the values); "
        "linear share = share of moving samples whose second difference is zero (values "
        "rebuilt by linear interpolation after compression)."
    ),
    limitations=[
        "A slow signal recorded with few decimals is coarse for analysis even if the "
        "instrument is fine; the finding is about the recorded data.",
    ],
    describe=_describe,
)
def resolution(
    dataset,
    *,
    warn_quantisation: float = param(
        0.25, gt=0, help="Step size, as a share of the spread, that is a warning."
    ),
    bad_quantisation: float = param(
        1.0, gt=0, help="Step size, as a share of the spread, that makes analysis unreliable."
    ),
    warn_linear: float = param(
        0.5, gt=0, le=1, help="Share of samples on straight lines that is a warning."
    ),
    bad_linear: float = param(
        0.8, gt=0, le=1, help="Share of samples on straight lines that is bad."
    ),
):
    """Coarse steps (quantisation, a wide recording deadband) or interpolated compressed data."""

    if is_text(dataset):
        return Finding(
            score=0, status="not_applicable", message=t("Text signals have no resolution.")
        )
    values = numbers(dataset).to_numpy()
    if values.size < 20:
        raise NotEnoughData(t("Fewer than 20 numeric samples in the window."))
    spread = robust_spread(values)
    steps = np.abs(np.diff(values))
    scale = 1e-9 * max(1.0, float(np.max(np.abs(values))))
    moving = steps > scale
    if spread <= scale or moving.sum() < 5:
        return Finding(
            score=0,
            status="not_applicable",
            metrics={"spread": round(spread, 6), "distinct_values": int(np.unique(values).size)},
            message=t("The signal barely moves; the frozen value check judges it."),
        )
    quantum = float(np.percentile(steps[moving], 5))
    quantisation = quantum / spread
    curvature = np.abs(np.diff(values, 2))
    linear = float((curvature[moving[1:]] <= scale).mean()) if moving[1:].any() else 0.0
    score = max(
        score_band(
            quantisation, warn_quantisation, max(bad_quantisation, warn_quantisation * 1.001)
        ),
        score_band(linear, warn_linear, max(bad_linear, warn_linear * 1.001), 1.0),
    )
    return Finding(
        score=score,
        metrics={
            "quantum": round(quantum, 6),
            "spread": round(spread, 6),
            "quantisation": round(quantisation, 4),
            "linear_fraction": round(linear, 4),
            "distinct_values": int(np.unique(values).size),
            "apt": score < 75,
        },
    )
