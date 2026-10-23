"""Staff identity: just-in-time provisioning from Microsoft Entra ID tokens."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hcwave.core.clock import utcnow
from hcwave.db.models import StaffUser


@dataclass(frozen=True)
class StaffPrincipal:
    """An authenticated staff member.

    Attributes:
        oid: Entra object ID (stable user identifier).
        name: Display name.
        email: Email / UPN.
        roles: Platform roles (``front_office``, ``patient_relations``,
            ``unit_head``, ``admin``).
        hospital_ids: Hospitals the user may access.
    """

    oid: str
    name: str
    email: str
    roles: frozenset[str] = field(default_factory=frozenset)
    hospital_ids: frozenset[str] = field(default_factory=frozenset)

    def has_any(self, *roles: str) -> bool:
        """True if the user holds any of ``roles`` (admin holds all)."""
        return "admin" in self.roles or bool(self.roles.intersection(roles))


async def provision_staff(
    session: AsyncSession, hospital_id: str, principal: StaffPrincipal
) -> StaffUser:
    """Creates or refreshes the staff row for the signed-in user."""
    user = await session.scalar(
        select(StaffUser).where(
            StaffUser.hospital_id == hospital_id, StaffUser.external_oid == principal.oid
        )
    )
    if user is None:
        user = StaffUser(hospital_id=hospital_id, external_oid=principal.oid)
        session.add(user)
    user.email, user.display_name = principal.email, principal.name
    user.roles, user.active, user.last_login_at = sorted(principal.roles), True, utcnow()
    await session.flush()
    return user
