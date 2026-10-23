"""
Utility functions for OpenAI API interactions.
"""


def get_minimal_reasoning_by_model(model_name: str) -> dict:
    """
    Returns the minimal reasoning effort setting based on the model name.
    This helps reduce latency by setting the lowest supported reasoning effort.
    See https://platform.openai.com/docs/api-reference/chat/create#chat_create-reasoning_effort

    Args:
        model_name: The name of the OpenAI model

    Returns:
        dict: Dictionary with reasoning_effort key if applicable, empty dict otherwise
    """
    # Models that don't support reasoning effort parameter
    if model_name in ["o1-mini", "gpt-5.2-chat-latest"]:
        return {}

    # o-series models (o1, o3, etc.) support "low" as minimal.
    #
    # Match the family, not the first letter: a gateway id carries its provider
    # in front ("openai/gpt-4.1-mini"), and a bare startswith("o") claims every
    # one of those as an o-series model. Today the backend overwrites the key,
    # so nothing breaks — but the next caller of this helper would get
    # reasoning_effort on a model that has none.
    if model_name.startswith(("o1", "o3", "o4")):
        return {"reasoning_effort": "low"}

    # gpt-5.x models (5.1, 5.2, etc.) support "none" as minimal
    if model_name.startswith("gpt-5."):
        return {"reasoning_effort": "none"}

    # gpt-5 base models support "minimal" as lowest effort
    if model_name.startswith("gpt-5"):
        return {"reasoning_effort": "minimal"}

    # Other models don't support reasoning effort
    return {}
