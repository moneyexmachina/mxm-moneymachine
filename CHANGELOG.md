# Changelog

All notable changes to this project will be documented in this file.

This project adheres to [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## [0.1.0] - 2026-05-25

### Added

#### Core System Foundations

- Initial public release of `mxm-moneymachine`.
- Compound trading-system package for the Money Ex Machina ecosystem.
- Strictly typed Python package targeting Python 3.13+.
- Canonical MXM package structure enforced via `mxm-foundry`.

#### Calendars

- Trading calendar loading and validation infrastructure.
- Calendar registry and calendar-service integration.
- Support for observed and projected trading-day surfaces.
- Canonical business-session handling.

#### Market Data

- Market-data schema coercion and validation framework.
- Daily mark canonicalisation and validation logic.
- Statistics-1d dataset storage and orchestration components.
- Market-data ingestion orchestration and attempt tracking.
- SQLite-backed dataset persistence infrastructure.

#### Reference Data Integration

- Integration with `mxm-refdata`.
- Product and contract lifecycle resolution.
- Contract metadata integration into synthetic assets and execution systems.

#### Synthetic Assets

- Synthetic asset specifications and registries.
- Component contract construction.
- Component weight generation.
- Contract-series handling.
- Trading-days-to-LTD infrastructure.
- Target holdings generation.

#### Execution and Backtesting

- Order generation framework.
- Holdings transition and preparation logic.
- Perfect execution simulator.
- Execution timestamp handling.
- Backtesting infrastructure and execution integration.

#### P&L and Returns

- Position and P&L construction infrastructure.
- Return-processing utilities.
- Canonical timestamp handling for execution and P&L systems.

#### Utilities and Infrastructure

- Canonical timestamp substrate using `np.datetime64[ns]`.
- Timestamp coercion and conversion utilities.
- Pandas timestamp interoperability utilities.
- Shared coercion and validation helpers.

#### Engineering Standards

- Full Ruff, Black, Isort, Pyright, and Pytest integration.
- Strict Pyright-clean codebase.
- Green `make check` publication baseline.
- MXM namespace package migration:
  - `mxm.v1` → `mxm.moneymachine`
  - repository rename:
    - `mxm-v1` → `mxm-moneymachine`

### Changed

- Standardised repository structure against `mxm-foundry`.
- Migrated internal timestamp handling toward canonical MXM timestamp semantics.
- Consolidated validation and coercion boundaries across market-data schemas.
- Updated tests and infrastructure to reflect non-null reference-data API semantics.
- Refactored package naming and namespace structure to align with long-term MXM architecture.

### Fixed

- Eliminated accumulated Ruff formatting drift.
- Eliminated accumulated Pyright strict-typing drift.
- Corrected stale fake/test API contracts across:
  - reference-data APIs
  - market-data orchestration
  - execution timestamp handling
- Fixed timestamp canonicalisation inconsistencies between pandas and MXM timestamp utilities.
- Corrected multiple schema coercion and validation-path inconsistencies.
- Restored full green `make check` state after namespace migration.

### Notes

- This release represents the first public engineering baseline of the Money Ex Machina trading-system package.
- The repository is under active public development and should not yet be considered a stable release product.
- The maintained surface is currently the typed package and tests covered by `make check`.
- Operational scripts, smoke workflows, Prefect deployments, and operator-facing interfaces are currently being consolidated into a formal runtime layer.

### Upgrade Guidance

- The previous `mxm-v1` namespace has been renamed to:
  ```python
  mxm.moneymachine
  ```

- Recreate Poetry virtual environments after migration if stale editable-install metadata is present:

  ```bash
  rm -rf .venv

  poetry env remove --all

  poetry install
  ```
