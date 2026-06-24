# Quickstart

Use this if you already have:

- Server VM iperf3 running at `10.205.0.20`
- Collector directories created on `collectors01`
- SSH upload keys added to `/home/appsadmin/.ssh/authorized_keys`

## S-NW-PROBE1

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Setup-LaptopA-ClientToServerAndPeerReceiver.ps1" `
  -ServerIP "10.205.0.20" `
  -SSID "srhcvoice2" `
  -IntervalMinutes 5 `
  -LatencyProbeCount 5 `
  -LatencyProbeTimeoutMilliseconds 1000 `
  -SSHKeyPath "$env:USERPROFILE\.ssh\vocera_iperf_ed25519"

powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Start-VoceraIperfRole.ps1"
```

Get the Wi-Fi IP:

```powershell
Get-NetIPConfiguration |
  Where-Object { $_.InterfaceAlias -match "Wi-Fi|Wireless|WLAN" } |
  Select-Object InterfaceAlias,IPv4Address
```

## S-NW-PROBE2

Replace `<S-NW-PROBE1-WIRELESS-IP>`.

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Setup-LaptopB-ClientToClientTester.ps1" `
  -PeerIP "<S-NW-PROBE1-WIRELESS-IP>" `
  -SSID "srhcvoice2" `
  -IntervalMinutes 5 `
  -LatencyProbeCount 5 `
  -LatencyProbeTimeoutMilliseconds 1000 `
  -SSHKeyPath "$env:USERPROFILE\.ssh\vocera_iperf_ed25519"

powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Start-VoceraIperfRole.ps1"
```

## Status

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Get-VoceraIperfRoleStatus.ps1"
```

## Stop

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Stop-VoceraIperfRole.ps1"
```
