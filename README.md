# ai-code-evaluator

A test harness that grades candidate Python solutions — human-written or AI-generated — against a
task specification, runs each one in an isolated subprocess with a timeout, and reports not just a
score but *why* each failing case failed.

I built this out of my work evaluating AI-generated code, where the job is to design tasks and test
cases that expose off-by-one errors, missed edge cases, wrong exception handling, and code that
hangs. This tool automates the mechanical part of that review so the human time goes into writing
better tests and diagnosing the failures.

## How it works

```
tasks/
  fizzbuzz/
    task.json          # which function to call, description, per-case timeout
    tests.json         # inputs + expected outputs (or expected exception)
    solutions/
      correct.py       # one or more candidates to grade
      off_by_one.py
      wrong_order.py
```

Each candidate is loaded in a **separate Python process** (`python -I`), given the test inputs on
stdin, and returns results as JSON. That means a candidate that infinite-loops, calls `sys.exit()`,
has a syntax error, or raises inside import can't take the harness down — it just scores zero with
the reason recorded.

Every failing case is classified as one of:

| Outcome | Meaning |
|---|---|
| `wrong_answer` | Ran fine, returned the wrong value (or didn't raise when it should have) |
| `exception` | Raised an unexpected exception |
| `timeout` | Exceeded the task's per-case time limit |
| `no_function` | Couldn't be imported, or the named function doesn't exist |

For list results the report points at the **first differing index** instead of dumping both lists.

## Quick start

```bash
git clone https://github.com/elijahawusinu/ai-code-evaluator.git
cd ai-code-evaluator

python evaluator.py                    # grade every task
python evaluator.py --task two_sum     # one task
python evaluator.py --json report.json # machine-readable results
python evaluator.py -v                 # show passing cases too
```

Sample output:

```
== fizzbuzz ==
  [PASS] correct.py                    5/5  100.0%
  [FAIL] wrong_order.py                3/5   60.0%  (wrong_answer=2)
         X  first 15: first difference at index 14: expected 'FizzBuzz', got 'Fizz'
         X  n = 30 ends in FizzBuzz: first difference at index 14: expected 'FizzBuzz', got 'Fizz'
  [FAIL] off_by_one.py                 2/5   40.0%  (wrong_answer=3)
         X  first 15: length 14, expected 15
         X  n = 1: length 0, expected 1

== parse_duration ==
  [PASS] regex.py                      9/9  100.0%
  [FAIL] lenient.py                    5/9   55.6%  (wrong_answer=4)
         X  empty string raises: returned 0 instead of raising ValueError
         X  wrong order raises: returned 5400 instead of raising ValueError
  [FAIL] infinite_loop.py              0/9    0.0%  (timeout=9)
         X  hours and minutes: exceeded 1.0s per case
...
Overall: 43/63 cases passed across 9 solution(s)
```

The three bundled tasks each ship with one correct solution and two realistically buggy ones (the
kinds of mistakes that actually show up in generated code: off-by-one ranges, condition order,
returning `None` instead of raising, reusing an element, being too lenient on input, hanging).

## Writing your own task

1. Create `tasks/<name>/task.json`:
   ```json
   {"function": "my_func", "description": "What it should do", "timeout": 2.0}
   ```
2. Create `tasks/<name>/tests.json` — a list of cases. Use `expected` for a return value or `raises`
   for an exception class name:
   ```json
   [
     {"name": "happy path", "input": [1, 2], "expected": 3},
     {"name": "bad input",  "input": ["a"],  "raises": "TypeError"}
   ]
   ```
3. Drop candidate `.py` files in `tasks/<name>/solutions/` and run `python evaluator.py --task <name>`.

Inputs and outputs must be JSON-serialisable. Tuples returned by a candidate are compared as lists.

## Running the tests

```bash
pip install -r requirements.txt
pytest
```

The suite (14 tests) covers every outcome type — including a deliberately hanging candidate and one
that calls `sys.exit()` — and checks that every bundled task has at least one perfect solution, which
guards against broken test cases.

## Possible next steps

- Hidden test sets (grade against cases the solver never sees)
- Memory limits via `resource.setrlimit`
- Side-by-side comparison report across several model outputs for the same task
- Support for stdin/stdout programs, not just functions

## Author

Elijah Awusinu — Software Engineer / Expert Contributor (AI code evaluation),
B.S. Information Technology (Towson University).
