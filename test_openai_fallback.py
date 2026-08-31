import io
from types import SimpleNamespace

import app


def test_valid_gemini_result_never_calls_openai(monkeypatch):
    class SuccessfulModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text='[{"Invoice No.": "INV-GEMINI"}]',
                model_version="gemini-test",
                usage_metadata=None,
            )

    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=SuccessfulModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [{"provider": "gemini"}])
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: (_ for _ in ()).throw(AssertionError("OpenAI must not run")),
    )

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "gemini"}
    ]


def test_openai_runs_only_after_all_gemini_models_fail(monkeypatch):
    requested_models = []

    class BusyModels:
        def generate_content(self, **kwargs):
            requested_models.append(kwargs["model"])
            raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(app, "MAX_RETRIES", 1)
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=BusyModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: [{"provider": "openai"}],
    )

    result = app.analyze_bills([SimpleNamespace(name="bill.jpeg")])

    assert result == [{"provider": "openai"}]
    assert requested_models == app.MODEL_FALLBACKS


def test_zero_record_gemini_responses_eventually_use_openai(monkeypatch):
    class EmptyModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="[]",
                model_version=kwargs["model"],
                usage_metadata=None,
            )

    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=EmptyModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: [{"provider": "openai"}],
    )

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "openai"}
    ]


def test_openai_schema_has_required_object_root():
    assert app.OPENAI_RESPONSE_SCHEMA["type"] == "object"
    assert "records" in app.OPENAI_RESPONSE_SCHEMA["properties"]


def test_one_minute_gemini_deadline_switches_to_openai(monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(app.time, "monotonic", iter([0.0, 61.0, 61.0]).__next__)
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **call_kwargs: (_ for _ in ()).throw(
                    AssertionError("Gemini must not start after the deadline")
                )
            )
        ),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: [{"provider": "openai"}],
    )

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "openai"}
    ]


def test_openai_analyzes_each_uploaded_file_independently(monkeypatch):
    request_count = 0

    class FakeResponses:
        def create(self, **kwargs):
            nonlocal request_count
            request_count += 1
            return SimpleNamespace(
                output_text='{"records":[{"Invoice No.":"INV","items":[]}]}'
            )

    files = []
    for index in range(3):
        uploaded_file = io.BytesIO(b"image")
        uploaded_file.name = f"bill-{index}.jpeg"
        files.append(uploaded_file)

    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(
        app,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(responses=FakeResponses()),
    )
    monkeypatch.setattr(app, "repair_openai_customer_identifiers", lambda records: records)

    records = app.analyze_bills_with_openai(files)

    assert request_count == 3
    assert len(records) == 3


def test_openai_customer_ocr_slip_is_repaired_from_unique_master_code(monkeypatch):
    customer_lookup = {
        "MUMC020630": {
            "Customer Name": "SHIZA ENTERPRISES",
            "To": "AMBERNATH W",
        },
        "MUMC002775": {
            "Customer Name": "STAR AGENCY-TITWALA",
            "To": "TITWALA",
        },
    }
    monkeypatch.setattr(app, "load_customer_master", lambda: object())
    monkeypatch.setattr(app, "build_customer_lookup", lambda data: customer_lookup)

    repaired = app.repair_openai_customer_identifiers(
        [
            {
                "Customer Code": "MUMC020830",
                "Customer Name": "SHIFA ENTERPRISES",
            }
        ]
    )

    assert repaired[0]["Customer Code"] == "MUMC020630"


def test_openai_customer_name_disambiguates_similar_master_codes(monkeypatch):
    customer_lookup = {
        "MUMC002775": {
            "Customer Name": "STAR AGENCY-TITWALA",
            "To": "TITWALA",
        },
        "MUMC002776": {
            "Customer Name": "ANOTHER CUSTOMER",
            "To": "OTHER",
        },
    }
    monkeypatch.setattr(app, "load_customer_master", lambda: object())
    monkeypatch.setattr(app, "build_customer_lookup", lambda data: customer_lookup)

    repaired = app.repair_openai_customer_identifiers(
        [
            {
                "Customer Code": "MUMC002779",
                "Customer Name": "STAR AGENCY TITWALA",
            }
        ]
    )

    assert repaired[0]["Customer Code"] == "MUMC002775"
