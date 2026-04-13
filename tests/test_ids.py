from kbparser import ids


def test_doc_id_deterministic():
    a = ids.doc_id("a" * 64, "fidelity")
    b = ids.doc_id("a" * 64, "fidelity")
    assert a == b
    assert a.startswith("doc_")


def test_doc_id_varies_by_profile():
    a = ids.doc_id("a" * 64, "fidelity")
    b = ids.doc_id("a" * 64, "balanced")
    assert a != b


def test_section_id_varies_by_path_and_order():
    d = "doc_abc"
    assert ids.section_id(d, ["1"], 0) != ids.section_id(d, ["2"], 0)
    assert ids.section_id(d, ["1"], 0) != ids.section_id(d, ["1"], 1)


def test_record_id_depends_on_lineage():
    a = ids.record_id("doc_x", "chunk", ["sec_1", "blk_1"])
    b = ids.record_id("doc_x", "chunk", ["sec_1", "blk_2"])
    assert a != b
