"""Tests verifying OpenAPI schema request and response examples for every endpoint."""

from app.main import app


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
                        if "example" in media_def or "examples" in media_def:
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
                    if "example" in media_def or "examples" in media_def:
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
