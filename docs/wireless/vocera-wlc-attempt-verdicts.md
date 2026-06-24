# Vocera WLC Attempt Verdicts

Verdicts are deterministic and intentionally cautious.

## `baseline_success`

Operator reported `audio_result=heard`. Evidence remains useful as a known-good
baseline.

## `membership_failure`

Operator reported missed audio and the parsed during-broadcast WLC snapshot
identified the active Vocera group while the C1000 was not in the client list.

## `media_degraded`

Operator reported partial or choppy audio and a valid PCAP container exists.
This is low confidence until RTP or CAPWAP payloads are decoded.

## `inconclusive`

Used when the multicast group is not identified, CLI transcripts are
incomplete, PCAPs are missing or undecodable, AP captures are encrypted, or the
capture point cannot support a stronger claim.

Inconclusive is not a pass and not a failure.

## Current Limitation

The first implementation validates PCAP containers and records metadata. It does
not yet decode CAPWAP or prove WLC forwarding. Any forwarding or RTP quality
claim waits for the CAPWAP/media phase.
