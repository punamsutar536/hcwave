"""Bundle of domain services built once per process from the container."""

from __future__ import annotations

from dataclasses import dataclass

from hcwave.core.container import Container
from hcwave.domain.booking import BookingService
from hcwave.domain.briefing import BriefingService
from hcwave.domain.feedback import FeedbackService, TicketService
from hcwave.domain.his_sync import HisSyncService
from hcwave.domain.messenger import Messenger
from hcwave.domain.reminders import ReminderService
from hcwave.domain.reports import ReportService


@dataclass(frozen=True)
class Services:
    """All domain services, sharing one container and messenger."""

    container: Container
    messenger: Messenger
    booking: BookingService
    reminders: ReminderService
    reports: ReportService
    tickets: TicketService
    feedback: FeedbackService
    briefing: BriefingService
    his_sync: HisSyncService

    @classmethod
    def build(cls, container: Container) -> Services:
        """Wires every service from the container."""
        messenger = Messenger(container.settings, container.messaging)
        reports = ReportService(container, messenger)
        tickets = TicketService(container, messenger)
        return cls(
            container=container,
            messenger=messenger,
            booking=BookingService(container.settings),
            reminders=ReminderService(container, messenger),
            reports=reports,
            tickets=tickets,
            feedback=FeedbackService(container, messenger, tickets),
            briefing=BriefingService(container, messenger),
            his_sync=HisSyncService(container, reports),
        )
