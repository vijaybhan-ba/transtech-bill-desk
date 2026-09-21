from types import SimpleNamespace

import app


def test_model_fallbacks_do_not_include_unavailable_model():
    assert app.MODEL_FALLBACKS == [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
    ]
    assert "gemini-2.5-flash-lite" not in app.MODEL_FALLBACKS


def test_analyze_bills_uses_next_model_after_not_found(monkeypatch):
    requested_models = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            requested_models.append(model)
            if model == app.MODEL_FALLBACKS[0]:
                raise RuntimeError("404 NOT_FOUND: model is unavailable")
            return SimpleNamespace(
                text='[{"Invoice No.": "INV-1"}]',
                model_version=model,
                usage_metadata=None,
            )

    monkeypatch.setattr(app, "API_KEY", "test-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [{"ok": True}])
    monkeypatch.setattr(app.st, "warning", lambda message: None)

    result = app.analyze_bills([SimpleNamespace(name="bill.jpeg")])

    assert result == [{"ok": True}]
    assert requested_models == app.MODEL_FALLBACKS[:2]
