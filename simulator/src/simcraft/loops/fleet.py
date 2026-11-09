"""The plant's healthy majority: 50 well-tuned loops beside the 50 of the demo story.

A real plant has far more loops that work than loops with a problem. The first 50 loops
(``dynamics``) each carry one known behaviour, 41 of them a fault; these 50 add loops that hold
their setpoint, so the demo reads as a plant of 100 loops where 41 need a look (2026-11-09).

Each row is the loop's id, name, area, the equipment it sits on in the plant map and its
setpoint; the type comes from the id's first letter and sets a tuning that is healthy for it.
"""

from __future__ import annotations

from .dynamics import LoopDefinition

# (loop id, name, area, equipment in the plant map, setpoint)
HEALTHY_FLEET: tuple[tuple[str, str, str, str, float], ...] = (
    ("FIC-1301", "Feed preheat bypass flow", "Feed", "P-1001", 54.0),
    ("PIC-1302", "Charge pump discharge pressure", "Feed", "P-1001", 57.0),
    ("TIC-1303", "Feed preheat temperature", "Feed", "P-1001", 61.0),
    ("TIC-1304", "Crude preheat outlet temperature", "Heat exchange", "E-1009", 62.0),
    ("FIC-1305", "Exchanger bypass flow", "Heat exchange", "E-1009", 49.0),
    ("TIC-1306", "Product cooler outlet temperature", "Heat exchange", "E-1009", 53.0),
    ("PIC-1307", "Cooling water return pressure", "Heat exchange", "E-1009", 55.0),
    ("FIC-1308", "Furnace pass A flow", "Furnaces", "F-1104", 58.0),
    ("FIC-1309", "Furnace pass B flow", "Furnaces", "F-1104", 58.0),
    ("PIC-1310", "Furnace draft pressure", "Furnaces", "F-1104", 47.0),
    ("FIC-1311", "Combustion air flow", "Furnaces", "F-1104", 63.0),
    ("FIC-1312", "Top reflux flow", "Distillation", "C-1101", 56.0),
    ("PIC-1313", "Column top pressure", "Distillation", "C-1101", 52.0),
    ("TIC-1314", "Bottom temperature", "Distillation", "C-1101", 64.0),
    ("LIC-1315", "Column bottom level", "Distillation", "C-1101", 50.0),
    ("FIC-1316", "Naphtha product flow", "Distillation", "D-1106", 51.0),
    ("FIC-1317", "Kerosene stripper steam flow", "Distillation", "P-1102", 46.0),
    ("FIC-1318", "Hydrogen feed flow", "Reaction", "R-1005", 59.0),
    ("PIC-1319", "Reactor pressure", "Reaction", "R-1005", 60.0),
    ("TIC-1320", "Quench temperature", "Reaction", "R-1005", 57.0),
    ("FIC-1321", "Make-up hydrogen flow", "Recycle", "P-1003", 52.0),
    ("PIC-1322", "Recycle pump suction pressure", "Recycle", "P-1003", 48.0),
    ("LIC-1323", "Water boot level", "Separation", "V-1004", 45.0),
    ("FIC-1324", "Sour water flow", "Separation", "V-1004", 50.0),
    ("PIC-1325", "Flash drum pressure", "Separation", "V-1105", 54.0),
    ("TIC-1326", "Separator feed temperature", "Separation", "V-1105", 58.0),
    ("FIC-1327", "Compressor spillback flow", "Compression", "K-1103", 53.0),
    ("TIC-1328", "Interstage cooler temperature", "Compression", "K-1103", 56.0),
    ("PIC-1329", "Seal gas pressure", "Compression", "K-1103", 61.0),
    ("LIC-1330", "Knock-out drum level", "Compression", "V-1208", 48.0),
    ("FIC-1331", "Wash water flow", "Hydrotreating", "R-1203", 55.0),
    ("TIC-1332", "Reactor bed 2 temperature", "Hydrotreating", "R-1203", 63.0),
    ("PIC-1333", "Low-pressure separator pressure", "Hydrotreating", "V-1204", 50.0),
    ("FIC-1334", "Stripper bottoms flow", "Hydrotreating", "V-1204", 57.0),
    ("AIC-1335", "Recycle gas hydrogen purity", "Quality", "u-200-quality", 52.0),
    ("AIC-1336", "Product aromatics content", "Quality", "u-200-quality", 55.0),
    ("FIC-1337", "Lean amine flow", "Treating", "C-1216", 56.0),
    ("TIC-1338", "Lean amine temperature", "Treating", "C-1216", 52.0),
    ("PIC-1339", "Absorber pressure", "Treating", "C-1216", 58.0),
    ("FIC-1340", "Acid gas flow", "Sulfur recovery", "R-1226", 51.0),
    ("TIC-1341", "Reaction furnace temperature", "Sulfur recovery", "R-1226", 62.0),
    ("LIC-1342", "Sulfur pit level", "Sulfur recovery", "R-1226", 47.0),
    ("PIC-1343", "Steam header pressure", "Utilities", "V-1218", 59.0),
    ("FIC-1344", "Boiler feed water flow", "Utilities", "V-1218", 54.0),
    ("TIC-1345", "Cooling tower return temperature", "Utilities", "P-1219", 50.0),
    ("PIC-1346", "Instrument air pressure", "Utilities", "u-900-utilities", 57.0),
    ("LIC-1347", "Deaerator level", "Utilities", "V-1218", 53.0),
    ("FIC-1348", "Clarifier feed flow", "Water treatment", "TK-1223", 52.0),
    ("AIC-1349", "Effluent hydrocarbon content", "Water treatment", "TK-1223", 46.0),
    ("LIC-1350", "Sludge tank level", "Water treatment", "TK-1225", 49.0),
)

# By the id's first letter: unit and a tuning that holds the setpoint (like the healthy loops of
# the story: FIC-1001, LIC-1106, TIC-1114, PIC-1221).
_KINDS: dict[str, tuple[str, float, float, float]] = {
    # unit, time constant (s), controller gain, integral gain
    "F": ("m³/h", 108.0, 1.15, 0.13),
    "P": ("bar", 155.0, 1.25, 0.16),
    "T": ("°C", 220.0, 1.25, 0.16),
    "L": ("%", 300.0, 0.68, 0.05),
    "A": ("mol%", 210.0, 1.10, 0.14),
}


def healthy_fleet() -> tuple[LoopDefinition, ...]:
    """The 50 healthy loops as simulator definitions, each with its own seed."""

    loops = []
    for index, (loop_id, name, area, _equipment, setpoint) in enumerate(HEALTHY_FLEET):
        unit, tau, gain, integral = _KINDS[loop_id[0]]
        # Small, deterministic spread so no two loops trace the same line.
        spread = 1.0 + ((index * 7) % 11 - 5) / 50.0
        loops.append(
            LoopDefinition(
                loop_id=loop_id,
                name=name,
                area=area,
                service="Healthy, well-tuned loop",
                pv_unit=unit,
                behavior="healthy",
                seed=1301 + index,
                base_sp=setpoint,
                base_pv=setpoint,
                time_constant_seconds=round(tau * spread, 1),
                dead_time_seconds=10.0 if loop_id[0] == "F" else 15.0,
                controller_gain=gain,
                integral_gain=integral,
                process_noise=0.025,
                measurement_noise=0.05,
            )
        )
    return tuple(loops)
