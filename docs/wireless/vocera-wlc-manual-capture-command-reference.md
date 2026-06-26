# Vocera WLC Manual Capture Command Reference

The Study Web WLC session workflow generates these command sheets with
session-specific capture names, ACL names, MACs, VLANs, and SCP export paths.
Operators must verify placeholder syntax with WLC `?` help before starting EPC.

Cisco's Catalyst 9800 EPC documentation is the authoritative reference for
controller syntax. For the current WLC session workflow, the generated circular
buffer syntax is:

```text
monitor capture <CAPTURE_NAME> buffer circular file <COUNT> file-size <MB>
```

Do not use older examples that show `buffer circular size <MB>` for production
WLC session captures.

## Before

```text
terminal length 0
show clock detail
show wireless client mac-address <C1000_MAC> detail
show wireless client mac-address <C1000_MAC> mobility history
show wireless client mac-address <V5000_MAC> detail
show wireless client mac-address <V5000_MAC> mobility history
show wireless multicast
show ap multicast mom
show ip igmp snooping
show ip igmp snooping wireless mgid
show wireless multicast group summary
```

## During

```text
terminal length 0
show clock detail
show wireless multicast group summary
show wireless multicast group <VOCERA_GROUP> vlan <VOCERA_VLAN>
show wireless multicast source 0.0.0.0 group <VOCERA_GROUP> vlan <VOCERA_VLAN>
show ip igmp snooping groups vlan <VOCERA_VLAN>
show ip igmp snooping igmpv2-tracking
show wireless client mac-address <C1000_MAC> detail
show wireless client mac-address <V5000_MAC> detail
show ap multicast mom
```

## After

```text
terminal length 0
show clock detail
show wireless client mac-address <C1000_MAC> detail
show wireless client mac-address <C1000_MAC> mobility history
show wireless multicast group summary
show ip igmp snooping igmpv2-tracking
show ap multicast mom
```

## EPC Start/Stop

The generated EPC sheets include concrete values for the selected session.
Exact syntax must still be validated on the target WLC before the first smoke
capture because Cisco IOS XE command availability can vary by release and
platform.

### Short Validation Capture

The 60- to 120-second smoke test uses a duration limit. Example shape:

```text
show monitor capture <CAPTURE_NAME>
monitor capture <CAPTURE_NAME> interface Port-channel 1 both
monitor capture <CAPTURE_NAME> buffer circular file 5 file-size 100
monitor capture <CAPTURE_NAME> access-list <TEMPORARY_ACL_NAME>
monitor capture <CAPTURE_NAME> match ipv4 any any
monitor capture <CAPTURE_NAME> inner mac <V5000_MAC> <C1000_MAC>
monitor capture <CAPTURE_NAME> limit duration 90
monitor capture <CAPTURE_NAME> start
```

### Long Reproduction Capture

Long reproduction captures intentionally have no duration limit. The operator
stops and exports after the failure is reproduced:

```text
show monitor capture <CAPTURE_NAME>
monitor capture <CAPTURE_NAME> interface Port-channel 1 both
monitor capture <CAPTURE_NAME> buffer circular file 5 file-size 100
monitor capture <CAPTURE_NAME> access-list <TEMPORARY_ACL_NAME>
monitor capture <CAPTURE_NAME> match ipv4 any any
monitor capture <CAPTURE_NAME> inner mac <V5000_MAC> <C1000_MAC>
monitor capture <CAPTURE_NAME> start
```

### Stop, Export, Cleanup

The export destination must be the session package `incoming/` directory. The
collector ingest service validates and finalizes the EPC into `pcaps/`; the WLC
must not export directly to `pcaps/`.

```text
monitor capture <CAPTURE_NAME> stop
show monitor capture <CAPTURE_NAME>
monitor capture <CAPTURE_NAME> export scp://<SCP_USER>@<COLLECTOR>//var/lib/vocera-media-qoe/raw/wlc-sessions/<STUDY>/<SESSION>/incoming/<SESSION>.pcap
```

Only after the WLC reports a successful SCP export, run cleanup:

```text
no monitor capture <CAPTURE_NAME>
no ip access-list extended <TEMPORARY_ACL_NAME>
show monitor capture <CAPTURE_NAME>
```

## Audit Notes

- The active Study Web WLC session generator and its tests use
  `buffer circular file <COUNT> file-size <MB>`.
- The legacy `vocera_wlc_attempt.py` attempt-only helper still contains an older
  example command shape and should not be used as the production command source
  for WLC capture sessions.
