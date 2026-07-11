"""Tests for the lazy app proxy used under pytest (M5.7)."""

from fastapi import FastAPI

from audio_to_subs.api.app import _LazyApp, app


def test_app_is_lazy_proxy_under_pytest():
    """Under pytest the module-level ``app`` is the lazy proxy, not a real app."""
    assert isinstance(app, _LazyApp)
    # The proxy is ASGI-callable (uvicorn invokes app(scope, receive, send)).
    assert callable(app)


def test_lazy_app_resolves_to_fastapi():
    """First attribute access builds a real FastAPI app."""
    assert isinstance(app._resolve(), FastAPI)


def test_lazy_app_forwards_attributes():
    """Attribute access is delegated to the resolved FastAPI instance."""
    assert app.routes is app._resolve().routes
