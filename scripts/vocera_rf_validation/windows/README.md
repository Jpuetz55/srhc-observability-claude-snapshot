# Windows RF Validation Upload

The design splits **PCAP QoE** by device (control vs test) but keeps the
**RF validation** panel single-device. On the laptop you stage one `Pcaps\`
folder per badge MAC, plus shared `survey\` and `badge-log\` folders.

## Local layout

Folder names are the badge MAC with `:` replaced by `-`. The per-MAC folders
only need `Pcaps\`; badge logs are shared because RF validation treats the
control and test captures as one logical run.

```text
C:\rf-validation-data\
  survey\                            # shared .esx file
    Main_Campus_Base_Project.esx
  badge-log\                         # shared RF validation badge logs
    20260602_141908-V5.6.1_Build_25-Test_one-0009ef545f46-udd.tar.gz
    20260603_114119-V5.6.1_Build_25-Test_Two-0009ef502a28-udd.tar.gz
  00-09-ef-54-5f-46\                 # control badge ("Test_one" device)
    Pcaps\
      capture_2026-06-02_1102.pcap
  00-09-ef-50-2a-28\                 # test badge ("Test_Two" device)
    Pcaps\
      capture_2026-06-03_1141.pcap
```

The badge firmware export filename pattern is
`<YYYYMMDD>_<HHMMSS>-V<ver>-Test_<one|Two>-<MAC-hex>-udd.tar.gz`. The
Windows script selects one newest shared badge log whose filename contains
either configured badge MAC. It passes the matching MAC with that selected log,
so RF validation never parses a Test_Two log using the Test_one MAC.

## Run

Two-device PCAP run (RF validation uses one newest shared badge log):

```powershell
PowerShell -ExecutionPolicy Bypass -File .\Sync-RfValidationDataAndRun.ps1 `
  -ControlBadgeMac 00:09:ef:54:5f:46 `
  -TestBadgeMac 00:09:ef:50:2a:28
```

Single-device run (omit `-TestBadgeMac`):

```powershell
PowerShell -ExecutionPolicy Bypass -File .\Sync-RfValidationDataAndRun.ps1 `
  -ControlBadgeMac 00:09:ef:54:5f:46
```

Common overrides:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\Sync-RfValidationDataAndRun.ps1 `
  -LocalRoot C:\rf-validation-data `
  -CollectorHost 10.0.128.107 `
  -CollectorUser appsadmin `
  -ControlBadgeMac 00:09:ef:54:5f:46 `
  -TestBadgeMac 00:09:ef:50:2a:28 `
  -RunId srhc_vocera_ekahau_2026_06_03_1430
```

Use `-SkipRfValidation` for a PCAP-only parse/load run. PCAP study lifecycle
actions are handled in Grafana on the collector, not by this laptop script.

Missing or empty `Pcaps\` folders are allowed. The upload still runs and the
server processes whatever PCAP files exist. Missing `survey\` or
`badge-log\` inputs skip RF validation only; PCAP QoE still runs.

## What the server does with a two-device run

The script bundles + uploads the whole tree to
`/var/lib/vocera-rf-validation/uploads/<run-id>/` and triggers
`scripts/run_vocera_survey_refresh.sh` with the upload root as
`VOCERA_SURVEY_MEDIA_RAW_DIR` plus one RF badge log selected from the shared
`badge-log\` folder. The server then:

- **PCAP QoE: all uploaded PCAPs together.** The media parser recursively
  discovers PCAP files below the upload root. Control/test labeling comes
  from `config/vocera-media-qoe.yaml` device IP mappings. After a successful
  parse/load, uploaded `.pcap`, `.pcapng`, and `.cap` inputs under the run's
  upload directory are deleted.
- **RF validation: single device.** One selected shared badge diagnostic
  archive is parsed against the shared Ekahau survey. Outputs and DB rows use
  the base `test_run_id` with no role suffix.

The job manifest at
`data/vocera-rf-validation/out/jobs/<run-id-base>.json` carries a media parse
entry plus a single `rf_validation` block.

## Comparing control vs test in Grafana

PCAP QoE panels use `device_role = control` and `device_role = test` from the
parser's configured device IP mappings.

RF validation panels stay as-is - no device_role filtering needed.

## Rollback

```bash
cd /home/appsadmin/grafana-mimir-observability
sudo bash ./scripts/rollback_vocera_survey_refresh.sh --run-id srhc_vocera_ekahau_2026_06_03_1430
```

Add `--dry-run` to preview actions. Add `--remove-current-outputs` when the bad
run is still the current JSON/CSV/prom output and should be cleared.
