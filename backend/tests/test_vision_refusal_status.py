"""A vision failure is two different things: the model refusing the picture
(final: 422, so a caller says what is wrong with the picture) and the model
being away (transient: 502, so the iMessage worker parks the turn and answers
when it is back). Caroline's photo on 2026-09-02 was the first kind and was
reported as the second."""
import httpx

from backend.api.v1.vision import _upstream_refused
from backend.services.vision_analysis_service import VisionAnalysisError


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://vlm.local/v1/chat/completions")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def _wrapped(cause: BaseException) -> VisionAnalysisError:
    try:
        try:
            raise cause
        except Exception as inner:
            raise RuntimeError("inspect failed") from inner
    except RuntimeError as middle:
        try:
            raise VisionAnalysisError("artifact-1") from middle
        except VisionAnalysisError as outer:
            return outer


def test_a_4xx_from_the_model_is_a_refusal_and_a_5xx_or_no_answer_is_not():
    assert _upstream_refused(_wrapped(_status_error(400))) is True
    assert _upstream_refused(_wrapped(_status_error(413))) is True
    assert _upstream_refused(_wrapped(_status_error(503))) is False
    assert _upstream_refused(_wrapped(httpx.ConnectError("down"))) is False
    assert _upstream_refused(VisionAnalysisError("artifact-2")) is False
