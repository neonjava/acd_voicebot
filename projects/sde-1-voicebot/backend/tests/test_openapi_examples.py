"""Tests verifying OpenAPI schema request and response examples for every endpoint."""

from typing import Any

from app.main import app


def _has_example(
    media_type: str, media_def: dict[str, Any], schema: dict[str, Any]
) -> bool:
    """Check if media definition, schema, or component schema contains examples."""
    if media_type == "audio/wav":
        return True
    if "example" in media_def or "examples" in media_def:
        return True
    s = media_def.get("schema", {})
    if "example" in s or "examples" in s:
        return True

    refs = []
    if "$ref" in s:
        refs.append(s["$ref"])
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in s.get(key, []):
            if "$ref" in sub:
                refs.append(sub["$ref"])
            elif "example" in sub or "examples" in sub:
                return True

    for ref in refs:
        if ref.startswith("#/components/schemas/"):
            name = ref.split("/")[-1]
            comp = schema.get("components", {}).get("schemas", {}).get(name, {})
            if "example" in comp or "examples" in comp:
                return True
    return False


def test_openapi_spec_has_request_and_response_examples_for_every_endpoint():
    """Verify that every endpoint in OpenAPI includes request and response examples."""
    schema = app.openapi()
    paths = schema.get("paths", {})
    assert len(paths) >= 15, f"Expected at least 15 endpoints, found {len(paths)}"

    missing_response_examples: list[str] = []
    missing_request_examples: list[str] = []

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue

            endpoint_desc = f"{method.upper()} {path}"

            # Check response example
            responses = operation.get("responses", {})
            has_response_example = False
            for status_code, resp_def in responses.items():
                if status_code in ("200", "201"):
                    content = resp_def.get("content", {})
                    for media_type, media_def in content.items():
                        if _has_example(media_type, media_def, schema):
                            has_response_example = True
                            break

            if not has_response_example:
                missing_response_examples.append(endpoint_desc)

            # Check request body example if requestBody is defined
            request_body = operation.get("requestBody")
            if request_body:
                content = request_body.get("content", {})
                has_request_example = False
                for media_type, media_def in content.items():
                    if _has_example(media_type, media_def, schema):
                        has_request_example = True
                        break

                if not has_request_example:
                    missing_request_examples.append(endpoint_desc)

    assert not missing_response_examples, (
        "The following endpoints are missing response examples in OpenAPI:\n"
        + "\n".join(missing_response_examples)
    )
    assert not missing_request_examples, (
        "The following endpoints are missing request body examples in OpenAPI:\n"
        + "\n".join(missing_request_examples)
    )


def test_speech_route_declares_audio_wav_response():
    """Verify speech route declares audio/wav response in OpenAPI."""
    schema = app.openapi()
    speech_path = schema.get("paths", {}).get(
        "/api/sessions/{session_id}/turns/{turn_id}/speech", {}
    )
    speech_op = speech_path.get("get", {})
    speech_content = speech_op.get("responses", {}).get("200", {}).get("content", {})
    assert "audio/wav" in speech_content, "Expected audio/wav in speech response"
