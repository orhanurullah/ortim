# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Six default mutation cases — one per bug class.

Each case is intentionally small (< 30 lines of code) so the diff
between `original_code` and `mutated_code` is unambiguous and the
Reviewer's job is purely about catching the bug, not understanding a
large surface area. Acceptance criteria are written in binary,
Phase-0-rubric form (Hard Rule 10) — no soft words like "appropriately"
or "user-friendly" that would muddy the catch signal.
"""

from __future__ import annotations

from runtime.mutation.case import MutationCase


_OFF_BY_ONE = MutationCase(
    name="sum_consecutive_pairs",
    bug_class="off-by-one",
    language="Python",
    task_title="Implement sum_consecutive_pairs",
    task_description=(
        "Implement a pure function sum_consecutive_pairs(nums) that "
        "returns a list where output[i] = nums[i] + nums[i+1] for all "
        "valid i. Single-element and empty inputs return an empty list."
    ),
    module_scope="arithmetic",
    acceptance_criteria=[
        "sum_consecutive_pairs([1, 2, 3, 4]) returns [3, 5, 7]",
        "sum_consecutive_pairs([10]) returns []",
        "sum_consecutive_pairs([]) returns []",
        "Function does not raise IndexError for any non-empty input list of integers",
    ],
    rfc_section="§4 arithmetic",
    rfc_excerpt=(
        "§4 — arithmetic helpers. Pure functions over int lists, no I/O. "
        "Sum-of-pairs is the only operation in scope for this task."
    ),
    file_path="arithmetic/pairs.py",
    original_code=(
        "def sum_consecutive_pairs(nums: list[int]) -> list[int]:\n"
        "    result: list[int] = []\n"
        "    for i in range(len(nums) - 1):\n"
        "        result.append(nums[i] + nums[i + 1])\n"
        "    return result\n"
    ),
    mutated_code=(
        "def sum_consecutive_pairs(nums: list[int]) -> list[int]:\n"
        "    result: list[int] = []\n"
        "    for i in range(len(nums)):\n"
        "        result.append(nums[i] + nums[i + 1])\n"
        "    return result\n"
    ),
    bug_keywords=[
        "indexerror", "index error", "out of bound", "off-by-one",
        "off by one", "range(len", "i + 1", "last element",
    ],
)


_NULL_CHECK_REMOVED = MutationCase(
    name="get_user_display_name",
    bug_class="null-check-removed",
    language="TypeScript",
    task_title="Implement getUserDisplayName",
    task_description=(
        "Implement getUserDisplayName(user) that returns user.displayName "
        "when present and non-empty, otherwise the literal string "
        "'Anonymous'. Must not throw on null, undefined, or "
        "missing-property inputs."
    ),
    module_scope="user",
    acceptance_criteria=[
        "getUserDisplayName({ displayName: 'Alice' }) returns 'Alice'",
        "getUserDisplayName({}) returns 'Anonymous'",
        "getUserDisplayName(null) returns 'Anonymous'",
        "getUserDisplayName(undefined) returns 'Anonymous'",
        "Function never throws TypeError for any input",
    ],
    rfc_section="§4 user",
    rfc_excerpt=(
        "§4 — user module. Display-name helper used by the UI. "
        "Receives the User object from the auth context; the object "
        "can be null between login attempts."
    ),
    file_path="user/display.ts",
    original_code=(
        "export function getUserDisplayName(user: { displayName?: string } | null | undefined): string {\n"
        "  if (user && user.displayName) {\n"
        "    return user.displayName;\n"
        "  }\n"
        "  return 'Anonymous';\n"
        "}\n"
    ),
    mutated_code=(
        "export function getUserDisplayName(user: { displayName?: string } | null | undefined): string {\n"
        "  return user.displayName || 'Anonymous';\n"
        "}\n"
    ),
    bug_keywords=[
        "null", "undefined", "typeerror", "throws", "throw",
        "cannot read", "optional chain", "?.", "null check",
    ],
)


_AUTH_BYPASS = MutationCase(
    name="is_authorized",
    bug_class="auth-bypass",
    language="Python",
    task_title="Implement is_authorized",
    task_description=(
        "Implement is_authorized(user, resource) that returns True iff "
        "user.role == 'admin' OR user.id == resource.owner_id. Any other "
        "combination returns False."
    ),
    module_scope="auth",
    acceptance_criteria=[
        "is_authorized(User(id=1, role='admin'), Resource(owner_id=2)) returns True",
        "is_authorized(User(id=2, role='user'), Resource(owner_id=2)) returns True",
        "is_authorized(User(id=3, role='user'), Resource(owner_id=2)) returns False",
        "is_authorized(User(id=3, role='guest'), Resource(owner_id=2)) returns False",
        "Function does not unconditionally return True",
    ],
    rfc_section="§5 auth",
    rfc_excerpt=(
        "§5 — authorization. Two-condition rule: admins can touch any "
        "resource; non-admins only the resources they own. Used by every "
        "write endpoint."
    ),
    file_path="auth/authorize.py",
    original_code=(
        "def is_authorized(user, resource) -> bool:\n"
        "    return user.role == 'admin' or user.id == resource.owner_id\n"
    ),
    mutated_code=(
        "def is_authorized(user, resource) -> bool:\n"
        "    # TODO: implement actual check\n"
        "    return True\n"
    ),
    bug_keywords=[
        "always true", "unconditionally", "bypass", "todo",
        "stub", "no check", "missing check", "returns true",
        "always return", "auth bypass",
    ],
)


_SQL_INJECTION = MutationCase(
    name="find_user_by_name",
    bug_class="sql-injection",
    language="Python",
    task_title="Implement find_user_by_name",
    task_description=(
        "Implement find_user_by_name(conn, name) that fetches the first "
        "user row from the database whose name column equals the input. "
        "Returns None when no match. The SQL must be parameterized — "
        "user input must not be interpolated into the query string."
    ),
    module_scope="repository",
    acceptance_criteria=[
        "Query uses parameterized SQL (? placeholder, not string interpolation)",
        "Returns the first matching row when one exists",
        "Returns None when no row matches",
        "Untrusted user input is not concatenated into the SQL string",
    ],
    rfc_section="§6 repository",
    rfc_excerpt=(
        "§6 — repository. Uses sqlite3 with parameterized queries. "
        "Trust boundary: the `name` argument comes from HTTP and is "
        "considered untrusted; never interpolate it into SQL."
    ),
    file_path="repository/users.py",
    original_code=(
        "def find_user_by_name(conn, name: str):\n"
        "    cursor = conn.cursor()\n"
        "    cursor.execute('SELECT * FROM users WHERE name = ?', (name,))\n"
        "    return cursor.fetchone()\n"
    ),
    mutated_code=(
        "def find_user_by_name(conn, name: str):\n"
        "    cursor = conn.cursor()\n"
        "    cursor.execute(f\"SELECT * FROM users WHERE name = '{name}'\")\n"
        "    return cursor.fetchone()\n"
    ),
    bug_keywords=[
        "sql injection", "injection", "f-string", "f\"select",
        "concatenat", "format", "parameterized", "not parameterized",
        "untrusted", "string interpolation", "user input",
    ],
)


_MISSING_AWAIT = MutationCase(
    name="get_user_count",
    bug_class="missing-await",
    language="TypeScript",
    task_title="Implement getUserCount",
    task_description=(
        "Implement async function getUserCount(db) that returns the "
        "integer count of rows in the users table. The function must "
        "return a number, NOT a Promise — the caller awaits it once."
    ),
    module_scope="repository",
    acceptance_criteria=[
        "Function returns a number (resolves to a number when awaited)",
        "await getUserCount(db) === db.usersCount when db has a usersCount field",
        "Function awaits all async I/O calls inside its body",
        "Return type signature matches Promise<number>, not Promise<Promise<number>>",
    ],
    rfc_section="§6 repository",
    rfc_excerpt=(
        "§6 — repository. Async functions wrap async DB calls; every "
        "internal await is required so the final return is a flat "
        "Promise<T>, not a nested one."
    ),
    file_path="repository/users.ts",
    original_code=(
        "export async function getUserCount(db: { query: (sql: string) => Promise<number> }): Promise<number> {\n"
        "  const count = await db.query('SELECT COUNT(*) FROM users');\n"
        "  return count;\n"
        "}\n"
    ),
    mutated_code=(
        "export async function getUserCount(db: { query: (sql: string) => Promise<number> }): Promise<number> {\n"
        "  const count = db.query('SELECT COUNT(*) FROM users');\n"
        "  return count;\n"
        "}\n"
    ),
    bug_keywords=[
        "missing await", "await", "promise<promise", "not awaited",
        "no await", "nested promise", "unresolved promise",
        "returns a promise",
    ],
)


_WRONG_OPERATOR = MutationCase(
    name="can_book_appointment",
    bug_class="wrong-operator",
    language="Python",
    task_title="Implement can_book_appointment",
    task_description=(
        "Implement can_book_appointment(slot, now) that returns True iff "
        "BOTH conditions hold: slot.is_available is True, AND "
        "slot.starts_at > now. Either condition failing returns False."
    ),
    module_scope="booking",
    acceptance_criteria=[
        "Returns True when slot.is_available=True and slot.starts_at > now",
        "Returns False when slot.is_available=False (even if starts_at > now)",
        "Returns False when slot.starts_at <= now (even if is_available)",
        "Function uses AND, not OR, between the two conditions",
    ],
    rfc_section="§7 booking",
    rfc_excerpt=(
        "§7 — booking. Eligibility for a slot requires BOTH the slot "
        "being marked available AND the start time being strictly in "
        "the future. Either condition alone is insufficient."
    ),
    file_path="booking/eligibility.py",
    original_code=(
        "def can_book_appointment(slot, now) -> bool:\n"
        "    return slot.is_available and slot.starts_at > now\n"
    ),
    mutated_code=(
        "def can_book_appointment(slot, now) -> bool:\n"
        "    return slot.is_available or slot.starts_at > now\n"
    ),
    bug_keywords=[
        "or", "and", "operator", "logic", "wrong operator",
        "should be and", "boolean", "should and",
    ],
)


DEFAULT_CASES: list[MutationCase] = [
    _OFF_BY_ONE,
    _NULL_CHECK_REMOVED,
    _AUTH_BYPASS,
    _SQL_INJECTION,
    _MISSING_AWAIT,
    _WRONG_OPERATOR,
]
"""The shipped suite — one case per bug class. Stable order so the
report row layout is consistent across runs."""
