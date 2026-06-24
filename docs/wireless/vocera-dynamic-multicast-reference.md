# Vocera Dynamic Multicast Reference

Vocera broadcast sessions use a dynamic multicast group. For this study the
authoritative detection range is:

```text
230.230.0.0/20
first usable: 230.230.0.1
last usable: 230.230.15.254
```

This range is stored in `config/vocera-media-qoe.yaml` under:

```yaml
vocera_multicast:
  ipv4_pool:
    cidr: 230.230.0.0/20
```

The WLC capture workflow uses this pool for the temporary EPC ACL, and the
evidence parser uses it to identify dynamic Vocera groups in WLC transcripts.

Evidence ranking:

```text
Exact dynamic multicast IPv4 match: highest confidence
IP plus correctly derived Ethernet multicast MAC: high confidence
MAC-only match: supporting evidence only
Badge unicast MAC match: identity/control evidence only
```

Native multicast traffic uses the multicast destination MAC, not the C1000
unicast MAC. A C1000 inner-MAC filter is useful for client/control context but
is not sufficient to prove native multicast delivery.

Cisco's Vocera/WLC flow describes badges joining the assigned multicast group,
WLC group membership tracking, and WLC/AP forwarding as the relevant evidence
chain:

https://www.cisco.com/c/en/us/support/docs/wireless/catalyst-9800-series-wireless-controllers/225171-understand-vocera-broadcast-on-wlc-9800.html
