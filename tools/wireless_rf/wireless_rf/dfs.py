"""DFS channel classification helpers used by RF parsing and dashboards."""

from __future__ import annotations

# United States 5 GHz DFS channels commonly relevant to Cisco enterprise WLANs.
# This helper is intentionally conservative and used for reporting, not for
# regulatory enforcement. Validate the regulatory domain on the controller.
DFS_5GHZ_CHANNELS = {
    52, 56, 60, 64,
    100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144,
}
NON_DFS_5GHZ_CHANNELS = {36, 40, 44, 48, 149, 153, 157, 161, 165}


def is_dfs_channel(channel: int | None) -> bool:
    """Return True when a channel is in the local DFS reporting set."""

    if channel is None:
        return False
    return int(channel) in DFS_5GHZ_CHANNELS


def channel_family(channel: int | None) -> str:
    """Return a human-readable 5 GHz channel family bucket."""

    if channel is None:
        return "unknown"
    channel = int(channel)
    if channel in {36, 40, 44, 48}:
        return "UNII-1 non-DFS"
    if channel in {52, 56, 60, 64}:
        return "UNII-2 DFS"
    if 100 <= channel <= 144:
        return "UNII-2e DFS"
    if channel in {149, 153, 157, 161, 165}:
        return "UNII-3 non-DFS"
    return "other"
