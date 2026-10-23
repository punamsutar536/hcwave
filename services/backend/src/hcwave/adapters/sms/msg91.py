"""MSG91 SMS sender (DLT-registered flows) – the one non-Azure piece if needed."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import httpx

from hcwave.adapters.base import AdapterSettings
from hcwave.adapters.sms.base import SmsSender

_log = logging.getLogger(__name__)


class Msg91Settings(AdapterSettings):
    """Settings for MSG91.

    Attributes:
        auth_key: MSG91 auth key (secret).
        flow_url: Flow API endpoint.
        templates: Purpose -> DLT-approved MSG91 template ID.
    """

    auth_key: str
    flow_url: str = "https://control.msg91.com/api/v5/flow/"
    templates: dict[str, str] = {}


class Msg91SmsSender(SmsSender):
    """Sends SMS through the MSG91 Flow API."""

    settings_model = Msg91Settings
    name = "msg91"

    async def send(self, to: str, text: str, purpose: str, variables: Mapping[str, str]) -> bool:
        """Sends using the DLT template registered for ``purpose``."""
        template_id = self.config.templates.get(purpose)
        if not template_id:
            _log.error("no MSG91 template configured for purpose %s", purpose)
            return False
        payload = {
            "template_id": template_id,
            "recipients": [{"mobiles": to.lstrip("+"), **variables}],
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    self.config.flow_url, json=payload, headers={"authkey": self.config.auth_key}
                )
            return response.status_code < 300
        except httpx.HTTPError:
            _log.exception("MSG91 send failed")
            return False
