# Kubernetes and Mimir scaffolding status

> **Status: retained reference, not the deployed collector architecture.** The
> active deployment is the single collector VM described in
> [`architecture.md`](architecture.md): local Telegraf, Prometheus, Mimir,
> Grafana, PostgreSQL services, and Study Web. Do not use this document as a
> deployment runbook for the current environment.

The `deploy/k8s/` tree remains Kustomize-oriented scaffolding for a possible
future Kubernetes implementation. Its base/overlay layout is useful for
studying how shared configuration could be expressed, but it is not the source
of truth for the live VM’s service units, loopback ports, local Mimir storage,
or dashboard promotion workflow.

Before treating Kubernetes manifests as operational, the project would need a
reviewed design for at least:

- service discovery, durable storage, and Mimir tenancy;
- secrets management and certificate rotation;
- the WLC gRPC dial-out receiver topology;
- PostgreSQL persistence/backup and Study Web delivery;
- node-exporter textfile and manual evidence staging equivalents; and
- an explicit migration/rollback plan from the collector VM.

Use `make kustomize-validate` only as a manifest syntax check. It does not
prove a deployed Kubernetes observability platform exists.
