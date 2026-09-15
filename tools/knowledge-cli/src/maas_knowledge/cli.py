"""Machine-readable command line interface for the live knowledge index."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from maas_knowledge.service import KnowledgeInitializer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maas knowledge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def command(name: str, *, input_name: str | None = None) -> argparse.ArgumentParser:
        child = subparsers.add_parser(name)
        child.add_argument("--instance", type=Path, required=True)
        if input_name:
            child.add_argument(input_name, type=Path)
        return child

    command("init")
    command("status")
    command("import-resume", input_name="resume")
    command("replace-index", input_name="input")
    command("upsert-index", input_name="input")
    remove = command("remove-records")
    remove.add_argument("record_ids", nargs="+")
    command("validate")
    return parser


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "knowledge":
        argv = argv[1:]
    arguments = _parser().parse_args(argv)
    service = KnowledgeInitializer(arguments.instance)
    actions: dict[str, Callable[[], Any]] = {
        "init": service.initialize,
        "status": service.status,
        "import-resume": lambda: service.import_resume(arguments.resume),
        "replace-index": lambda: service.replace_index(arguments.input),
        "upsert-index": lambda: service.upsert_index(arguments.input),
        "remove-records": lambda: service.remove_records(tuple(arguments.record_ids)),
        "validate": service.validate,
    }
    try:
        result = actions[arguments.command]()
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": _jsonable(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
