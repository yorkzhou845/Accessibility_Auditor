def estimate_tokens(text):
    """Rough token count estimate: ~4 characters per token.
    Used only for diagnostic printing; not passed to the model."""
    return len(text) // 4
