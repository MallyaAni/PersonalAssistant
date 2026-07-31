import pytest

from backend.vision.lm_studio import (
    OpenAICompatibleVisionProvider,
    create_vision_provider,
)


# Verify the configured adapter constructs the neutral vision implementation.
def test_vision_factory_selects_openai_compatible_adapter():
    provider = create_vision_provider(
        adapter="openai_compatible",
        base_url="http://provider.local",
        model="vision-model",
        api_key=None,
        timeout_seconds=30,
        reasoning_effort="none",
    )

    assert isinstance(provider, OpenAICompatibleVisionProvider)
    assert provider.base_url == "http://provider.local"
    assert provider.model == "vision-model"


# Verify unknown vision adapters fail closed during dependency construction.
def test_vision_factory_rejects_unknown_adapter():
    with pytest.raises(
        ValueError,
        match="Unsupported vision inference adapter: unknown",
    ):
        create_vision_provider(
            adapter="unknown",
            base_url="http://provider.local",
            model="vision-model",
            api_key=None,
            timeout_seconds=30,
            reasoning_effort="none",
        )
