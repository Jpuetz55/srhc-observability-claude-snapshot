# Kubernetes and Mimir platform

This repo assumes a Kustomize-oriented deployment model.

## Base intent
The base layer holds shared observability resources:
- namespace
- Grafana config
- Prometheus config and rules
- Mimir-oriented platform dashboards

## Overlays
- `deploy/k8s/overlays/dev` for a small editable environment
- `deploy/k8s/overlays/prod` for the provisioned production profile

## Monitoring goals
- deployment health
- pod readiness and availability
- node readiness
- Prometheus remote write health
- Mimir ingest visibility
