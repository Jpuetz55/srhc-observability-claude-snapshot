# Vocera iperf Laptop Role Scripts v5

This bundle is for the current two-laptop test plan.

It does **not** use Windows Scheduled Tasks.  
Each laptop runs indefinitely after you start it, and stops when you run the stop script.

## Environment

```text
Server VM: 10.205.0.20
Laptop A:  S-NW-PROBE1
Laptop B:  S-NW-PROBE2
SSID:      srhcvoice2
Collector: collectors01
Collector user: appsadmin
Upload path: /var/lib/vocera-iperf-qoe/incoming
```

## What each laptop does

### Laptop A: S-NW-PROBE1

Laptop A runs:

```text
client -> server
S-NW-PROBE1 -> 10.205.0.20:5201
```

It uses normal iperf3 client mode:

```text
iperf3 -c 10.205.0.20 -u ...
```

Laptop A also starts an iperf3 peer receiver on port `5203` so Laptop B can test to it:

```text
S-NW-PROBE2 -> S-NW-PROBE1:5203
```

### Laptop B: S-NW-PROBE2

Laptop B runs:

```text
client -> client
S-NW-PROBE2 -> S-NW-PROBE1:5203
```

## Traffic profile

Default test profile:

```text
UDP bitrate:       64K
Payload size:      160 bytes
Duration:          60 seconds
Interval:          every 5 minutes
DSCP/TOS:          0xb8
SSID metadata:     srhcvoice2
```

These are synthetic voice-like UDP tests. They are not actual Vocera RTP, but they give repeatable jitter/loss data for the wireless path.

---

# 1. Server VM setup

Run on the Linux server VM at `10.205.0.20`.

If you already created `iperf3-5201.service`, just verify it:

```bash
sudo systemctl status iperf3-5201.service
ss -lntup | grep 5201
```

If not, use the bundled script:

```bash
chmod +x ./linux/setup-iperf3-server.sh
sudo ./linux/setup-iperf3-server.sh
```

Control it:

```bash
sudo ./linux/control-iperf3-server.sh start
sudo ./linux/control-iperf3-server.sh stop
sudo ./linux/control-iperf3-server.sh status
```

---

# 2. Collector setup

Run on `collectors01`.

```bash
chmod +x ./collector/setup-vocera-iperf-scp-ingest.sh
sudo ./collector/setup-vocera-iperf-scp-ingest.sh
```

Manual equivalent:

```bash
sudo mkdir -p /var/lib/vocera-iperf-qoe/incoming
sudo mkdir -p /var/lib/vocera-iperf-qoe/processed
sudo mkdir -p /var/lib/vocera-iperf-qoe/logs

sudo chown -R appsadmin:appsadmin /var/lib/vocera-iperf-qoe

sudo chmod 0750 /var/lib/vocera-iperf-qoe
sudo chmod 0770 /var/lib/vocera-iperf-qoe/incoming
sudo chmod 0770 /var/lib/vocera-iperf-qoe/processed
sudo chmod 0770 /var/lib/vocera-iperf-qoe/logs
```

---

# 3. Install scripts on both laptops

Do this on both:

```text
S-NW-PROBE1
S-NW-PROBE2
```

Extract this ZIP, then from the extracted folder run:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\Install-LocalVoceraIperfScripts.ps1 `
  -IperfSourceDir "C:\Users\jpuetz\Downloads\iperf3.1.4_64"
```

That copies scripts to:

```text
C:\VoceraIperf\windows
```

and copies iperf3 plus its DLLs to:

```text
C:\Tools\iperf3
```

Verify on both laptops:

```powershell
Test-Path "C:\VoceraIperf\windows\Setup-LaptopA-ClientToServerAndPeerReceiver.ps1"
Test-Path "C:\VoceraIperf\windows\Setup-LaptopB-ClientToClientTester.ps1"
Test-Path "C:\Tools\iperf3\iperf3.exe"

& "C:\Tools\iperf3\iperf3.exe" --version
```

All `Test-Path` commands should return `True`.

---

# 4. Create an SSH upload key on each laptop

Do this on both S-NW-PROBE1 and S-NW-PROBE2.

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\New-VoceraIperfUploadKey.ps1"
```

That creates:

```text
C:\Users\jpuetz\.ssh\vocera_iperf_ed25519
C:\Users\jpuetz\.ssh\vocera_iperf_ed25519.pub
```

Show the public key:

```powershell
Get-Content "$env:USERPROFILE\.ssh\vocera_iperf_ed25519.pub"
```

Copy the full public key line from each laptop.

On `collectors01`, add both public keys to:

```bash
/home/appsadmin/.ssh/authorized_keys
```

Then fix permissions on `collectors01`:

```bash
chmod 700 /home/appsadmin/.ssh
chmod 600 /home/appsadmin/.ssh/authorized_keys
chown -R appsadmin:appsadmin /home/appsadmin/.ssh
```

Test from each laptop:

```powershell
ssh -i "$env:USERPROFILE\.ssh\vocera_iperf_ed25519" appsadmin@collectors01 "hostname && whoami"
```

Expected:

```text
collectors01.srhc.net
appsadmin
```

You can also run:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Test-CollectorScpUpload.ps1"
```

---

# 5. Configure and start Laptop A: S-NW-PROBE1

Run on **S-NW-PROBE1**:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Setup-LaptopA-ClientToServerAndPeerReceiver.ps1" `
  -ServerIP "10.205.0.20" `
  -SSID "srhcvoice2" `
  -IntervalMinutes 5 `
  -LatencyProbeCount 5 `
  -LatencyProbeTimeoutMilliseconds 1000 `
  -SSHKeyPath "$env:USERPROFILE\.ssh\vocera_iperf_ed25519"
```

If Windows Firewall rules fail because PowerShell was not elevated, run this as Administrator on S-NW-PROBE1:

```powershell
New-NetFirewallRule -DisplayName "Vocera iperf3 peer TCP 5203" -Direction Inbound -Protocol TCP -LocalPort 5203 -Action Allow
New-NetFirewallRule -DisplayName "Vocera iperf3 peer UDP 5203" -Direction Inbound -Protocol UDP -LocalPort 5203 -Action Allow
```

Start Laptop A:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Start-VoceraIperfRole.ps1"
```

Check status:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Get-VoceraIperfRoleStatus.ps1"
```

Verify Laptop A is listening for Laptop B:

```powershell
netstat -ano | findstr ":5203"
```

Get Laptop A's Wi-Fi IP:

```powershell
Get-NetIPConfiguration |
  Where-Object { $_.InterfaceAlias -match "Wi-Fi|Wireless|WLAN" } |
  Select-Object InterfaceAlias,IPv4Address
```

You need this IP for Laptop B.

---

# 6. Configure and start Laptop B: S-NW-PROBE2

Run on **S-NW-PROBE2**.

Replace `<S-NW-PROBE1-WIRELESS-IP>` with the Wi-Fi IP from Laptop A.

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Setup-LaptopB-ClientToClientTester.ps1" `
  -PeerIP "<S-NW-PROBE1-WIRELESS-IP>" `
  -SSID "srhcvoice2" `
  -IntervalMinutes 5 `
  -LatencyProbeCount 5 `
  -LatencyProbeTimeoutMilliseconds 1000 `
  -SSHKeyPath "$env:USERPROFILE\.ssh\vocera_iperf_ed25519"
```

Example:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Setup-LaptopB-ClientToClientTester.ps1" `
  -PeerIP "10.16.76.200" `
  -SSID "srhcvoice2" `
  -IntervalMinutes 5 `
  -LatencyProbeCount 5 `
  -LatencyProbeTimeoutMilliseconds 1000 `
  -SSHKeyPath "$env:USERPROFILE\.ssh\vocera_iperf_ed25519"
```

Start Laptop B:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Start-VoceraIperfRole.ps1"
```

Check status:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Get-VoceraIperfRoleStatus.ps1"
```

---

# 7. Stop either laptop

Run on the laptop you want to stop:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Stop-VoceraIperfRole.ps1"
```

The stop script:

```text
1. Creates a stop flag for the loop.
2. Stops the loop process.
3. Stops the Laptop A peer receiver if present.
4. Stops any remaining iperf3.exe processes if needed.
```

---

# 8. Verify uploads on collectors01

On `collectors01`:

```bash
find /var/lib/vocera-iperf-qoe/incoming -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n' | sort | tail -50
```

Check each laptop:

```bash
find /var/lib/vocera-iperf-qoe/incoming/S-NW-PROBE1 -type f -ls
find /var/lib/vocera-iperf-qoe/incoming/S-NW-PROBE2 -type f -ls
```

View latest metadata:

```bash
for f in $(find /var/lib/vocera-iperf-qoe/incoming -name '*.json' | sort | tail -5); do
  echo "===== $f ====="
  jq '.metadata' "$f"
done
```

Expected metadata:

```text
S-NW-PROBE1:
  direction = client_to_server
  ssid      = srhcvoice2
  target    = 10.205.0.20
  raw_latency_ms = <ICMP RTT average to server VM>

S-NW-PROBE2:
  direction = client_to_client
  ssid      = srhcvoice2
  target    = <S-NW-PROBE1-WIRELESS-IP>
  raw_latency_ms = <ICMP RTT average to Laptop A>
```

`raw_latency_ms` is measured immediately before each iperf run. The runner uses
ICMP ping first; if ICMP is blocked, it falls back to TCP connect latency against
the target iperf port. If both methods fail, the field is null and
`latency_probe_error` explains the probe failure; iperf still runs and uploads
normally.

---

# 9. Local file locations

Each laptop writes local files here:

```text
C:\iperf-vocera-tests\<DEVICE>\raw
C:\iperf-vocera-tests\<DEVICE>\logs
C:\iperf-vocera-tests\<DEVICE>\state
```

Role config is here:

```text
C:\VoceraIperf\config\role.json
```

---

# 10. Troubleshooting

## Missing iperf DLLs

If iperf fails with:

```text
-1073741515
```

then only `iperf3.exe` was copied without the DLLs.

Fix:

```powershell
Copy-Item "C:\Users\jpuetz\Downloads\iperf3.1.4_64\*" "C:\Tools\iperf3\" -Recurse -Force
Get-ChildItem "C:\Tools\iperf3" -Recurse | Unblock-File
```

## SSH key missing

If setup fails with:

```text
SSHKeyPath not found
```

create the key:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\New-VoceraIperfUploadKey.ps1"
```

Then add the `.pub` key to `collectors01`.

## SCP upload denied

On `collectors01`:

```bash
sudo chown -R appsadmin:appsadmin /var/lib/vocera-iperf-qoe
sudo chmod 0770 /var/lib/vocera-iperf-qoe/incoming
```

## Laptop B cannot reach Laptop A

On Laptop A:

```powershell
netstat -ano | findstr ":5203"
```

On Laptop B:

```powershell
Test-NetConnection <S-NW-PROBE1-WIRELESS-IP> -Port 5203
```

If blocked, create inbound firewall rules on Laptop A for TCP/UDP 5203.


---

# v5 fix notes

v5 fixes the Windows PowerShell `ssh-keygen -N ""` issue where Windows PowerShell may drop the empty argument and produce:

```text
option requires an argument -- N
```

The upload key script now passes the empty passphrase argument in a Windows PowerShell-compatible way and checks the ssh-keygen exit code before claiming success.
