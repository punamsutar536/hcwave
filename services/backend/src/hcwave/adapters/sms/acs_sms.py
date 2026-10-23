"""Azure Communication Services SMS sender.

Check that ACS can deliver to Indian numbers under the DLT rules for your
sender before relying on it; otherwise switch ``sms.provider`` to ``msg91``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.sms.base import SmsSender

_log = logging.getLogger(__name__)


class AcsSmsSettings(AdapterSettings):
    """Settings for ACS SMS."""

    endpoint: str
    from_number: str
    access_key: str = ""


class AcsSmsSender(SmsSender):
    """Sends SMS through ACS."""

    settings_model = AcsSmsSettings
    name = "acs_sms"

    async def send(self, to: str, text: str, purpose: str, variables: Mapping[str, str]) -> bool:
        """Sends one SMS with delivery reports enabled."""
        from azure.communication.sms.aio import SmsClient

        if self.config.access_key:
            from azure.core.credentials import AzureKeyCredential

            credential = AzureKeyCredential(self.config.access_key)
        else:
            credential = self.ctx.credentials.aio
        try:
            async with SmsClient(self.config.endpoint, credential) as client:
                results = await client.send(
                    from_=self.config.from_number,
                    to=[to],
                    message=text,
                    enable_delivery_report=True,
                    tag=purpose,
                )
            return bool(results and results[0].successful)
        except Exception:
            _log.exception("ACS SMS send failed")
            return False
