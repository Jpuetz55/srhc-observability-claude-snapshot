# Kubernetes manifest scaffolding

> **Not the active deployment path.** The live platform runs on the collector
> VM. See [`../../docs/architecture.md`](../../docs/architecture.md) and
> [`../../docs/k8s-mimir-platform.md`](../../docs/k8s-mimir-platform.md).

This directory is a minimal Kustomize skeleton retained for design exploration:

- `base/` contains shared resource concepts;
- `overlays/dev/` models an editable development profile; and
- `overlays/prod/` models a prospective production profile.

`make kustomize-validate` validates manifest rendering only. It does not deploy
or validate the VM services, WLC telemetry receiver path, local PostgreSQL
datasources, Study Web, Mimir storage, or Grafana dashboard state.
