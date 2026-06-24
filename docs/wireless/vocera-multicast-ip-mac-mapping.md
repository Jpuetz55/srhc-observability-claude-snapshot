# Vocera Multicast IP to MAC Mapping

IPv4 multicast maps to Ethernet multicast using the lower 23 bits of the IPv4
address. The repo helper is:

```text
tools/vocera_media_qoe/vocera_multicast.py
```

Examples for the configured Vocera pool:

```text
230.230.0.1     -> 01:00:5e:66:00:01
230.230.15.254  -> 01:00:5e:66:0f:fe
```

Use the IP address as the primary identifier. The Ethernet MAC is corroborating
evidence because the IPv4 multicast to MAC mapping is not globally one-to-one.

Supported helper functions:

```text
is_vocera_multicast_ip(ip)
ipv4_multicast_to_mac(ip)
vocera_group_metadata(ip)
is_vocera_multicast_mac(mac)
validate_ip_mac_mapping(ip, mac)
```

Parser output should distinguish:

```text
vocera_dynamic_group_ip
vocera_dynamic_group_mac
vocera_group_evidence_confidence
```

Do not treat a MAC-only match as proof of a specific Vocera group.
