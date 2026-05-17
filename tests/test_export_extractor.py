# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""extract_exports() coverage for the two languages M4 supports today:
TypeScript (incl. TSX/JS) and Python.

Six guarantees:
  - TS named function captured with kind=function + signature
  - TS default export captured (with name when present)
  - TS interface + type captured
  - TS re-export `export { foo, bar as baz } from './x'` captured
  - Python def + class captured with full signature (args + return type)
  - Unsupported extensions return [] without raising
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ortim.codebase.exports import extract_exports  # noqa: E402


def test_ts_named_function_captured() -> None:
    src = (
        "import { z } from 'zod';\n"
        "\n"
        "export function createTaskService(db: DbAdapter) {\n"
        "  return {\n"
        "    create: (title: string) => ({ ... }),\n"
        "  };\n"
        "}\n"
    )
    exports = extract_exports(Path("svc.ts"), src)
    names = {(e.kind, e.name) for e in exports}
    assert ("function", "createTaskService") in names
    sig = next(e for e in exports if e.name == "createTaskService").signature
    assert "createTaskService" in sig
    assert "DbAdapter" in sig


def test_ts_default_named_export_captured() -> None:
    src = (
        "function TaskForm(props: TaskFormProps) { return null; }\n"
        "export default TaskForm;\n"
    )
    exports = extract_exports(Path("TaskForm.tsx"), src)
    assert any(e.kind == "default" and e.name == "TaskForm" for e in exports)


def test_ts_interface_and_type_captured() -> None:
    src = (
        "export interface Task {\n"
        "  id: string;\n"
        "  title: string;\n"
        "}\n"
        "export type TaskId = string;\n"
    )
    exports = extract_exports(Path("types.ts"), src)
    names = {(e.kind, e.name) for e in exports}
    assert ("interface", "Task") in names
    assert ("type", "TaskId") in names


def test_ts_re_export_named_specifiers() -> None:
    src = (
        "export { Task, TaskRepo as Repo } from './internal';\n"
        "export { default as Logger } from './logger';\n"
    )
    exports = extract_exports(Path("index.ts"), src)
    names = {e.name for e in exports}
    assert "Task" in names
    assert "Repo" in names
    # `default as Logger` → exported name is Logger
    assert "Logger" in names


def test_python_def_class_captured_with_signature() -> None:
    src = (
        "from typing import Optional\n"
        "\n"
        "class TaskService:\n"
        "    def __init__(self, db: 'DbAdapter') -> None:\n"
        "        ...\n"
        "\n"
        "def create_task(title: str, completed: bool = False) -> dict:\n"
        "    return {}\n"
        "\n"
        "def _helper() -> None:  # private, must not be surfaced\n"
        "    ...\n"
    )
    exports = extract_exports(Path("svc.py"), src)
    by_name = {e.name: e for e in exports}
    assert "TaskService" in by_name
    assert by_name["TaskService"].kind == "class"
    assert "create_task" in by_name
    assert "title: str" in by_name["create_task"].signature
    assert "-> dict" in by_name["create_task"].signature
    assert "_helper" not in by_name  # underscored = private = not exported


def test_unsupported_extension_returns_empty_list() -> None:
    assert extract_exports(Path("schema.sql"), "CREATE TABLE x ...") == []
    assert extract_exports(Path("README.md"), "# title") == []


def test_ts_class_extracted_with_inheritance() -> None:
    src = (
        "export abstract class Base<T> {\n"
        "  abstract get(): T;\n"
        "}\n"
        "export class Repo extends Base<Task> {\n"
        "  get(): Task { return null!; }\n"
        "}\n"
    )
    exports = extract_exports(Path("repo.ts"), src)
    names = {e.name for e in exports}
    assert "Base" in names
    assert "Repo" in names
    repo_sig = next(e for e in exports if e.name == "Repo").signature
    assert "extends Base" in repo_sig


def test_python_top_level_annotated_constant_captured() -> None:
    src = "MAX_TASKS: int = 1000\n"
    exports = extract_exports(Path("config.py"), src)
    assert any(e.kind == "const" and e.name == "MAX_TASKS" for e in exports)


def test_ts_destructured_params_preserved_in_signature() -> None:
    """React component pattern: `export function Foo({ bar }: FooProps) { ... }`
    The destructure's `{...}` must NOT be mistaken for the function body
    opener — otherwise Worker T-N sees `export function Foo(` and has to
    guess the prop name. That guess is exactly what M4 was built to
    eliminate. Regression guard for the bug discovered in the first
    M4 E2E re-run (web-todo-m2 T-004 → invented `onCreate`)."""
    src = (
        "export function TaskForm({ onSubmit }: TaskFormProps) {\n"
        "  return null;\n"
        "}\n"
    )
    exports = extract_exports(Path("TaskForm.tsx"), src)
    sig = next(e for e in exports if e.name == "TaskForm").signature
    assert "onSubmit" in sig
    assert "TaskFormProps" in sig


def test_ts_generic_function_signature_preserved() -> None:
    """`export function foo<T extends X>(value: T): T` — angle brackets
    around the type param shouldn't terminate the capture."""
    src = (
        "export function identity<T extends object>(value: T): T {\n"
        "  return value;\n"
        "}\n"
    )
    exports = extract_exports(Path("identity.ts"), src)
    sig = next(e for e in exports if e.name == "identity").signature
    assert "<T extends object>" in sig
    assert ": T" in sig
