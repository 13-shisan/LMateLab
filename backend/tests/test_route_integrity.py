import ast
import unittest
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI

from route_integrity import assert_unique_routes, duplicate_routes


ROUTERS_DIR = Path(__file__).resolve().parents[1] / "routers"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def route_definitions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name):
                continue
            if decorator.func.value.id != "router" or decorator.func.attr not in HTTP_METHODS:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue

            yield decorator.func.attr.upper(), decorator.args[0].value, node.name, node.lineno


class RouteIntegrityTests(unittest.TestCase):
    def test_duplicate_routes_reports_full_method_and_path(self):
        app = FastAPI()
        app.add_api_route("/duplicate", lambda: None, methods=["GET"], name="first")
        app.add_api_route("/duplicate", lambda: None, methods=["GET"], name="second")

        self.assertEqual(
            {("GET", "/duplicate"): ["first", "second"]},
            duplicate_routes(app),
        )

    def test_assert_unique_routes_rejects_duplicate_registration(self):
        app = FastAPI()
        app.add_api_route("/duplicate", lambda: None, methods=["GET"], name="first")
        app.add_api_route("/duplicate", lambda: None, methods=["GET"], name="second")

        with self.assertRaisesRegex(RuntimeError, "GET /duplicate"):
            assert_unique_routes(app)

    def test_router_modules_do_not_register_duplicate_method_paths(self):
        duplicates = []

        for path in sorted(ROUTERS_DIR.glob("*.py")):
            routes = defaultdict(list)
            for method, route_path, function_name, line in route_definitions(path):
                routes[(method, route_path)].append((function_name, line))

            for route, definitions in routes.items():
                if len(definitions) > 1:
                    duplicates.append((path.name, route, definitions))

        self.assertEqual([], duplicates)

    def test_application_routes_are_unique(self):
        from main import app

        self.assertEqual({}, duplicate_routes(app))

    def test_application_exposes_liveness_endpoint(self):
        from main import app

        routes = [
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/health/live"
        ]
        self.assertEqual(1, len(routes))
        self.assertEqual({"status": "ok"}, routes[0].endpoint())


if __name__ == "__main__":
    unittest.main()
