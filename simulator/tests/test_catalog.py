from collections import Counter

from simcraft import load_catalog


def test_catalog_is_complete_and_self_consistent() -> None:
    catalog = load_catalog()

    assert catalog.validate() == ()
    assert len(catalog.loops) == 50
    assert len(catalog.signals) == 500
    assert len(catalog.scenarios) == 20
    assert Counter(signal.scope for signal in catalog.signals) == {
        "control_loop": 250,
        "plant_context": 250,
    }
    assert len({signal.opcua_node_id for signal in catalog.signals}) == 500
    assert len(catalog.digest) == 64


def test_every_loop_has_pv_sp_op_mode_and_final_element_feedback() -> None:
    catalog = load_catalog()
    for loop in catalog.loops:
        suffixes = {
            signal.node_identifier.rsplit(".", 1)[-1]
            for signal in catalog.signals
            if signal.loop_id == loop.loop_id
        }
        assert suffixes == {"PV", "SP", "OP", "MODE", "MVFB"}
