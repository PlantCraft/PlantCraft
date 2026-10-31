"""Shared scientific references used by methodology blocks."""

from __future__ import annotations

from plantcraft_sdk.methods import ScientificReference

BAUER_2016_CPM_SURVEY = ScientificReference(
    title="The current state of control loop performance monitoring - A survey of application in industry",
    authors=["Margret Bauer", "Alexander Horch", "Lei Xie", "Mohieddine Jelali", "Nina Thornhill"],
    year=2016,
    venue="Journal of Process Control",
    doi="10.1016/j.jprocont.2015.11.002",
    url="https://www.sciencedirect.com/science/article/abs/pii/S0959152415002127",
    reference_type="article",
    notes="Industrial CPM survey used as baseline reference for practical loop-monitoring KPIs.",
)

HARRIS_1989_PERFORMANCE = ScientificReference(
    title="Assessment of control loop performance",
    authors=["T.J. Harris"],
    year=1989,
    venue="The Canadian Journal of Chemical Engineering",
    doi="10.1002/cjce.5450670519",
    url="https://onlinelibrary.wiley.com/doi/abs/10.1002/cjce.5450670519",
    reference_type="article",
    notes="Original minimum-variance benchmark for control loop performance assessment.",
)

HORCH_ISAKSSON_1999_MODIFIED_INDEX = ScientificReference(
    title="A modified index for control performance assessment",
    authors=["Alexander Horch", "Alf J. Isaksson"],
    year=1999,
    venue="Journal of Process Control",
    doi="10.1016/S0959-1524(99)00031-1",
    url="https://www.sciencedirect.com/science/article/abs/pii/S0959152499000311",
    reference_type="article",
    notes="Modified benchmark reference for variance-based control performance assessment.",
)

THORNHILL_HAGGLUND_1997_OSCILLATION = ScientificReference(
    title="Detection and diagnosis of oscillation in control loops",
    authors=["N.F. Thornhill", "T. Hagglund"],
    year=1997,
    venue="Control Engineering Practice",
    doi="10.1016/S0967-0661(97)00131-7",
    url="https://www.sciencedirect.com/science/article/abs/pii/S0967066197001317",
    reference_type="article",
    notes="Reference for oscillation detection and operational signatures in control loops.",
)

THORNHILL_HUANG_ZHANG_2003_REGULARITY = ScientificReference(
    title="Detection of multiple oscillations in control loops",
    authors=["N.F. Thornhill", "B. Huang", "H. Zhang"],
    year=2003,
    venue="Journal of Process Control, 13(1), 91-100",
    doi="10.1016/S0959-1524(02)00007-0",
    url="https://doi.org/10.1016/S0959-1524(02)00007-0",
    reference_type="article",
    notes="Regularity of an oscillation from the zero crossings of the autocorrelation function: "
    "r = mean period / (3 x standard deviation of the periods); the oscillation is regular "
    "when r > 1.",
)

HE_2007_CURVE_FITTING_STICTION = ScientificReference(
    title="A curve fitting method for detecting valve stiction in oscillating control loops",
    authors=["Q. Peter He", "Jin Wang", "Martin Pottmann", "S. Joe Qin"],
    year=2007,
    venue="Industrial & Engineering Chemistry Research, 46(13), 4549-4560",
    doi="10.1021/ie061219a",
    url="https://doi.org/10.1021/ie061219a",
    reference_type="article",
    notes="Each half cycle of the oscillation is fitted with a sine and with a triangle; a "
    "sticky valve makes the controller output (or an integrating PV) triangular, aggressive "
    "tuning keeps it sinusoidal. Index = sine error / (sine + triangle error).",
)

CHOUDHURY_THORNHILL_SHAH_2005_STICTION_MODEL = ScientificReference(
    title="Modelling valve stiction",
    authors=["M.A.A. Shoukat Choudhury", "N.F. Thornhill", "S.L. Shah"],
    year=2005,
    venue="Control Engineering Practice, 13(5), 641-658",
    doi="10.1016/j.conengprac.2004.05.005",
    url="https://doi.org/10.1016/j.conengprac.2004.05.005",
    reference_type="article",
    notes="Two-parameter stiction model: the valve stays stuck while the command moves inside "
    "the stick band, then slips; the stick-then-slip movement the screening looks for.",
)

CHOUDHURY_2006_STICTION = ScientificReference(
    title="Automatic detection and quantification of stiction in control valves",
    authors=[
        "M.A.A. Shoukat Choudhury",
        "S.L. Shah",
        "N.F. Thornhill",
        "David S. Shook",
    ],
    year=2006,
    venue="Control Engineering Practice",
    doi="10.1016/j.conengprac.2005.10.003",
    url="https://www.sciencedirect.com/science/article/abs/pii/S0967066105002388",
    reference_type="article",
    notes="Reference for non-invasive stiction detection using routine operating data.",
)

JELALI_HUANG_2010_STICTION_BOOK = ScientificReference(
    title="Detection and Diagnosis of Stiction in Control Loops: State of the Art and Advanced Methods",
    authors=["Mohieddine Jelali", "Biao Huang"],
    year=2010,
    venue="Springer, Advances in Industrial Control",
    doi="10.1007/978-1-84882-775-2",
    url="https://link.springer.com/book/10.1007/978-1-84882-775-2",
    reference_type="book",
    notes="Book reference for assumptions, strengths and limitations of stiction methods.",
)

JELALI_2006_CPA_OVERVIEW = ScientificReference(
    title="An overview of control performance assessment technology and industrial applications",
    authors=["Mohieddine Jelali"],
    year=2006,
    venue="Control Engineering Practice",
    reference_type="article",
    notes="Review of CPA indices used in industry, including time-in-limits and operator-intervention KPIs.",
)

SHINSKEY_1996_PROCESS_CONTROL_SYSTEMS = ScientificReference(
    title="Process Control Systems: Application, Design and Tuning",
    authors=["F. Greg Shinskey"],
    year=1996,
    venue="McGraw-Hill, 4th edition",
    reference_type="book",
    notes="Textbook treatment of averaging (surge) level control: the level absorbs disturbances so the outflow stays smooth.",
)

THORNHILL_CHOUDHURY_SHAH_2004_COMPRESSION = ScientificReference(
    title="The impact of compression on data-driven process analyses",
    authors=["Nina F. Thornhill", "M.A.A. Shoukat Choudhury", "Sirish L. Shah"],
    year=2004,
    venue="Journal of Process Control",
    reference_type="article",
    notes="Shows how historian compression and coarse sampling distort data-driven loop analyses.",
)
