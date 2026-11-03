import json
import ast
from pathlib import Path

from server.api import app


def test_openapi_routes_match_pre_refactor_contract():
    fixture = Path(__file__).parent / "fixtures" / "contracts" / "api_routes.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    openapi = app.openapi()
    actual = {
        path: sorted(method.upper() for method in operations if method in {
            "get", "post", "put", "patch", "delete", "options", "head"
        })
        for path, operations in openapi["paths"].items()
    }

    assert actual == expected


def test_openapi_keeps_existing_request_model_contracts():
    paths = app.openapi()["paths"]
    expected_models = {
        ("/api/market/config", "post"): "MarketKeyConfigRequest",
        ("/api/parlays/search", "post"): "ParlaySearchRequest",
        ("/api/profiles/login", "post"): "ProfileLoginByNameRequest",
        ("/api/profiles/register", "post"): "ProfileRegisterRequest",
        ("/api/tickets/place", "post"): "PlaceTicketRequest",
        ("/api/tickets/settle", "post"): "SettleTicketRequest",
        ("/api/wallet/deposit", "post"): "DepositRequest",
    }
    for (path, method), model_name in expected_models.items():
        schema = paths[path][method]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["$ref"] == f"#/components/schemas/{model_name}"


def test_router_modules_do_not_import_the_composition_root():
    router_dir = Path(__file__).parents[1] / "server" / "routers"
    for path in router_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
        assert "server.api" not in imported_modules, path.name
