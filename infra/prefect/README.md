# MXM Prefect Runtime

This directory defines the self-hosted Prefect control plane for
`mxm-moneymachine`.

The stack is configuration-first and secret-safe:

```text
non-secret config -> environment defaults / .env.example
secret source     -> gopass
runtime injection -> infra/prefect/stack.sh
compose consumer  -> Docker Compose secrets
```

No cleartext secret `.env` file is required.

## Services

The initial stack contains:

- `postgres`: Prefect operational database
- `redis`: Prefect messaging/cache backend
- `prefect-server`: Prefect API and UI
- `prefect-services`: Prefect background services

Workers are added after the control plane is verified.

## Files

```text
infra/prefect/
  compose.yml
  .env.example
  stack.sh
  README.md
```

## Secret policy

MXM invariant:

```text
No committed or persisted cleartext secrets outside gopass.
```

The Prefect Postgres password is read from gopass at runtime and injected into
Docker Compose as a Docker secret.

Default gopass path:

```text
mxm/green/<env>/prefect/postgres/password
```

Create it with:

```bash
gopass insert mxm/green/<env>/prefect/postgres/password
```

## Start

```bash
infra/prefect/stack.sh up
```

## Inspect

```bash
infra/prefect/stack.sh ps
```

```bash
infra/prefect/stack.sh logs
```

## Stop

```bash
infra/prefect/stack.sh down
```

## Reset

This destroys the Prefect Postgres and Redis Docker volumes.

```bash
infra/prefect/stack.sh reset
```

## Prefect UI

Local development URL:

```text
http://localhost:4200
```

## Local Prefect CLI

Point the host-machine Prefect CLI at the local server:

```bash
export PREFECT_API_URL=http://localhost:4200/api
```

Then verify:

```bash
prefect config view
prefect work-pool ls
```

## Endpoint model

There are two different API URLs:

```text
Host/browser/CLI:
  http://localhost:4200/api

Container-internal:
  http://prefect-server:4200/api
```

The UI needs the host/browser URL.

Workers or flow containers running inside the Compose network usually need the
container-internal URL.

## Current scope

This stack is the Prefect control plane only.

Next steps:

1. verify server startup
2. verify CLI connectivity
3. create `mxm-dev-process` work pool
4. create `mxm-dev-docker` work pool
5. run `instrument_definition_flow` through both execution backends

