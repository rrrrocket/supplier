from html.parser import HTMLParser
import re
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AuthMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.auth_markers: dict[str, int] = {
            "data-auth-guest": 0,
            "data-auth-member": 0,
            "data-auth-identity": 0,
            "data-auth-workspace": 0,
        }
        self.auth_redirect: str | None = None
        self.region_markers: dict[str, dict[str, int]] = {
            region: {marker: 0 for marker in self.auth_markers}
            for region in ("header", "hero", "cta", "footer", "marketing")
        }
        self.region_text: dict[str, list[str]] = {region: [] for region in self.region_markers}
        self.stack: list[tuple[str, set[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        regions = set(self.stack[-1][1]) if self.stack else set()
        classes = set((attributes.get("class") or "").split())
        if tag == "header" and "site-header" in classes:
            regions.add("header")
        if "hero-actions" in classes:
            regions.add("hero")
        if "cta-actions" in classes:
            regions.add("cta")
        if tag == "footer" and "site-footer" in classes:
            regions.add("footer")
        if "network-card" in classes:
            regions.add("marketing")
        for marker in self.auth_markers:
            if marker in attributes:
                self.auth_markers[marker] += 1
                for region in regions:
                    self.region_markers[region][marker] += 1
        if tag == "body":
            self.auth_redirect = attributes.get("data-auth-redirect")
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, regions))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self.stack:
            return
        for region in self.stack[-1][1]:
            self.region_text[region].append(data)


def parse_auth_markup(html: str) -> AuthMarkupParser:
    parser = AuthMarkupParser()
    parser.feed(html)
    return parser


def test_landing_page_exposes_guest_and_authenticated_actions(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200

    markup = parse_auth_markup(response.text)
    assert markup.region_markers["header"] == {
        "data-auth-guest": 2,
        "data-auth-member": 2,
        "data-auth-identity": 1,
        "data-auth-workspace": 1,
    }
    assert markup.region_markers["hero"] == {
        "data-auth-guest": 1,
        "data-auth-member": 1,
        "data-auth-identity": 0,
        "data-auth-workspace": 1,
    }
    assert markup.region_markers["cta"] == {
        "data-auth-guest": 2,
        "data-auth-member": 2,
        "data-auth-identity": 1,
        "data-auth-workspace": 1,
    }
    assert markup.region_markers["footer"] == {
        "data-auth-guest": 2,
        "data-auth-member": 1,
        "data-auth-identity": 0,
        "data-auth-workspace": 1,
    }
    assert all(value == 0 for value in markup.region_markers["marketing"].values())
    assert "中国供应商" in "".join(markup.region_text["marketing"])


def test_guest_only_pages_redirect_authenticated_visitors(client: TestClient) -> None:
    for pathname in ("/login", "/apply"):
        response = client.get(pathname)
        assert response.status_code == 200
        assert parse_auth_markup(response.text).auth_redirect == "workspace"


def test_hidden_auth_actions_cannot_be_overridden_by_button_layout() -> None:
    stylesheet = (PROJECT_ROOT / "app/web/assets/styles.css").read_text()
    assert re.search(
        r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important",
        stylesheet,
    )


def test_supplier_workspace_uses_only_unified_pagination_controls(client: TestClient) -> None:
    response = client.get("/app")
    assert response.status_code == 200

    html = response.text
    assert 'id="products-pagination"' in html
    assert 'id="offers-pagination"' in html
    assert 'id="import-pagination"' in html
    for obsolete_id in (
        "products-prev-page",
        "products-next-page",
        "offers-prev-page",
        "offers-next-page",
        "import-prev-page",
        "import-next-page",
    ):
        assert f'id="{obsolete_id}"' not in html


def test_operator_marketplace_pages_and_workspaces_are_exposed(client: TestClient) -> None:
    for pathname, marker in (
        ("/operator/apply", 'id="operator-application-form"'),
        ("/suppliers", 'id="supplier-directory"'),
        ("/operator", 'data-operator-workspace'),
    ):
        response = client.get(pathname)
        assert response.status_code == 200
        assert marker in response.text

    application = client.get("/operator/apply").text
    assert application.count(" required") == 3
    landing = client.get("/").text
    assert 'href="/suppliers"' in landing
    assert 'href="/operator/apply"' in landing


def test_supplier_and_admin_workspaces_expose_operator_cooperation_views(client: TestClient) -> None:
    assert 'data-view="operator-cooperations"' in client.get("/app").text
    admin = client.get("/admin").text
    assert 'data-view="operator-applications"' in admin
    assert 'data-view="operator-cooperations"' in admin
