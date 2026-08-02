class DiscoveryError(RuntimeError):
    """Raised when a discovery sweep cannot proceed or its record is unusable."""


class DiscoveryProfileLimitError(ValueError):
    """Raised when a profile would exceed its bounded interest or place count."""


class DiscoveryProjectionConflictError(ValueError):
    """Raised when a fact value no longer matches its stable discovery identity."""
