"""Outbound SMS contract, used as the OTP fallback when WhatsApp fails.

In India, transactional SMS must use DLT-registered sender IDs and templates,
so providers receive both the rendered text and the template variables.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping

from hcwave.adapters.base import Adapter


class SmsSender(Adapter, abc.ABC):
    """Abstract SMS sender."""

    @abc.abstractmethod
    async def send(self, to: str, text: str, purpose: str, variables: Mapping[str, str]) -> bool:
        """Sends one SMS.

        Args:
            to: Recipient in E.164.
            text: Fully rendered message (must match the DLT template).
            purpose: Logical purpose, e.g. ``otp`` (selects a DLT template).
            variables: Template variables, e.g. ``{"otp": "123456"}``.

        Returns:
            True when the provider accepted the message.
        """
