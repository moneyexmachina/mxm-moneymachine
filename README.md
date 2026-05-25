![Version](https://img.shields.io/github/v/release/moneyexmachina/mxm-moneymachine)
![License](https://img.shields.io/github/license/moneyexmachina/mxm-moneymachine)
![Python](https://img.shields.io/badge/python-3.13+-blue)
[![Checked with pyright](https://microsoft.github.io/pyright/img/pyright_badge.svg)](https://microsoft.github.io/pyright/)

Compound trading-system package for the Money Ex Machina ecosystem.

`mxm-moneymachine` is the first public engineering baseline of the core Money Ex Machina trading system. It contains infrastructure and domain components for calendars, market data, synthetic assets, execution, holdings, backtesting, and portfolio construction.

The repository is under active public development. The maintained surface is the typed Python package and tests covered by `make check`. Operational scripts, smoke workflows, and Prefect deployments are currently being consolidated into a formal execution and operator layer.

## Purpose

The goal of `mxm-moneymachine` is to build a fully inspectable, reproducible, and systematically engineered trading system from first principles.

The project is designed around several core principles:

- strict typing and explicit contracts  
- deterministic and testable infrastructure  
- separation between semantic and operational concerns  
- reproducible configuration and execution  
- composable system architecture  
- executable workflows rather than static models  
- public, incremental development  

Current implemented areas include:

- calendar construction and loading  
- reference-data integration  
- contract selection and contract-series construction  
- synthetic asset specification, registry, component contracts, component weights, and target holdings  
- market-data storage, schema coercion, and orchestration components  
- execution simulation, order generation, holdings transitions, and backtesting  
- P&L construction and return processing  

The current repository state should be understood as a clean engineering baseline rather than a finished trading platform or stable release product.

## Installation

Clone the repository and install dependencies using Poetry:

```bash
git clone https://github.com/moneyexmachina/mxm-moneymachine.git

cd mxm-moneymachine

poetry install
```

The project currently targets:

- Python 3.13+
- Poetry-managed environments

## Usage

Run the canonical package validation gate:

```bash
make check
```

This executes:

- formatting checks  
- linting  
- strict Pyright type checking  
- pytest test suite  

Run tests directly:

```bash
pytest
```

Run strict typing directly:

```bash
pyright
```

The package is currently focused on infrastructure and system components rather than end-user CLI workflows. Smoke workflows, operator commands, and Prefect-based runtime orchestration are planned as the next consolidation layer.

## Architecture Overview

`mxm-moneymachine` is organised around several major domains:

- `calendars` — trading-session calendars and schedules  
- `marketdata` — storage, schemas, orchestration, and dataset ingestion  
- `synthetic_assets` — synthetic asset definitions, registries, contract mappings, and weights  
- `execution` — order generation, execution simulation, holdings transitions, and backtesting  
- `pnl` — position and return construction  
- `utils` — canonical timestamp handling, coercion, and shared utilities  

The system integrates with several external MXM packages, including:

- `mxm-types`
- `mxm-config`
- `mxm-dataio`
- `mxm-refdata`
- `mxm-secrets`

## Development

Install dependencies:

```bash
poetry install
```

Run the full validation gate:

```bash
make check
```

Run formatting:

```bash
make fmt
```

The repository follows the MXM package contract enforced by `mxm-foundry`, including:

- canonical formatting configuration  
- strict Pyright typing  
- deterministic Makefile targets  
- pytest integration  
- documentation and package structure requirements  

The next development phase focuses on:

- executable smoke workflows  
- Prefect orchestration and deployments  
- operator-facing CLI interfaces  
- documentation consolidation  
- workflow demonstrations and runtime observability  

## License

MIT License. See [LICENSE](LICENSE).

