"""Единый мир: тики, флоты, постройки, карта, влияние."""

from __future__ import annotations

from app.services.world_service._mixin_01 import WorldServiceMixin01
from app.services.world_service._mixin_02 import WorldServiceMixin02
from app.services.world_service._mixin_03 import WorldServiceMixin03
from app.services.world_service._mixin_04 import WorldServiceMixin04
from app.services.world_service._mixin_05 import WorldServiceMixin05
from app.services.world_service._mixin_06 import WorldServiceMixin06
from app.services.world_service._mixin_07 import WorldServiceMixin07


class WorldService(
    WorldServiceMixin01,
    WorldServiceMixin02,
    WorldServiceMixin03,
    WorldServiceMixin04,
    WorldServiceMixin05,
    WorldServiceMixin06,
    WorldServiceMixin07,
):
    """Порядок миксинов задаёт MRO; публичный API не менялся."""


__all__ = ["WorldService"]
