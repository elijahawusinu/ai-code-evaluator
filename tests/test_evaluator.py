import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluator import (  # noqa: E402
    Task,
    Case,
    _explain_diff,
    _normalise,
    discover_tasks,
    load_task,
    main,
    run_solution,
)


def make_task(tmp_path, function, tests, solutions: dict[str, str], timeout=1.0) -> Task:
    """Write a task directory on disk and load it, exactly as the CLI would."""
    d = tmp_path / "mytask"
    (d / "solutions").mkdir(parents=True)
    (d / "task.json").write_text(json.dumps({"function": function, "timeout": timeout}))
    (d / "tests.json").write_text(json.dumps(tests))
    for name, code in solutions.items():
        (d / "solutions" / f"{name}.py").write_text(code)
    return load_task(d)


SQUARE_TESTS = [
    {"name": "two", "input": [2], "expected": 4},
    {"name": "zero", "input": [0], "expected": 0},
    {"name": "negative", "input": [-3], "expected": 9},
    {"name": "string raises", "input": ["x"], "raises": "TypeError"},
]


def test_correct_solution_passes_everything(tmp_path):
    t = make_task(tmp_path, "square", SQUARE_TESTS,
                  {"good": "def square(n):\n    if not isinstance(n, int): raise TypeError\n    return n*n\n"})
    r = run_solution(t, t.solutions[0])
    assert r.passed == r.total == 4
    assert r.score == 100.0
    assert r.failure_breakdown() == {}


def test_wrong_answer_is_classified(tmp_path):
    t = make_task(tmp_path, "square", SQUARE_TESTS,
                  {"cube": "def square(n):\n    if not isinstance(n, int): raise TypeError\n    return n**3\n"})
    r = run_solution(t, t.solutions[0])
    outcomes = {c.name: c.outcome for c in r.cases}
    assert outcomes == {"two": "wrong_answer", "zero": "pass", "negative": "wrong_answer",
                        "string raises": "pass"}
    assert r.failure_breakdown() == {"wrong_answer": 2}


def test_exception_is_classified(tmp_path):
    t = make_task(tmp_path, "square", SQUARE_TESTS[:1],
                  {"boom": "def square(n):\n    return n / 0\n"})
    r = run_solution(t, t.solutions[0])
    assert r.cases[0].outcome == "exception"
    assert "ZeroDivisionError" in r.cases[0].error


def test_expected_exception_not_raised(tmp_path):
    t = make_task(tmp_path, "square", [SQUARE_TESTS[3]],
                  {"lenient": "def square(n):\n    return 0\n"})
    r = run_solution(t, t.solutions[0])
    assert r.cases[0].outcome == "wrong_answer"
    assert "instead of raising TypeError" in r.cases[0].error


def test_wrong_exception_type(tmp_path):
    t = make_task(tmp_path, "square", [SQUARE_TESTS[3]],
                  {"wrongexc": "def square(n):\n    raise ValueError('nope')\n"})
    r = run_solution(t, t.solutions[0])
    assert "raised ValueError instead of TypeError" in r.cases[0].error


def test_timeout_is_caught(tmp_path):
    t = make_task(tmp_path, "square", SQUARE_TESTS[:2],
                  {"hang": "def square(n):\n    while True: pass\n"}, timeout=0.3)
    r = run_solution(t, t.solutions[0])
    assert r.passed == 0
    assert all(c.outcome == "timeout" for c in r.cases)


def test_missing_function_and_syntax_error(tmp_path):
    t = make_task(tmp_path, "square", SQUARE_TESTS[:1],
                  {"wrongname": "def sq(n):\n    return n*n\n",
                   "broken": "def square(n)\n    return n*n\n"})
    results = {s.name: run_solution(t, s) for s in t.solutions}
    assert "no callable named 'square'" in results["wrongname.py"].load_error
    assert "SyntaxError" in results["broken.py"].load_error
    assert results["broken.py"].cases[0].outcome == "no_function"


def test_sys_exit_in_candidate_does_not_kill_harness(tmp_path):
    t = make_task(tmp_path, "square", SQUARE_TESTS[:1],
                  {"exiter": "import sys\ndef square(n):\n    sys.exit(1)\n"})
    r = run_solution(t, t.solutions[0])
    assert r.cases[0].outcome == "exception"
    assert "SystemExit" in r.cases[0].error


def test_tuple_results_compare_equal_to_lists(tmp_path):
    t = make_task(tmp_path, "pair", [{"input": [1, 2], "expected": [1, 2]}],
                  {"tup": "def pair(a, b):\n    return (a, b)\n"})
    assert run_solution(t, t.solutions[0]).passed == 1


def test_normalise_and_explain_diff():
    assert _normalise((1, (2, 3))) == [1, [2, 3]]
    assert "index 1" in _explain_diff([1, 2, 3], [1, 9, 3])
    assert _explain_diff([1, 2, 3], [1, 2]).startswith("length 2, expected 3")
    assert _explain_diff(5, 6) == "expected 5, got 6"


def test_load_task_rejects_empty_tests(tmp_path):
    with pytest.raises(ValueError):
        make_task(tmp_path, "f", [], {})


def test_bundled_tasks_have_a_perfect_solution_each():
    """Every shipped task must include at least one solution that scores 100%,
    otherwise the task's tests are probably wrong."""
    tasks = discover_tasks(ROOT / "tasks")
    assert {t.name for t in tasks} == {"fizzbuzz", "two_sum", "parse_duration"}
    for t in tasks:
        scores = [run_solution(t, s).score for s in t.solutions]
        assert 100.0 in scores, f"{t.name} has no fully-correct solution"
        assert any(s < 100.0 for s in scores), f"{t.name} has no buggy solution to grade"


def test_cli_writes_json_and_exit_code(tmp_path, capsys):
    out = tmp_path / "r.json"
    code = main(["--tasks-dir", str(ROOT / "tasks"), "--task", "fizzbuzz", "--json", str(out)])
    assert code == 1  # buggy solutions exist on purpose
    data = json.loads(out.read_text())
    assert {d["solution"] for d in data} == {"correct.py", "off_by_one.py", "wrong_order.py"}
    assert "first difference at index 14" in capsys.readouterr().out


def test_cli_no_tasks(tmp_path):
    assert main(["--tasks-dir", str(tmp_path)]) == 2
