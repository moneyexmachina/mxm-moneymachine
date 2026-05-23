"""
MXM V1 — Calendar registry.

The calendar registry is the authoritative index of calendar artifacts stored in
user refdata. It is the semantic contract between:

- builders (which generate artifacts + populate registry metadata)
- loaders (which load artifacts + validate against the registry)
- downstream consumers (which rely on deterministic calendar semantics)

The registry is stored as YAML and describes, per calendar_id:
- upstream provenance (package + version + source calendar name)
- observed region (start/end, artifact filenames, checksums)
- projection region (rule_id, start/end, artifact filenames, checksums)
- generation timestamp

This module defines the strict schema and validation rules for those entries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import yaml

from mxm.moneymachine.utils.date_utils import coerce_np_day
from mxm.types import JSONMap, JSONValue

TABLE_EVENTS = "instrument_definition_events"
TABLE_WATERMARKS = "instrument_definition_watermarks"
TABLE_CURRENT = "instrument_definition_current"


class CalendarRegistryError(RuntimeError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message)


def _coerce_json_value(x: object, *, where: str) -> JSONValue:
    """
    Validate and coerce a YAML-loaded Python object into MXM JSONValue.

    The calendar registry is stored as YAML, but its semantic data model is a
    JSON-compatible tree:
    - scalar leaves
    - lists
    - dictionaries with string keys
    """
    if x is None or isinstance(x, str | int | float | bool):
        return x

    if isinstance(x, list):
        xs = cast(list[object], x)
        return [_coerce_json_value(v, where=f"{where}[{i}]") for i, v in enumerate(xs)]

    if isinstance(x, dict):
        raw = cast(dict[object, object], x)
        out: JSONMap = {}

        for k, v in raw.items():
            if not isinstance(k, str):
                raise CalendarRegistryError(
                    f"{where} keys must be strings, got {type(k)!r}"
                )
            out[k] = _coerce_json_value(v, where=f"{where}.{k}")

        return out

    raise CalendarRegistryError(
        f"{where} contains unsupported registry value type: {type(x).__name__}"
    )


def _require_mapping(x: object, *, where: str) -> JSONMap:
    value = _coerce_json_value(x, where=where)

    if not isinstance(value, dict):
        raise CalendarRegistryError(f"{where} must be a mapping")

    return value


def _require_str(x: object, *, where: str) -> str:
    if not isinstance(x, str) or not x.strip():
        raise CalendarRegistryError(f"{where} must be a non-empty string")
    return x.strip()


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """
    Source provenance for a calendar build.

    The registry is source-agnostic. The `kind` discriminator identifies the
    source type, while `spec` stores source-specific builder metadata.
    """

    kind: str
    spec: JSONMap


@dataclass(frozen=True, slots=True)
class BuilderInfo:
    """
    Provenance for the build process that produced the artifacts.
    """

    builder_id: str
    mxm_version: str | None
    params: JSONMap | None


@dataclass(frozen=True, slots=True)
class ObservedSection:
    start: np.datetime64
    end: np.datetime64
    trading_days_artifact: str
    schedule_artifact: str
    sha256_trading_days: str
    sha256_schedule: str


@dataclass(frozen=True, slots=True)
class ProjectionSection:
    rule_id: str
    start: np.datetime64
    end: np.datetime64
    trading_days_artifact: str
    sha256_trading_days: str


@dataclass(frozen=True, slots=True)
class CalendarRegistryEntry:
    calendar_id: str
    source: SourceInfo
    observed: ObservedSection
    projection: ProjectionSection
    generated_at: str
    builder: BuilderInfo | None = None


def load_calendar_registry(registry_path: Path) -> dict[str, CalendarRegistryEntry]:
    """
    Load calendar_registry.yaml and return mapping calendar_id -> CalendarRegistryEntry.
    """
    raw = _load_registry_yaml(registry_path)
    entries = _normalize_registry_entries(raw)
    return _parse_and_validate_registry_entries(entries)


def _load_registry_yaml(registry_path: Path) -> JSONValue:
    if not registry_path.exists():
        raise CalendarRegistryError(f"Calendar registry not found: {registry_path}")

    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))

    if raw is None:
        raise CalendarRegistryError(f"Calendar registry is empty: {registry_path}")

    return _coerce_json_value(raw, where="calendar_registry")


def _normalize_registry_entries(raw: JSONValue) -> dict[str, JSONMap]:
    if isinstance(raw, dict):
        return _normalize_registry_mapping(raw)

    if isinstance(raw, list):
        return _normalize_registry_list(raw)

    raise CalendarRegistryError(f"Unsupported registry YAML type: {type(raw)!r}")


def _normalize_registry_mapping(raw: JSONMap) -> dict[str, JSONMap]:
    if "calendar_id" in raw:
        return _normalize_single_registry_entry_mapping(raw)

    return _normalize_registry_mapping_by_calendar_id(raw)


def _normalize_single_registry_entry_mapping(raw: JSONMap) -> dict[str, JSONMap]:
    calendar_id = raw.get("calendar_id")

    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise CalendarRegistryError(
            "Registry single-entry mapping missing valid calendar_id"
        )

    return {calendar_id: raw}


def _normalize_registry_mapping_by_calendar_id(raw: JSONMap) -> dict[str, JSONMap]:
    entries: dict[str, JSONMap] = {}

    for key, value in raw.items():
        if not isinstance(value, dict):
            raise CalendarRegistryError(f"Registry entry for {key!r} must be a mapping")

        entries[key] = value

    return entries


def _normalize_registry_list(raw: list[JSONValue]) -> dict[str, JSONMap]:
    entries: dict[str, JSONMap] = {}

    for item in raw:
        if not isinstance(item, dict):
            raise CalendarRegistryError("Registry list items must be mappings")

        calendar_id = item.get("calendar_id")

        if not isinstance(calendar_id, str) or not calendar_id.strip():
            raise CalendarRegistryError("Registry list item missing valid calendar_id")

        entries[calendar_id] = item

    return entries


def _parse_and_validate_registry_entries(
    entries: dict[str, JSONMap],
) -> dict[str, CalendarRegistryEntry]:
    registry: dict[str, CalendarRegistryEntry] = {}

    for calendar_id, entry_dict in entries.items():
        parsed = _parse_entry(entry_dict, fallback_calendar_id=calendar_id)
        validate_registry_entry(parsed)
        registry[parsed.calendar_id] = parsed

    return registry


def get_registry_entry(
    registry: Mapping[str, CalendarRegistryEntry], calendar_id: str
) -> CalendarRegistryEntry:
    try:
        return registry[calendar_id]
    except KeyError as e:
        raise CalendarRegistryError(f"Unknown calendar_id {calendar_id!r}") from e


def validate_registry_entry(entry: CalendarRegistryEntry) -> None:
    """
    Structural and semantic validation.
    """
    _validate_observed_region(entry)
    _validate_projection_region(entry)
    _validate_observed_projection_boundary(entry)
    _validate_source_provenance(entry)
    _validate_builder_provenance(entry)
    _validate_projection_rule(entry)
    _validate_artifact_filenames(entry)


def _validate_observed_region(entry: CalendarRegistryEntry) -> None:
    observed = entry.observed

    if observed.start > observed.end:
        raise CalendarRegistryError(
            f"{entry.calendar_id}: observed.start after observed.end: "
            f"{observed.start} > {observed.end}"
        )


def _validate_projection_region(entry: CalendarRegistryEntry) -> None:
    projection = entry.projection

    if projection.start > projection.end:
        raise CalendarRegistryError(
            f"{entry.calendar_id}: projection.start after projection.end: "
            f"{projection.start} > {projection.end}"
        )


def _validate_observed_projection_boundary(entry: CalendarRegistryEntry) -> None:
    observed = entry.observed
    projection = entry.projection

    if projection.start <= observed.end:
        raise CalendarRegistryError(
            f"{entry.calendar_id}: projection.start must be strictly after "
            f"observed.end (got {projection.start} <= {observed.end})"
        )

    if projection.end <= observed.end:
        raise CalendarRegistryError(
            f"{entry.calendar_id}: projection.end must extend beyond "
            f"observed.end (got {projection.end} <= {observed.end})"
        )


def _validate_source_provenance(entry: CalendarRegistryEntry) -> None:
    if not entry.source.kind or not entry.source.kind.strip():
        raise CalendarRegistryError(f"{entry.calendar_id}: source.kind is required")


def _validate_builder_provenance(entry: CalendarRegistryEntry) -> None:
    if entry.builder is None:
        return

    if not entry.builder.builder_id or not entry.builder.builder_id.strip():
        raise CalendarRegistryError(
            f"{entry.calendar_id}: builder.builder_id is required "
            "if builder block is present"
        )


def _validate_projection_rule(entry: CalendarRegistryEntry) -> None:
    if not entry.projection.rule_id:
        raise CalendarRegistryError(
            f"{entry.calendar_id}: projection.rule_id is required"
        )


def _validate_artifact_filenames(entry: CalendarRegistryEntry) -> None:
    observed = entry.observed
    projection = entry.projection

    for artifact_name in (
        observed.trading_days_artifact,
        observed.schedule_artifact,
        projection.trading_days_artifact,
    ):
        _validate_artifact_filename(
            calendar_id=entry.calendar_id,
            artifact_name=artifact_name,
        )


def _validate_artifact_filename(
    *,
    calendar_id: str,
    artifact_name: str,
) -> None:
    if "/" in artifact_name or "\\" in artifact_name:
        raise CalendarRegistryError(
            f"{calendar_id}: artifact paths must be relative filenames, "
            f"got {artifact_name!r}"
        )


def validate_registry_files_exist(
    entry: CalendarRegistryEntry, calendar_root: Path
) -> None:
    """
    Optional validation: ensure artifact files referenced by the registry exist.
    """
    observed = entry.observed
    projection = entry.projection

    cal_dir = calendar_root / entry.calendar_id
    missing: list[str] = []

    for filename in (
        observed.trading_days_artifact,
        observed.schedule_artifact,
        projection.trading_days_artifact,
    ):
        path = cal_dir / filename
        if not path.exists():
            missing.append(str(path))

    if missing:
        raise CalendarRegistryError(
            f"{entry.calendar_id}: missing artifact files:\n" + "\n".join(missing)
        )


def _parse_entry(d: JSONMap, *, fallback_calendar_id: str) -> CalendarRegistryEntry:
    """
    Parse a single registry entry mapping into a CalendarRegistryEntry.
    """
    calendar_id_any = d.get("calendar_id")
    calendar_id = (
        calendar_id_any.strip()
        if isinstance(calendar_id_any, str) and calendar_id_any.strip()
        else fallback_calendar_id
    )

    src = _require_mapping(d.get("source"), where=f"{calendar_id}.source")
    kind = _require_str(src.get("kind"), where=f"{calendar_id}.source.kind")

    spec_any = src.get("spec")
    spec = (
        {}
        if spec_any is None
        else _require_mapping(spec_any, where=f"{calendar_id}.source.spec")
    )
    source = SourceInfo(kind=kind, spec=spec)

    obs = _require_mapping(d.get("observed"), where=f"{calendar_id}.observed")
    obs_sha = _require_mapping(
        obs.get("sha256"), where=f"{calendar_id}.observed.sha256"
    )

    observed = ObservedSection(
        start=coerce_np_day(obs.get("start")),
        end=coerce_np_day(obs.get("end")),
        trading_days_artifact=_require_str(
            obs.get("trading_days_artifact"),
            where=f"{calendar_id}.observed.trading_days_artifact",
        ),
        schedule_artifact=_require_str(
            obs.get("schedule_artifact"),
            where=f"{calendar_id}.observed.schedule_artifact",
        ),
        sha256_trading_days=_require_str(
            obs_sha.get("trading_days"),
            where=f"{calendar_id}.observed.sha256.trading_days",
        ),
        sha256_schedule=_require_str(
            obs_sha.get("schedule"),
            where=f"{calendar_id}.observed.sha256.schedule",
        ),
    )

    proj = _require_mapping(d.get("projection"), where=f"{calendar_id}.projection")
    proj_sha = _require_mapping(
        proj.get("sha256"), where=f"{calendar_id}.projection.sha256"
    )

    projection = ProjectionSection(
        rule_id=_require_str(
            proj.get("rule_id"), where=f"{calendar_id}.projection.rule_id"
        ),
        start=coerce_np_day(proj.get("start")),
        end=coerce_np_day(proj.get("end")),
        trading_days_artifact=_require_str(
            proj.get("trading_days_artifact"),
            where=f"{calendar_id}.projection.trading_days_artifact",
        ),
        sha256_trading_days=_require_str(
            proj_sha.get("trading_days"),
            where=f"{calendar_id}.projection.sha256.trading_days",
        ),
    )

    generated_at = str(d.get("generated_at") or "")
    builder = _parse_builder(d.get("builder"), calendar_id=calendar_id)

    return CalendarRegistryEntry(
        calendar_id=calendar_id,
        source=source,
        observed=observed,
        projection=projection,
        generated_at=generated_at,
        builder=builder,
    )


def _parse_builder(
    builder_any: JSONValue | None,
    *,
    calendar_id: str,
) -> BuilderInfo | None:
    if builder_any is None:
        return None

    b = _require_mapping(builder_any, where=f"{calendar_id}.builder")

    builder_id = _require_str(
        b.get("builder_id"), where=f"{calendar_id}.builder.builder_id"
    )

    mxm_version_any = b.get("mxm_version")
    mxm_version = (
        None
        if mxm_version_any is None
        else _require_str(mxm_version_any, where=f"{calendar_id}.builder.mxm_version")
    )

    params_any = b.get("params")
    params = (
        None
        if params_any is None
        else _require_mapping(params_any, where=f"{calendar_id}.builder.params")
    )

    return BuilderInfo(
        builder_id=builder_id,
        mxm_version=mxm_version,
        params=params,
    )


def _day_to_iso(d: np.datetime64) -> str:
    """
    Convert numpy datetime64 to ISO 'YYYY-MM-DD' at day precision.
    """
    dd = d.astype("datetime64[D]")
    return str(dd)


def _entry_to_yaml(entry: CalendarRegistryEntry) -> JSONMap:
    out: JSONMap = {
        "calendar_id": entry.calendar_id,
        "source": {
            "kind": entry.source.kind,
            "spec": entry.source.spec,
        },
        "observed": {
            "start": _day_to_iso(entry.observed.start),
            "end": _day_to_iso(entry.observed.end),
            "trading_days_artifact": entry.observed.trading_days_artifact,
            "schedule_artifact": entry.observed.schedule_artifact,
            "sha256": {
                "trading_days": entry.observed.sha256_trading_days,
                "schedule": entry.observed.sha256_schedule,
            },
        },
        "projection": {
            "rule_id": entry.projection.rule_id,
            "start": _day_to_iso(entry.projection.start),
            "end": _day_to_iso(entry.projection.end),
            "trading_days_artifact": entry.projection.trading_days_artifact,
            "sha256": {
                "trading_days": entry.projection.sha256_trading_days,
            },
        },
        "generated_at": entry.generated_at,
    }

    if entry.builder is not None:
        out["builder"] = {
            "builder_id": entry.builder.builder_id,
            "mxm_version": entry.builder.mxm_version,
            "params": entry.builder.params,
        }

    return out


def write_calendar_registry(
    path: Path, registry: dict[str, CalendarRegistryEntry]
) -> None:
    """
    Write registry entries to disk as a mapping keyed by calendar_id.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    data: JSONMap = {}
    for calendar_id, entry in registry.items():
        data[calendar_id] = _entry_to_yaml(entry)

    txt = yaml.safe_dump(data, sort_keys=True)
    path.write_text(txt, encoding="utf-8")
