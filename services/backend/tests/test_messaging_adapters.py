import hashlib
import hmac
import json

import pytest

from hcwave.adapters.base import AdapterContext
from hcwave.adapters.messaging.acs_whatsapp import AcsWhatsAppProvider
from hcwave.adapters.messaging.base import (
    Choice,
    InboundEventType,
    OutboundKind,
    OutboundMessage,
    TemplateButtonBinding,
    TemplateParameter,
    WebhookVerificationError,
    render_text_menu,
)
from hcwave.adapters.messaging.meta_cloud import MetaCloudProvider


@pytest.fixture
def ctx(container):
    return AdapterContext(settings=container.settings, credentials=container.credentials)


@pytest.fixture
def acs(ctx):
    return AcsWhatsAppProvider({"endpoint": "https://acs.example", "access_key": "x"}, ctx)


def test_acs_text_and_template(acs):
    text = acs.build_request("chan", "+91900", OutboundMessage(kind=OutboundKind.TEXT, text="hi"))
    assert text == {
        "channelRegistrationId": "chan",
        "to": ["+91900"],
        "kind": "text",
        "content": "hi",
    }

    template = acs.build_request(
        "chan",
        "+91900",
        OutboundMessage(
            kind=OutboundKind.TEMPLATE,
            template_name="hcw_report_ready",
            template_language="en",
            template_params=(TemplateParameter("patient_name", "Asha"),),
            template_buttons=(
                TemplateButtonBinding("url", "h/tok"),
                TemplateButtonBinding("quick_reply", "x:1"),
            ),
        ),
    )
    body = template["template"]
    assert body["values"][0] == {"kind": "text", "name": "patient_name", "text": "Asha"}
    assert body["values"][1] == {"kind": "quickAction", "name": "button0", "text": "h/tok"}
    assert body["values"][2] == {"kind": "quickAction", "name": "button1", "payload": "x:1"}
    assert body["bindings"]["buttons"] == [
        {"subType": "url", "refValue": "button0"},
        {"subType": "quickReply", "refValue": "button1"},
    ]


def test_acs_interactive_buttons_and_list(acs):
    buttons = acs.build_request(
        "c",
        "+1",
        OutboundMessage(
            kind=OutboundKind.BUTTONS, text="Pick", choices=(Choice("a", "A"), Choice("b", "B"))
        ),
    )
    assert buttons["kind"] == "interactive"
    action = buttons["interactiveMessage"]["action"]
    assert action["kind"] == "whatsAppButtonAction" and action["content"]["buttons"][1] == {
        "id": "b",
        "title": "B",
    }

    listing = acs.build_request(
        "c",
        "+1",
        OutboundMessage(
            kind=OutboundKind.LIST,
            text="Pick",
            choices=(Choice("a", "A", "desc"),),
            list_button="Open",
        ),
    )
    content = listing["interactiveMessage"]["action"]["content"]
    assert content["kind"] == "group" and content["groups"][0]["items"][0]["description"] == "desc"


def test_acs_text_menu_fallback(ctx):
    provider = AcsWhatsAppProvider({"endpoint": "https://acs", "supports_interactive": False}, ctx)
    body = provider.build_request(
        "c",
        "+1",
        OutboundMessage(kind=OutboundKind.LIST, text="Pick", choices=(Choice("a", "Alpha"),)),
    )
    assert body["kind"] == "text" and "1. Alpha" in body["content"]


def test_acs_parse_events(acs):
    received = {
        "id": "evt-1",
        "eventType": "Microsoft.Communication.AdvancedMessageReceived",
        "data": {
            "content": "",
            "from": "919812345678",
            "to": "chan",
            "receivedTimestamp": "2026-10-13T10:00:00Z",
            "interactiveContent": {
                "type": "listReply",
                "listReply": {"id": "dept:1", "title": "Cardiology"},
            },
        },
    }
    status = {
        "eventType": "Microsoft.Communication.AdvancedMessageDeliveryStatusUpdated",
        "data": {"messageId": "m1", "status": "Delivered", "from": "chan", "to": "+919812345678"},
    }
    button = {
        "id": "evt-2",
        "type": "Microsoft.Communication.AdvancedMessageReceived",  # CloudEvents schema
        "data": {
            "from": "+919812345678",
            "to": "chan",
            "button": {"text": "Confirm", "payload": "remind_confirm:9"},
        },
    }
    events = acs.parse_events([received, status, button])
    assert events[0].type is InboundEventType.MESSAGE
    assert (
        events[0].sender,
        events[0].reply_id,
        events[0].text,
        events[0].provider_message_id,
    ) == (
        "+919812345678",
        "dept:1",
        "Cardiology",
        "evt-1",
    )
    assert events[1].type is InboundEventType.STATUS and events[1].status == "delivered"
    assert events[2].reply_id == "remind_confirm:9"


def test_meta_cloud_roundtrip(ctx):
    meta = MetaCloudProvider({"access_token": "t", "app_secret": "s", "verify_token": "v"}, ctx)
    body = meta.build_request(
        "+919812345678",
        OutboundMessage(kind=OutboundKind.BUTTONS, text="Q", choices=(Choice("y", "Yes"),)),
    )
    assert (
        body["to"] == "919812345678"
        and body["interactive"]["action"]["buttons"][0]["reply"]["id"] == "y"
    )

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "pn1"},
                            "messages": [
                                {
                                    "from": "919812345678",
                                    "id": "wamid.1",
                                    "timestamp": "1760000000",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {"id": "y", "title": "Yes"},
                                    },
                                }
                            ],
                            "statuses": [
                                {"id": "wamid.0", "status": "read", "recipient_id": "919812345678"}
                            ],
                        }
                    }
                ]
            }
        ]
    }
    events = meta.parse_events(payload)
    assert events[0].reply_id == "y" and events[0].channel_id == "pn1"
    assert events[1].status == "read"

    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"s", raw, hashlib.sha256).hexdigest()
    meta.verify_webhook({"x-hub-signature-256": signature}, raw)
    with pytest.raises(WebhookVerificationError):
        meta.verify_webhook({"x-hub-signature-256": "sha256=bad"}, raw)
    assert (
        meta.webhook_challenge(
            {"hub.mode": "subscribe", "hub.verify_token": "v", "hub.challenge": "42"}
        )
        == "42"
    )


def test_render_text_menu_keeps_choice_ids():
    menu = render_text_menu(
        OutboundMessage(
            kind=OutboundKind.LIST, text="Pick", choices=(Choice("a", "A"), Choice("b", "B"))
        )
    )
    assert menu.kind is OutboundKind.TEXT and menu.metadata["menu"] == ["a", "b"]
