import ast
from pathlib import Path

FORBIDDEN = {"httpx", "requests", "openai", "urllib", "aiohttp", "socket"}


def test_network_imports_are_confined_to_gateway():
    root = Path(__file__).resolve().parents[1] / "app"
    violations = []
    for path in root.rglob("*.py"):
        if "gateway" in path.relative_to(root).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend((path, alias.name) for alias in node.names if alias.name.split(".")[0] in FORBIDDEN)
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in FORBIDDEN:
                violations.append((path, node.module))
    assert not violations, violations
