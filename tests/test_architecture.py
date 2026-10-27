"""Keep the dependency and persistence boundaries introduced by the refactor."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "qqbot"


def modules():
    return {path.stem: ast.parse(path.read_text()) for path in PACKAGE.glob("*.py")}


def test_local_module_dependencies_have_no_cycles():
    trees = modules()
    graph = {name: set() for name in trees}
    for name, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                targets = (
                    [node.module.split(".")[0]]
                    if node.module
                    else [item.name for item in node.names]
                )
                graph[name].update(target for target in targets if target in trees)

    checked = set()

    def visit(name, path):
        assert name not in path, "Dependency cycle: " + " -> ".join([*path, name])
        if name in checked:
            return
        for dependency in sorted(graph[name]):
            visit(dependency, [*path, name])
        checked.add(name)

    for name in sorted(graph):
        visit(name, [])


def test_business_modules_do_not_access_store_connections():
    violations = []
    for name, tree in modules().items():
        if name == "store" or name.endswith("_store"):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "db"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr.endswith("store")
            ):
                violations.append(f"{name}.py:{node.lineno}")
    assert not violations, "Use a store operation instead of its connection: " + ", ".join(
        violations
    )


def test_components_do_not_keep_a_bridge_service_locator():
    violations = []
    for name, tree in modules().items():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr == "bridge"
            ):
                violations.append(f"{name}.py:{node.lineno}")
    assert not violations, "Inject explicit dependencies: " + ", ".join(violations)
