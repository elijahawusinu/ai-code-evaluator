"""
ai-code-evaluator
-----------------
A test harness for grading candidate Python solutions (human- or AI-written)
against a task specification.

Each task lives in tasks/<name>/ and contains:
    task.json        {"function": "name", "description": "...", "timeout": 2.0}
    tests.json       [{"input": [args...], "expected": value, "name": "..."},
                      {"input": [...],   "raises": "ValueError"}]
    solutions/*.py   one or more candidate solutions to grade

Each solution is run in a separate subprocess with a timeout, so an infinite
loop, a crash, or a sys.exit() in one candidate can't take down the harness.
The result is a per-solution score plus a diagnosis of *why* each failing case
failed (wrong answer, exception, timeout), which is what makes the report
useful for improving the code rather than just ranking it.

Usage:
    python evaluator.py                      # grade every task
    python evaluator.py --task fizzbuzz      # one task
    python evaluator.py --json report.json   # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Case:
    name: str
    input: list[Any]
    expected: Any = None
    raises: str | None = None

    @classmethod
    def from_dict(cls, d: dict, idx: int) -> "Case":
        return cls(
            name=d.get("name", f"case {idx + 1}"),
            input=list(d.get("input", [])),
            expected=d.get("expected"),
            raises=d.get("raises"),
        )


@dataclass
class CaseResult:
    name: str
    passed: bool
    outcome: str          # "pass" | "wrong_answer" | "exception" | "timeout" | "no_function"
    expected: Any = None
    actual: Any = None
    error: str = ""


@dataclass
class SolutionResult:
    task: str
    solution: str
    passed: int
    total: int
    cases: list[CaseResult] = field(default_factory=list)
    load_error: str = ""

    @property
    def score(self) -> float:
        return round(100 * self.passed / self.total, 1) if self.total else 0.0

    def failure_breakdown(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.cases:
            if not c.passed:
                out[c.outcome] = out.get(c.outcome, 0) + 1
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = self.score
        d["failure_breakdown"] = self.failure_breakdown()
        return d


# ---------------------------------------------------------------------------
# Loading tasks
# ---------------------------------------------------------------------------

@dataclass
class Task:
    name: str
    function: str
    description: str
    timeout: float
    tests: list[Case]
    solutions: list[Path]


def load_task(path: Path) -> Task:
    meta = json.loads((path / "task.json").read_text(encoding="utf-8"))
    raw_tests = json.loads((path / "tests.json").read_text(encoding="utf-8"))
    tests = [Case.from_dict(t, i) for i, t in enumerate(raw_tests)]
    if not tests:
        raise ValueError(f"{path.name}: tests.json has no test cases")
    solutions = sorted((path / "solutions").glob("*.py"))
    return Task(
        name=path.name,
        function=meta["function"],
        description=meta.get("description", ""),
        timeout=float(meta.get("timeout", 2.0)),
        tests=tests,
        solutions=solutions,
    )


def discover_tasks(tasks_dir: Path = TASKS_DIR, only: str | None = None) -> list[Task]:
    tasks = []
    for p in sorted(tasks_dir.iterdir()):
        if p.is_dir() and (p / "task.json").exists() and (only is None or p.name == only):
            tasks.append(load_task(p))
    return tasks


# ---------------------------------------------------------------------------
# Running a candidate in isolation
# ---------------------------------------------------------------------------

_RUNNER = textwrap.dedent("""
    import json, sys, traceback, importlib.util
    spec = importlib.util.spec_from_file_location("candidate", sys.argv[1])
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except BaseException as e:
        print(json.dumps({"load_error": f"{type(e).__name__}: {e}"}))
        sys.exit(0)
    fn = getattr(mod, sys.argv[2], None)
    if fn is None or not callable(fn):
        print(json.dumps({"load_error": f"no callable named {sys.argv[2]!r}"}))
        sys.exit(0)
    results = []
    for case in json.loads(sys.stdin.read()):
        try:
            value = fn(*case["input"])
            # make sure the value survives JSON; tuples become lists on purpose
            json.dumps(value)
            results.append({"ok": True, "value": value})
        except BaseException as e:
            results.append({"ok": False, "exc": type(e).__name__, "msg": str(e)[:300]})
    print(json.dumps({"results": results}))
""")


def _normalise(v: Any) -> Any:
    """Tuples arrive from JSON as lists; treat them as equal."""
    if isinstance(v, tuple):
        return [_normalise(x) for x in v]
    if isinstance(v, list):
        return [_normalise(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _normalise(x) for k, x in v.items()}
    return v


def run_solution(task: Task, solution: Path, python: str = sys.executable) -> SolutionResult:
    cases_payload = json.dumps([{"input": c.input} for c in task.tests])
    try:
        proc = subprocess.run(
            [python, "-I", "-c", _RUNNER, str(solution), task.function],
            input=cases_payload, capture_output=True, text=True,
            timeout=task.timeout * len(task.tests) + 1,
        )
    except subprocess.TimeoutExpired:
        cases = [CaseResult(c.name, False, "timeout", c.expected, None,
                            f"exceeded {task.timeout}s per case") for c in task.tests]
        return SolutionResult(task.name, solution.name, 0, len(task.tests), cases)

    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        payload = {}

    if "load_error" in payload or "results" not in payload:
        err = payload.get("load_error") or (proc.stderr.strip()[-400:] or "candidate produced no output")
        cases = [CaseResult(c.name, False, "no_function", c.expected, None, err) for c in task.tests]
        return SolutionResult(task.name, solution.name, 0, len(task.tests), cases, load_error=err)

    cases: list[CaseResult] = []
    for c, r in zip(task.tests, payload["results"]):
        if c.raises:
            if not r["ok"] and r["exc"] == c.raises:
                cases.append(CaseResult(c.name, True, "pass", c.raises, r["exc"]))
            elif not r["ok"]:
                cases.append(CaseResult(c.name, False, "wrong_answer", c.raises, r["exc"],
                                        f"raised {r['exc']} instead of {c.raises}"))
            else:
                cases.append(CaseResult(c.name, False, "wrong_answer", c.raises, r["value"],
                                        f"returned {r['value']!r} instead of raising {c.raises}"))
            continue
        if not r["ok"]:
            cases.append(CaseResult(c.name, False, "exception", c.expected, None,
                                    f"{r['exc']}: {r['msg']}"))
        elif _normalise(r["value"]) == _normalise(c.expected):
            cases.append(CaseResult(c.name, True, "pass", c.expected, r["value"]))
        else:
            cases.append(CaseResult(c.name, False, "wrong_answer", c.expected, r["value"]))

    passed = sum(1 for c in cases if c.passed)
    return SolutionResult(task.name, solution.name, passed, len(cases), cases)


def evaluate(tasks: list[Task]) -> list[SolutionResult]:
    results = []
    for t in tasks:
        for s in t.solutions:
            results.append(run_solution(t, s))
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _short(value: Any, limit: int = 70) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _explain_diff(expected: Any, actual: Any) -> str:
    """Human-friendly description of how `actual` differs from `expected`."""
    e, a = _normalise(expected), _normalise(actual)
    if isinstance(e, list) and isinstance(a, list):
        if len(e) != len(a):
            msg = f"length {len(a)}, expected {len(e)}"
        else:
            msg = ""
        for i, (x, y) in enumerate(zip(e, a)):
            if x != y:
                sep = "; " if msg else ""
                return f"{msg}{sep}first difference at index {i}: expected {_short(x)}, got {_short(y)}"
        return msg or f"expected {_short(e)}, got {_short(a)}"
    return f"expected {_short(e)}, got {_short(a)}"


def print_report(results: list[SolutionResult], verbose: bool = False) -> None:
    by_task: dict[str, list[SolutionResult]] = {}
    for r in results:
        by_task.setdefault(r.task, []).append(r)

    for task, rs in by_task.items():
        print(f"\n== {task} ==")
        rs.sort(key=lambda r: (-r.score, r.solution))
        for r in rs:
            flag = "PASS" if r.passed == r.total else "FAIL"
            bd = r.failure_breakdown()
            why = f"  ({', '.join(f'{k}={v}' for k, v in bd.items())})" if bd else ""
            print(f"  [{flag}] {r.solution:<28} {r.passed:>2}/{r.total:<2} {r.score:>5.1f}%{why}")
            if r.load_error:
                print(f"         load error: {r.load_error}")
            if verbose or (r.passed != r.total and not r.load_error):
                for c in r.cases:
                    if c.passed and not verbose:
                        continue
                    mark = "ok " if c.passed else "X  "
                    line = f"         {mark}{c.name}"
                    if not c.passed:
                        if c.outcome == "wrong_answer" and not c.error:
                            line += f": {_explain_diff(c.expected, c.actual)}"
                        else:
                            line += f": {c.error[:160]}"
                    print(line)
    total = sum(r.passed for r in results)
    cases = sum(r.total for r in results)
    print(f"\nOverall: {total}/{cases} cases passed across {len(results)} solution(s)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Grade candidate solutions against task test cases")
    p.add_argument("--tasks-dir", default=str(TASKS_DIR))
    p.add_argument("--task", help="only run this task")
    p.add_argument("--json", metavar="FILE", help="write full results as JSON")
    p.add_argument("-v", "--verbose", action="store_true", help="show every case, not just failures")
    args = p.parse_args(argv)

    tasks = discover_tasks(Path(args.tasks_dir), args.task)
    if not tasks:
        print("No tasks found.", file=sys.stderr)
        return 2
    results = evaluate(tasks)
    print_report(results, args.verbose)
    if args.json:
        Path(args.json).write_text(json.dumps([r.to_dict() for r in results], indent=2))
        print(f"JSON written to {args.json}")
    return 0 if all(r.passed == r.total for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
