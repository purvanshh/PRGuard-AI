"""Generate N varied evaluation dataset fixtures for PRGuard AI."""

import json
import os
import random
from pathlib import Path

random.seed(42)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "src" / "prguard_ai" / "evaluation" / "dataset"
NUM_FIXTURES = 520


def _diff(before, added, after, old_line, file="app/controller.py"):
    lines_before = [l for l in before.split("\n") if l] if before else []
    added_lines = added.split("\n") if "\n" in added else [added]
    after_lines = [l for l in after.split("\n") if l] if after else []

    if not lines_before and after_lines:
        all_added = added_lines + after_lines
        context_after = []
    else:
        all_added = added_lines
        context_after = after_lines

    start = old_line - len(lines_before)
    old_count = len(lines_before) + len(context_after)
    if old_count == 0:
        old_count = 0
    new_lines_total = len(lines_before) + len(all_added) + len(context_after)
    new_count = max(1, new_lines_total)

    hdr = (
        f"diff --git a/{file} b/{file}\n"
        f"index 111..222 100644\n"
        f"--- a/{file}\n"
        f"+++ b/{file}\n"
        f"@@ -{start},{old_count} +{start},{new_count} @@\n"
    )
    parts = []
    for l in lines_before:
        parts.append(f" {l}")
    for l in all_added:
        parts.append(f"+{l}")
    for l in context_after:
        parts.append(f" {l}")
    return hdr + "\n".join(parts)


FIXTURE_TEMPLATES = [
    # ---- Security issues ----
    {
        "category": "security",
        "desc": "eval() with user input",
        "diff": lambda n: _diff(
            "def process(data):",
            '    result = eval(data)  # DANGER: user input to eval',
            '    return result',
            n, "app/process.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "eval() called on potentially user-controlled input", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "SQL injection via string concatenation",
        "diff": lambda n: _diff(
            "def get_user(name):",
            '    query = "SELECT * FROM users WHERE name = \'" + name + "\'"',
            "    return db.execute(query)",
            n, "app/queries.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "SQL injection via string-concatenated query", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "Command injection with shell=True",
        "diff": lambda n: _diff(
            "import subprocess",
            '    subprocess.run(f"ping {host}", shell=True)',
            '    return output',
            n, "app/network.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Command injection via shell=True with interpolated input", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "Hardcoded secret",
        "diff": lambda n: _diff(
            "# configuration",
            'SECRET_KEY = "sk-live-abcdef1234567890"',
            "",
            n, "config/prod.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Hardcoded secret detected", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "Pickle deserialization",
        "diff": lambda n: _diff(
            "import pickle",
            '    data = pickle.loads(user_input)',
            '    return data',
            n, "app/serialize.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Unsafe pickle deserialization with untrusted input", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "Path traversal",
        "diff": lambda n: _diff(
            "def read_file(filename):",
            '    path = f"/var/data/{filename}"',
            "    return open(path).read()",
            n, "app/files.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Path traversal vulnerability via unvalidated filename", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "SSRF via user-controlled URL",
        "diff": lambda n: _diff(
            "import requests",
            '    resp = requests.get(url, timeout=5)',
            '    return resp.text',
            n, "app/fetch.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Server-side request forgery via user-controlled URL", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "Insecure deserialization yaml",
        "diff": lambda n: _diff(
            "import yaml",
            '    config = yaml.load(user_data)',
            '    return config',
            n, "app/config.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Unsafe yaml.load allows arbitrary code execution", "severity": "high"},
    },
    {
        "category": "security",
        "desc": "Assert statement used for validation",
        "diff": lambda n: _diff(
            "def validate(user):",
            '    assert user.is_admin, "Not authorized"',
            "    return True",
            n, "app/auth.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "assert used for validation; disabled with -O flag", "severity": "medium"},
    },
    {
        "category": "security",
        "desc": "MD5 hash used for passwords",
        "diff": lambda n: _diff(
            "import hashlib",
            '    digest = hashlib.md5(password.encode()).hexdigest()',
            '    return digest',
            n, "app/crypto.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "MD5 hash used; consider bcrypt or Argon2", "severity": "medium"},
    },
    {
        "category": "security",
        "desc": "Template injection",
        "diff": lambda n: _diff(
            "from jinja2 import Template",
            '    tmpl = Template(f"Hello {user_input}")',
            '    return tmpl.render()',
            n, "app/templates.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Server-side template injection via unescaped user input", "severity": "high"},
    },
    # ---- Logic issues ----
    {
        "category": "logic",
        "desc": "Bare except clause",
        "diff": lambda n: _diff(
            "try:",
            '    process(data)',
            "except:",
            n, "app/errors.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Bare except clause hides unexpected errors", "severity": "medium"},
    },
    {
        "category": "logic",
        "desc": "Off-by-one in range",
        "diff": lambda n: _diff(
            "def process_items(items):",
            '    for i in range(len(items) + 1):',
            "        print(items[i])",
            n, "app/loops.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Off-by-one: range(len(items)+1) will cause IndexError", "severity": "high"},
    },
    {
        "category": "logic",
        "desc": "None dereference",
        "diff": lambda n: _diff(
            "def get_name(user):",
            '    return user.name.upper()',
            "",
            n, "app/users.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Potential None dereference if user is None", "severity": "medium"},
    },
    {
        "category": "logic",
        "desc": "Unhandled exception in async",
        "diff": lambda n: _diff(
            "async def handler(request):",
            '    data = await fetch_data(request.id)',
            '    return JSONResponse(data)',
            n, "app/handlers.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Unhandled exception will produce a 500 response", "severity": "medium"},
    },
    {
        "category": "logic",
        "desc": "TOCTOU race condition",
        "diff": lambda n: _diff(
            "if os.path.exists(path):",
            '    with open(path) as f:',
            "        return f.read()",
            n, "app/files.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "TOCTOU race condition: file may be deleted between exists and open", "severity": "medium"},
    },
    {
        "category": "logic",
        "desc": "Infinite loop",
        "diff": lambda n: _diff(
            "def poll():",
            '    while True:',
            "        pass",
            n, "app/poller.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Infinite loop without break condition", "severity": "medium"},
    },
    {
        "category": "logic",
        "desc": "Mutable default argument",
        "diff": lambda n: _diff(
            "def add_item(item, items=[]):",
            '    items.append(item)',
            '    return items',
            n, "app/utils.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Mutable default argument shared across calls", "severity": "low"},
    },
    {
        "category": "logic",
        "desc": "Variable shadowing",
        "diff": lambda n: _diff(
            "def filter(items):",
            '    items = [x for x in items if x > 0]',
            '    return items',
            n, "app/filter.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Variable shadows built-in function 'filter'", "severity": "low"},
    },
    {
        "category": "logic",
        "desc": "Comparison with None using ==",
        "diff": lambda n: _diff(
            "if result == None:",
            '    return default_value',
            '    return result',
            n, "app/check.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Comparison to None should use 'is' not '=='", "severity": "low"},
    },
    {
        "category": "logic",
        "desc": "Forgotten await",
        "diff": lambda n: _diff(
            "async def get_data():",
            '    result = fetch_data()',
            '    return result',
            n, "app/async_utils.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Coroutine 'fetch_data' was never awaited", "severity": "high"},
    },
    {
        "category": "logic",
        "desc": "Dead code after return",
        "diff": lambda n: _diff(
            "def compute(x):",
            '    return x * 2',
            '    print("done")',
            n, "app/math.py"
        ),
        "issue": lambda n: {"line": n + 2, "message": "Unreachable code after return statement", "severity": "low"},
    },
    {
        "category": "logic",
        "desc": "Division by zero",
        "diff": lambda n: _diff(
            "def divide(a, b):",
            '    return a / b',
            "",
            n, "app/math.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Division by zero if b is 0", "severity": "high"},
    },
    # ---- Style issues ----
    {
        "category": "style",
        "desc": "TODO comment",
        "diff": lambda n: _diff(
            "def process():",
            '    pass  # TODO: implement error handling',
            "",
            n, "app/todo.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "TODO present in newly added code", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Long line over 120 chars",
        "diff": lambda n: _diff(
            "def long():",
            '    result = some_function_with_many_arguments(arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, arg10, arg11, arg12, arg13, arg14, arg15)',
            '    return result',
            n, "app/lines.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Line exceeds 120 character limit", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Missing function docstring",
        "diff": lambda n: _diff(
            "",
            'def calculate(x, y):',
            '    return x + y',
            n, "app/math.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Function is missing a docstring", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Trailing whitespace",
        "diff": lambda n: _diff(
            "def clean():",
            '    pass    ',
            '    return True',
            n, "app/clean.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Line has trailing whitespace", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "CamelCase function name",
        "diff": lambda n: _diff(
            "",
            'def getDataFromAPI():',
            '    """Fetch data."""',
            n, "app/naming.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Function name should use snake_case", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Unused import",
        "diff": lambda n: _diff(
            "import os",
            'import sys',
            'import json',
            n, "app/imports.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Unused import: sys", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Unused variable",
        "diff": lambda n: _diff(
            "def process(data):",
            '    temp = transform(data)',
            '    return data',
            n, "app/process.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Unused variable 'temp'", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Multiple imports on one line",
        "diff": lambda n: _diff(
            "",
            'import os, sys, json, re, math',
            "",
            n, "app/imports.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "Multiple imports on one line", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Missing module docstring",
        "diff": lambda n: _diff(
            "",
            'from pathlib import Path',
            "",
            n, "app/module.py"
        ),
        "issue": lambda n: {"line": n, "message": "Module is missing a module-level docstring", "severity": "low"},
    },
    {
        "category": "style",
        "desc": "Mixed indentation",
        "diff": lambda n: _diff(
            "def render():",
            '\treturn template.render()',
            '    # back to spaces',
            n, "app/template.py"
        ),
        "issue": lambda n: {"line": n + 1, "message": "File uses mixed tabs and spaces for indentation", "severity": "low"},
    },
    # ---- Multi-issue fixtures ----
    {
        "category": "mixed",
        "desc": "eval + bare except",
        "diff": lambda n: _diff(
            "try:",
            f"    result = eval(data)",
            f"except:\n    pass",
            n, "app/process.py"
        ),
        "issues": lambda n: [
            {"line": n + 1, "message": "eval() called on potentially user-controlled input", "severity": "high"},
            {"line": n + 2, "message": "Bare except clause hides unexpected errors", "severity": "medium"},
        ],
    },
    {
        "category": "mixed",
        "desc": "SQL injection + TODO",
        "diff": lambda n: _diff(
            "def search(term):",
            '    query = "SELECT * FROM items WHERE name LIKE \'%" + term + "%\'"  # TODO: use parameterized',
            "    return db.execute(query)",
            n, "app/search.py"
        ),
        "issues": lambda n: [
            {"line": n + 1, "message": "SQL injection via string-concatenated query", "severity": "high"},
            {"line": n + 1, "message": "TODO present in newly added code", "severity": "low"},
        ],
    },
    {
        "category": "mixed",
        "desc": "Command injection + long line",
        "diff": lambda n: _diff(
            "def ping_host(hostname, timeout, retries, verbose, output_format, log_level, use_sudo, resolve_dns):",
            '    subprocess.run(f"ping -c 1 {hostname}", shell=True, timeout=timeout, capture_output=verbose, check=True, encoding="utf-8")',
            "    return output",
            n, "app/network.py"
        ),
        "issues": lambda n: [
            {"line": n + 1, "message": "Command injection via shell=True with interpolated input", "severity": "high"},
            {"line": n + 1, "message": "Line exceeds 120 character limit", "severity": "low"},
        ],
    },
    {
        "category": "mixed",
        "desc": "Path traversal + missing docstring",
        "diff": lambda n: _diff(
            "",
            'def read_log(log_name):',
            '    return open(f"/var/log/{log_name}").read()',
            n, "app/logs.py"
        ),
        "issues": lambda n: [
            {"line": n + 1, "message": "Function is missing a docstring", "severity": "low"},
            {"line": n + 2, "message": "Path traversal vulnerability via unvalidated filename", "severity": "high"},
        ],
    },
    {
        "category": "mixed",
        "desc": "Null dereference + TODO",
        "diff": lambda n: _diff(
            "def format_user(user):",
            '    return user.name.upper()  # TODO: handle None',
            "",
            n, "app/format.py"
        ),
        "issues": lambda n: [
            {"line": n + 1, "message": "Potential None dereference if user is None", "severity": "medium"},
            {"line": n + 1, "message": "TODO present in newly added code", "severity": "low"},
        ],
    },
    {
        "category": "mixed",
        "desc": "Pickle + bare except",
        "diff": lambda n: _diff(
            "try:",
            f"    data = pickle.loads(payload)",
            "except:\n    data = {}",
            n, "app/load.py"
        ),
        "issues": lambda n: [
            {"line": n + 1, "message": "Unsafe pickle deserialization with untrusted input", "severity": "high"},
            {"line": n + 2, "message": "Bare except clause hides unexpected errors", "severity": "medium"},
        ],
    },
    # ---- No-issue (clean) fixtures ----
    {
        "category": "no_issue",
        "desc": "Clean formatting fix",
        "diff": lambda n: _diff(
            "def clean():",
            '    return formatted_result',
            "",
            n, "app/clean.py"
        ),
        "issues": lambda n: [],
    },
    {
        "category": "no_issue",
        "desc": "Simple import addition",
        "diff": lambda n: _diff(
            "import os",
            'import json',
            "",
            n, "app/imports.py"
        ),
        "issues": lambda n: [],
    },
    {
        "category": "no_issue",
        "desc": "Refactored constant",
        "diff": lambda n: _diff(
            "# Constants",
            'MAX_RETRIES = 3',
            "",
            n, "config/constants.py"
        ),
        "issues": lambda n: [],
    },
    {
        "category": "no_issue",
        "desc": "Type annotation addition",
        "diff": lambda n: _diff(
            "",
            'def greet(name: str) -> str:',
            '    return f"Hello, {name}"',
            n, "app/greet.py"
        ),
        "issues": lambda n: [],
    },
    {
        "category": "no_issue",
        "desc": "Logging improvement",
        "diff": lambda n: _diff(
            "import logging",
            'logger = logging.getLogger(__name__)',
            "",
            n, "app/logging.py"
        ),
        "issues": lambda n: [],
    },
    {
        "category": "no_issue",
        "desc": "Safe parameterized query",
        "diff": lambda n: _diff(
            "def find_user(email):",
            '    return db.execute("SELECT * FROM users WHERE email = %s", (email,))',
            "",
            n, "app/queries.py"
        ),
        "issues": lambda n: [],
    },
    {
        "category": "no_issue",
        "desc": "Safe subprocess without shell",
        "diff": lambda n: _diff(
            "import subprocess",
            '    result = subprocess.run(["ls", "-l"], capture_output=True)',
            "    return result.stdout",
            n, "app/run.py"
        ),
        "issues": lambda n: [],
    },
]


def generate():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Clear existing fixtures
    for f in OUTPUT_DIR.glob("fixture_*.json"):
        f.unlink()

    files = []
    for i in range(NUM_FIXTURES):
        template = random.choice(FIXTURE_TEMPLATES)
        line = random.randint(5, 50)
        diff_text = template["diff"](line)

        if template["category"] == "no_issue":
            issues = []
        elif "issues" in template:
            issues = template["issues"](line)
        else:
            issues = [template["issue"](line)]

        # Shuffle severity occasionally
        if issues and random.random() < 0.1:
            for iss in issues:
                iss["severity"] = random.choice(["low", "medium", "high"])

        fixture = {
            "id": f"fixture_{i+1:04d}",
            "description": template["desc"],
            "diff": diff_text,
            "expected_issues": issues,
        }

        path = OUTPUT_DIR / f"fixture_{i+1:04d}.json"
        path.write_text(json.dumps(fixture, indent=2) + "\n")
        files.append(path)

    print(f"Generated {len(files)} fixtures in {OUTPUT_DIR}")
    print(f"Categories used: {len(FIXTURE_TEMPLATES)} unique templates")


if __name__ == "__main__":
    generate()
