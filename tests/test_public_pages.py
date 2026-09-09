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
            for region in ("header", "hero", "cta", "footer", "role_entry")
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
        if "role-entry-panel" in classes:
            regions.add("role_entry")
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


class AdminMarkupParser(HTMLParser):
    void_tags = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.current_nav_section: str | None = None
        self.nav_sections: list[str] = []
        self.nav_routes: dict[str, list[str]] = {}
        self.views: dict[str, dict[str, set[str]]] = {}
        self.stack: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        parent = self.stack[-1] if self.stack else {}
        in_nav = bool(parent.get("in_nav")) or (tag == "nav" and "sidebar-nav" in classes)
        view = parent.get("view")
        if tag == "section" and "app-view" in classes:
            view = attributes.get("data-view")
        frame: dict[str, object] = {
            "tag": tag,
            "in_nav": in_nav,
            "view": view,
            "section_text": [] if in_nav and "nav-section-label" in classes else None,
        }
        if in_nav and attributes.get("data-route") and self.current_nav_section:
            self.nav_routes.setdefault(self.current_nav_section, []).append(
                attributes["data-route"] or ""
            )
        if isinstance(view, str):
            markers = self.views.setdefault(view, {"classes": set(), "ids": set()})
            markers["classes"].update(classes)
            if attributes.get("id"):
                markers["ids"].add(attributes["id"] or "")
        if tag not in self.void_tags:
            self.stack.append(frame)

    def handle_data(self, data: str) -> None:
        if self.stack and isinstance(self.stack[-1].get("section_text"), list):
            self.stack[-1]["section_text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            closed = self.stack[index:]
            del self.stack[index:]
            for frame in closed:
                section_text = frame.get("section_text")
                if isinstance(section_text, list):
                    label = "".join(section_text).strip()
                    self.current_nav_section = label
                    self.nav_sections.append(label)
                    self.nav_routes.setdefault(label, [])
            return


def parse_admin_markup(html: str) -> AdminMarkupParser:
    parser = AdminMarkupParser()
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
        "data-auth-guest": 0,
        "data-auth-member": 2,
        "data-auth-identity": 1,
        "data-auth-workspace": 1,
    }
    assert markup.region_markers["footer"] == {
        "data-auth-guest": 4,
        "data-auth-member": 2,
        "data-auth-identity": 0,
        "data-auth-workspace": 0,
    }
    assert markup.region_markers["role_entry"] == {
        "data-auth-guest": 2,
        "data-auth-member": 3,
        "data-auth-identity": 0,
        "data-auth-workspace": 0,
    }
    role_entry_text = "".join(markup.region_text["role_entry"])
    assert "我是供应商" in role_entry_text
    assert "我是运营商" in role_entry_text


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


def test_landing_page_routes_each_non_admin_role_to_its_actions(client: TestClient) -> None:
    landing = client.get("/").text

    assert 'class="role-entry-card supplier-entry"' in landing
    assert 'href="/apply"' in landing
    assert 'href="/operators"' in landing
    assert 'class="role-entry-card operator-entry"' in landing
    assert 'href="/operator/apply"' in landing
    assert 'href="/suppliers"' in landing
    assert "管理员入口" not in landing


def test_operator_directory_page_is_exposed(client: TestClient) -> None:
    response = client.get("/operators")

    assert response.status_code == 200
    assert 'id="operator-directory"' in response.text
    assert 'id="operator-directory-pagination"' in response.text


def test_supplier_and_admin_workspaces_expose_operator_cooperation_views(client: TestClient) -> None:
    supplier = client.get("/app").text
    assert 'data-view="operator-cooperations"' in supplier
    assert 'id="supplier-operator-pagination"' in supplier
    admin = client.get("/admin").text
    assert 'data-view="operator-applications"' in admin
    assert 'data-view="operator-cooperations"' in admin
    assert 'id="operator-application-pagination"' in admin
    assert 'id="operator-account-pagination"' in admin
    assert 'id="admin-operator-cooperation-pagination"' in admin

    operator = client.get("/operator").text
    assert 'id="operator-cooperation-pagination"' in operator
    assert 'id="operator-binding-pagination"' in operator


def test_admin_management_views_share_structure_and_keep_cooperations_separate(
    client: TestClient,
) -> None:
    response = client.get("/admin")
    assert response.status_code == 200
    markup = parse_admin_markup(response.text)

    assert markup.nav_sections == [
        "供应商管理",
        "运营商管理",
        "合作管理",
        "平台管理",
    ]
    assert markup.nav_routes["合作管理"] == ["operator-cooperations"]
    assert "operator-cooperations" not in markup.nav_routes["运营商管理"]
    assert response.text.count("平台 API 凭证") >= 2

    for view, count_id, search_id, pagination_id in (
        ("applications", "applications-count", "applications-search", "application-pagination"),
        (
            "operator-applications",
            "operator-applications-count",
            "operator-applications-search",
            "operator-application-pagination",
        ),
    ):
        assert {"admin-metric-grid", "toolbar", "data-card", "unified-pagination"} <= (
            markup.views[view]["classes"]
        )
        assert {count_id, search_id, pagination_id} <= markup.views[view]["ids"]

    for view, count_id, search_id, pagination_id in (
        ("suppliers", "suppliers-count", "suppliers-search", "supplier-pagination"),
        ("operators", "operators-count", "operators-search", "operator-account-pagination"),
    ):
        assert {"toolbar", "data-card", "unified-pagination"} <= markup.views[view][
            "classes"
        ]
        assert {count_id, search_id, pagination_id} <= markup.views[view]["ids"]


def test_supplier_workspace_exposes_erp_access_and_operator_credentials_are_removed(
    client: TestClient,
) -> None:
    supplier = client.get("/app").text
    assert 'data-view="erp-integration"' in supplier
    assert 'id="supplier-client-form"' in supplier
    assert 'id="supplier-client-pagination"' in supplier
    assert "ERP 接入" in supplier
    assert "只读 API 凭证" in supplier

    operator = client.get("/operator").text
    for obsolete_marker in (
        'data-view="integration"',
        'id="operator-client-form"',
        'id="operator-token-dialog"',
        "集成凭证",
    ):
        assert obsolete_marker not in operator


def test_user_facing_binding_copy_uses_cooperation_binding_uuid(client: TestClient) -> None:
    for pathname in ("/", "/app", "/operator", "/admin"):
        html = client.get(pathname).text
        assert "ERP 绑定" not in html

    for pathname in ("/app", "/operator", "/admin"):
        assert "合作绑定 UUID" in client.get(pathname).text
