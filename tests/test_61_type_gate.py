"""
tests/test_61_type_gate.py
Verify the layered type gate classification, ratchet enforcement, and gate behavior (Ticket 61).
"""
from tools.type_gate import check_ratchet, classify, evaluate_gate


def test_classify_hard_module_error():
    hard_prefixes = ["src/text_rules.py", "src/validators.py"]
    lines = [
        "src/text_rules.py:28: error: Name 'config' already defined (by an import)  [no-redef]",
        "src/app.py:1718: error: Incompatible types in assignment  [assignment]",
        "src/text_rules.py:28: note: Previous import here",
    ]
    hard, soft = classify(lines, hard_prefixes)
    assert len(hard) == 1
    assert "src/text_rules.py:28: error:" in hard[0]
    assert len(soft) == 1
    assert "src/app.py:1718: error:" in soft[0]


def test_classify_normalizes_windows_path_separators():
    hard_prefixes = ["src/text_rules.py"]
    lines = [
        r"src\text_rules.py:10: error: Incompatible types in assignment",
        r"src\app.py:20: error: Undefined variable",
    ]
    hard, soft = classify(lines, hard_prefixes)
    assert len(hard) == 1
    assert "text_rules.py" in hard[0]
    assert len(soft) == 1
    assert "app.py" in soft[0]


def test_classify_ignores_non_error_lines():
    hard_prefixes = ["src/text_rules.py"]
    lines = [
        "Success: no issues found in 20 source files",
        "Found 2 errors in 1 file (checked 20 source files)",
        "src/text_rules.py:10: note: See details here",
        "",
    ]
    hard, soft = classify(lines, hard_prefixes)
    assert hard == []
    assert soft == []


def test_ratchet_bites_when_soft_count_exceeds_ratchet():
    ratchet = 95
    assert check_ratchet(soft_count=96, ratchet=ratchet) == 1
    assert check_ratchet(soft_count=95, ratchet=ratchet) == 0
    assert check_ratchet(soft_count=94, ratchet=ratchet) == 0


def test_evaluate_gate_hard_error_bites():
    # Any hard error returns 1, regardless of soft error count or ratchet
    assert evaluate_gate(hard_count=1, soft_count=0, ratchet=10) == 1
    assert evaluate_gate(hard_count=1, soft_count=10, ratchet=10) == 1


def test_evaluate_gate_ratchet_bites():
    # 0 hard errors, soft count > ratchet returns 1
    assert evaluate_gate(hard_count=0, soft_count=11, ratchet=10) == 1
    # 0 hard errors, soft count <= ratchet returns 0
    assert evaluate_gate(hard_count=0, soft_count=10, ratchet=10) == 0
    assert evaluate_gate(hard_count=0, soft_count=9, ratchet=10) == 0
