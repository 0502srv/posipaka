"""Architecture boundary tests — prevent coupling creep between modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent / "posipaka"


def _collect_imports(directory: Path, skip_type_checking: bool = True) -> dict[str, set[str]]:
    """Collect runtime imports from .py files (skip TYPE_CHECKING blocks by default)."""
    imports: dict[str, set[str]] = {}
    for py_file in directory.rglob("*.py"):
        relative = str(py_file.relative_to(PROJECT_ROOT))
        file_imports: set[str] = set()
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        # Find TYPE_CHECKING if-blocks to skip
        type_check_ranges: set[int] = set()
        if skip_type_checking:
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    test = node.test
                    is_tc = False
                    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                        is_tc = True
                    elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                        is_tc = True
                    if is_tc:
                        for child in ast.walk(node):
                            if hasattr(child, "lineno"):
                                type_check_ranges.add(child.lineno)

        for node in ast.walk(tree):
            if hasattr(node, "lineno") and node.lineno in type_check_ranges:
                continue
            if isinstance(node, ast.ImportFrom) and node.module:
                file_imports.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    file_imports.add(alias.name)
        imports[relative] = file_imports
    return imports


class TestImportBoundaries:
    """Validate that modules respect architectural boundaries."""

    def test_channels_do_not_import_agent_at_runtime(self):
        """channels/ should not runtime-import core.agent (TYPE_CHECKING OK)."""
        channels_dir = PROJECT_ROOT / "channels"
        if not channels_dir.exists():
            pytest.skip("channels/ not found")
        imports = _collect_imports(channels_dir, skip_type_checking=True)
        for file_path, file_imports in imports.items():
            for imp in file_imports:
                assert imp != "posipaka.core.agent", (
                    f"{file_path} runtime-imports posipaka.core.agent. "
                    f"Use posipaka.core.agent_types or TYPE_CHECKING guard."
                )

    def test_integrations_do_not_import_channels(self):
        """integrations/ should not import from channels/."""
        integrations_dir = PROJECT_ROOT / "integrations"
        if not integrations_dir.exists():
            pytest.skip("integrations/ not found")
        imports = _collect_imports(integrations_dir)
        for file_path, file_imports in imports.items():
            for imp in file_imports:
                assert not imp.startswith("posipaka.channels"), (
                    f"{file_path} imports {imp}. "
                    f"integrations/ should not depend on channels/."
                )

    def test_security_does_not_import_agent(self):
        """security/ should not import from core/agent (avoid circular deps)."""
        security_dir = PROJECT_ROOT / "security"
        if not security_dir.exists():
            pytest.skip("security/ not found")
        imports = _collect_imports(security_dir)
        for file_path, file_imports in imports.items():
            for imp in file_imports:
                assert imp != "posipaka.core.agent", (
                    f"{file_path} imports posipaka.core.agent. "
                    f"security/ must not depend on core/agent."
                )

    def test_no_circular_core_to_channels(self):
        """core/ should not import from channels/ (gateway.py allowed as router)."""
        core_dir = PROJECT_ROOT / "core"
        if not core_dir.exists():
            pytest.skip("core/ not found")
        imports = _collect_imports(core_dir)
        # gateway.py is the entry point that routes to channels — allowed
        allowed = {"core/gateway.py"}
        for file_path, file_imports in imports.items():
            if file_path in allowed:
                continue
            for imp in file_imports:
                assert not imp.startswith("posipaka.channels"), (
                    f"core/{file_path} imports {imp}. "
                    f"core/ should not depend on channels/."
                )
