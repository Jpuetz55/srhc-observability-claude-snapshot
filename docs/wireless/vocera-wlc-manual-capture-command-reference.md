# Vocera WLC Manual Capture Command Reference

The repo generates these command sheets with attempt-specific MACs and VLANs.
Operators must verify placeholder syntax with WLC `?` help before starting EPC.

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

The generated EPC sheets include placeholders for interface and export
destination because exact syntax must be validated on the target WLC.

The workflow is:

```text
show monitor capture <SESSION>
monitor capture <SESSION> interface <WLC_UPLINK_INTERFACE> both
monitor capture <SESSION> buffer circular size 50
monitor capture <SESSION> match ipv4
monitor capture <SESSION> inner mac <V5000_MAC> <C1000_MAC>
monitor capture <SESSION> start
...
monitor capture <SESSION> stop
show monitor capture <SESSION>
monitor capture <SESSION> export <APPROVED_TRANSFER_DESTINATION>
no monitor capture <SESSION>
```
