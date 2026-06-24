# Getting started

## Validate the repo
```bash
make validate
```

## Dry-run production promotion
```bash
make plan
```

## Promote to production
```bash
make deploy
```

## Sync production baseline back into DEV
```bash
make dashboard-sync-prod-to-dev
```

## Expectations
You need Grafana API access for export and org-sync operations, plus filesystem and service access on the production runtime for full promotion.
