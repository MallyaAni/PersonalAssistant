class DiscoveryError(RuntimeError):
    """Raised when a discovery sweep cannot proceed or its record is unusable."""


class DiscoveryProfileLimitError(ValueError):
    """Raised when a profile would exceed its bounded interest or place count."""
