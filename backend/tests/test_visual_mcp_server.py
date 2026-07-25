import json
from types import SimpleNamespace

import pytest
from mcp import types

from backend.capabilities.visual_mcp import (
    VisualCapabilityRuntime,
    VisualRequestContext,
    _artifact_summary,
    _encode_result,
    _presentation_summary,
    _request_context,
    create_visual_mcp,
)


# Build a minimal FastMCP context containing application-owned request metadata.
def _context(**overrides):
    values = {
        "anios_user_id": "ani.mallya",
        "anios_conversation_id": "11111111-1111-4111-8111-111111111111",
        "anios_trace_id": "22222222-2222-4222-8222-222222222222",
        **overrides,
    }
    meta = types.RequestParams.Meta.model_validate(values)
    return SimpleNamespace(request_context=SimpleNamespace(meta=meta))


# Verify identity is taken from hidden request metadata rather than tool arguments.
def test_visual_request_context_is_application_owned():
    context = _request_context(_context())  # type: ignore[arg-type]

    assert context == VisualRequestContext(
        user_id="ani.mallya",
        conversation_id="11111111-1111-4111-8111-111111111111",
        trace_id="22222222-2222-4222-8222-222222222222",
    )


# Verify missing or malformed ownership metadata fails before service work.
@pytest.mark.parametrize(
    "overrides",
    [
        {"anios_user_id": ""},
        {"anios_conversation_id": "not-a-uuid"},
        {"anios_trace_id": "not-a-uuid"},
    ],
)
def test_visual_request_context_rejects_invalid_identity(overrides):
    with pytest.raises(ValueError, match="context"):
        _request_context(_context(**overrides))  # type: ignore[arg-type]


# Verify the model-visible schemas never contain user, conversation, or trace IDs.
@pytest.mark.asyncio
async def test_visual_mcp_declares_bounded_agent_facing_tools():
    server = create_visual_mcp(VisualCapabilityRuntime())

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "generate_diagram",
        "generate_image",
        "ask_about_image",
        "get_artifact",
        "create_presentation",
        "revise_presentation_slide",
        "get_presentation",
    }
    for tool in tools.values():
        properties = tool.inputSchema.get("properties", {})
        assert "user_id" not in properties
        assert "conversation_id" not in properties
        assert "trace_id" not in properties


# Verify artifact results omit private storage references and binary content.
def test_artifact_summary_contains_only_public_bounded_metadata():
    summary = _artifact_summary(
        {
            "id": "artifact",
            "kind": "generated_image",
            "status": "ready",
            "width": 2048,
            "_storage_key": "private/path.png",
            "content": b"secret bytes",
        }
    )

    assert summary == {
        "id": "artifact",
        "kind": "generated_image",
        "status": "ready",
        "width": 2048,
    }


# Verify presentation tools return slide handles without full private deck content.
def test_presentation_summary_is_bounded_to_current_slide_identities():
    summary = _presentation_summary(
        {
            "id": "deck",
            "conversation_id": "conversation",
            "title": "Deck title",
            "current_revision_id": "revision",
            "current_revision": {
                "revision_number": 2,
                "status": "ready",
                "content_available": True,
                "specification": {
                    "slides": [
                        {
                            "slide_id": "slide-a",
                            "title": "Opening",
                            "notes": "private notes",
                            "elements": [{"text": "private slide body"}],
                        }
                    ]
                },
            },
        }
    )

    assert summary["slides"] == [{"slide_id": "slide-a", "title": "Opening"}]
    assert "specification" not in summary


# Verify long vision answers remain valid bounded JSON under the MCP result cap.
def test_visual_result_encoding_remains_valid_json_when_analysis_is_long():
    encoded = _encode_result({"analysis": "x" * 10_000, "model": "gemma"})

    assert len(encoded) <= 3_500
    assert json.loads(encoded)["truncated"] is True
