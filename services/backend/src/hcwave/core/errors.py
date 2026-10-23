"""Platform exception hierarchy."""


class HcwaveError(Exception):
    """Base class for platform errors."""


class ConfigurationError(HcwaveError):
    """A required setting for the selected provider is missing or invalid."""


class ProviderError(HcwaveError):
    """An external provider (messaging, LLM, storage...) call failed."""


class NotFoundError(HcwaveError):
    """A requested entity does not exist in the caller's tenant."""


class ConflictError(HcwaveError):
    """The request conflicts with current state (e.g. slot already full)."""


class PolicyViolationError(HcwaveError):
    """The action is blocked by policy (opt-out, 24-hour window, ...)."""
