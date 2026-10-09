"""Pure field policy; identity resolution and transactional storage remain separate."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping, Any

from backend.catalog_package import CatalogPackageError, FIELDS

EDITABLE_FIELDS = frozenset(FIELDS)-{'id','tmdb_id'}


@dataclass(frozen=True)
class FieldUpdatePlan:
    changes: dict[str,Any]
    baseline: dict[str,Any]


def plan_field_updates(current: Mapping[str,Any], incoming: Mapping[str,Any],
                       baseline: Mapping[str,Any]) -> FieldUpdatePlan:
    """Plan one already identity-matched, validated movie in normalized JSON form.

    Missing/NULL provider values are not deletion commands. Unknown legacy
    filled fields never silently become managed. Caller must validate identity,
    normalize SQLite JSON fields, and commit changes/baseline atomically.
    This function does not change inputs, identifiers, files or the database.
    """
    if set(incoming)-set(FIELDS):
        raise CatalogPackageError('В обновлении карточки есть неизвестные поля')
    next_baseline = {key:deepcopy(value) for key,value in baseline.items() if key in EDITABLE_FIELDS}
    changes = {}
    for field,value in incoming.items():
        if field not in EDITABLE_FIELDS or value is None:
            continue
        local = current.get(field)
        if field not in baseline:
            if local is not None:
                continue
        elif local!=baseline[field]:
            # Keep the local override but remember the latest provider value.
            next_baseline[field] = deepcopy(value)
            continue
        if local!=value:
            changes[field] = deepcopy(value)
        next_baseline[field] = deepcopy(value)
    return FieldUpdatePlan(changes,next_baseline)
