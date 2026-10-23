"""Unit tests for GitHub Pages deployment workflow, decoupled fetching, and shareable URL state."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "deploy-pages.yml"
HTML_PATH = ROOT / "dashboard" / "index.html"
CSS_PATH = ROOT / "dashboard" / "styles.css"
JS_PATH = ROOT / "dashboard" / "app.js"


class TestDeployPagesWorkflow:
    """Validate GitHub Actions deployment workflow configuration (AC 1)."""

    def test_workflow_file_exists(self) -> None:
        assert WORKFLOW_PATH.is_file(), f"Workflow not found at {WORKFLOW_PATH}"

    def test_workflow_triggers(self) -> None:
        content = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "branches:" in content
        assert "- main" in content
        assert "workflow_dispatch:" in content

    def test_workflow_permissions(self) -> None:
        content = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "contents: read" in content
        assert "pages: write" in content
        assert "id-token: write" in content

    def test_workflow_environment_and_actions(self) -> None:
        content = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "environment:" in content
        assert "name: github-pages" in content
        assert "actions/upload-pages-artifact" in content
        assert "path: dashboard" in content
        assert "actions/deploy-pages" in content


class TestDashboardHtmlAndMeta:
    """Validate OpenGraph and social preview tags plus loading overlay markup (AC 2, AC 3)."""

    def test_opengraph_meta_tags_present(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        assert re.search(r'<meta\s+property=["\']og:title["\']', html)
        assert re.search(r'<meta\s+property=["\']og:description["\']', html)
        assert re.search(r'<meta\s+property=["\']og:type["\']\s+content=["\']website["\']', html)
        assert re.search(r'<meta\s+property=["\']og:url["\']', html)
        assert re.search(r'<meta\s+property=["\']og:image["\']', html)

    def test_twitter_meta_tags_present(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        assert re.search(r'<meta\s+name=["\']twitter:card["\']\s+content=["\']summary_large_image["\']', html)
        assert re.search(r'<meta\s+name=["\']twitter:title["\']', html)
        assert re.search(r'<meta\s+name=["\']twitter:description["\']', html)
        assert re.search(r'<meta\s+name=["\']twitter:image["\']', html)

    def test_loading_overlay_markup_present(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        assert 'id="loading-overlay"' in html
        assert 'class="loading-overlay"' in html
        assert 'class="loading-spinner"' in html


class TestDashboardStyles:
    """Validate loading overlay styles and animations (AC 2)."""

    def test_loading_overlay_css(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        assert ".loading-overlay" in css
        assert "position: fixed;" in css
        assert "z-index: 10000;" in css
        assert "transition:" in css
        assert ".loading-overlay.active" in css
        assert ".loading-overlay.fade-out" in css

    def test_loading_spinner_animation(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        assert ".loading-spinner" in css
        assert "@keyframes spinner-rotate" in css


class TestDashboardAppDecoupledFetchingAndUrlSync:
    """Validate app.js decoupled fetching, offline fallback, and URL state synchronization (AC 2, AC 3)."""

    def test_decoupled_data_fetching_logic(self) -> None:
        js = JS_PATH.read_text(encoding="utf-8")
        # Web environment protocol check
        assert "window.location.protocol === 'http:'" in js
        assert "window.location.protocol === 'https:'" in js
        # Fetching ./data.json
        assert "fetch('./data.json')" in js
        # Loading indicator invocation
        assert "showLoading()" in js
        assert "hideLoading()" in js
        # Fallback to embedded script tag
        assert "getEmbeddedData()" in js
        assert "document.getElementById('benchmark-data')" in js

    def test_url_parameters_synchronization(self) -> None:
        js = JS_PATH.read_text(encoding="utf-8")
        # URL search params sync helper
        assert "function updateUrlParams" in js
        assert "searchParams.set('tab'" in js
        assert "searchParams.set('prompt'" in js
        assert "searchParams.set('provider'" in js
        assert "searchParams.set('sort'" in js
        assert "searchParams.set('run'" in js
        assert "searchParams.delete('run')" in js

        # History API invocation
        assert "history.pushState" in js
        assert "history.replaceState" in js

    def test_url_parameters_restoration_on_load(self) -> None:
        js = JS_PATH.read_text(encoding="utf-8")
        # URL state restoration helper
        assert "function restoreStateFromUrl" in js
        # Reading params on initial load
        assert "params.get('prompt') || params.get('series')" in js
        assert "params.get('provider')" in js
        assert "params.get('sort')" in js
        assert "params.get('tab')" in js
        assert "params.get('run')" in js

        # Restoring exact state
        assert "switchTab(tabParam" in js
        assert "openModal(targetRun" in js

    def test_modal_close_removes_run_param(self) -> None:
        js = JS_PATH.read_text(encoding="utf-8")
        # closeModal resets currentModalRunId and syncs URL
        assert "currentModalRunId = null" in js
        assert "updateUrlParams()" in js

    def test_popstate_event_listener(self) -> None:
        js = JS_PATH.read_text(encoding="utf-8")
        assert "window.addEventListener('popstate'" in js
