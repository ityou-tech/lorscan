# Run lorscan on a Mac (autostart)

Best for: an always-on Mac (Mac mini, an old laptop on the shelf) that you and other people on your home network will hit from a browser.

If you'd rather run it on a NAS or other Linux/Windows host, see `docker-compose.yml` at the repo root.

## What you'll get

- `http://localhost:8000` from the host Mac
- `http://<your-mac-name>.local:8000` from any other device on the LAN (Bonjour)
- A LaunchAgent that brings lorscan back up after reboots and crashes
- Logs at `~/Library/Logs/lorscan.{out,err}.log`

## Prereqs

1. **macOS 13+** on Apple Silicon (M1/M2/M3/M4). Intel Macs work but skip the GPU acceleration — scans will be ~10× slower.
2. **uv** installed:
   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. The repo cloned somewhere stable (don't put it under `~/Downloads` or anywhere you might delete by accident — the LaunchAgent points at this path).

## Install

From the repo root:

```sh
./deploy/macmini/install.sh
```

That single command:

1. `uv sync` — installs the Python deps into `.venv/`
2. `lorscan sync-catalog` — pulls the card list from lorcanajson.org (~30 s)
3. `lorscan index-images` — downloads every card image and builds embeddings (~3–8 min on Apple Silicon, way longer on Intel)
4. Writes `~/Library/LaunchAgents/tech.ityou.lorscan.plist` and loads it
5. Prints the local + network URLs

Re-run anytime; it's idempotent. Pass `--no-data` to skip steps 2–3 if you've already bootstrapped.

## Make it actually always-on

The LaunchAgent restarts lorscan if it crashes, but macOS will still put the whole Mac to sleep by default. For a server role you want:

### 1. Disable system sleep

System Settings → **Energy** (Mac mini) or **Battery** (laptops):

- "Prevent automatic sleeping when display is off" — **on**
- "Wake for network access" — **on** (so the Mac responds to the first request from a sleeping state)

Or via CLI (requires sudo):

```sh
sudo pmset -a sleep 0
sudo pmset -a womp 1   # wake on network
```

### 2. Auto-login

LaunchAgents only run once the user logs in. After a power blip or reboot, lorscan stays down until someone logs in unless the Mac auto-logs-in.

System Settings → **Users & Groups** → **Automatically log in as** → pick your user.

> If FileVault is on, macOS won't let you enable auto-login. Either turn off FileVault (this Mac is going to be physically inside your house and never travel) or convert this to a LaunchDaemon — see "Alternative: LaunchDaemon" below.

### 3. Firewall

If macOS Application Firewall is on, the first incoming request will pop a "Allow incoming network connections" prompt. Click **Allow**. To pre-approve from the CLI:

```sh
sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
    --add "$(command -v uv)" \
    --unblockapp "$(command -v uv)"
```

## Day-to-day

| Action | Command |
|---|---|
| Status | `launchctl print gui/$(id -u)/tech.ityou.lorscan \| head` |
| Stop | `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/tech.ityou.lorscan.plist` |
| Start | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/tech.ityou.lorscan.plist` |
| Restart | `launchctl kickstart -k gui/$(id -u)/tech.ityou.lorscan` |
| Tail logs | `tail -f ~/Library/Logs/lorscan.out.log ~/Library/Logs/lorscan.err.log` |
| Update code | `git pull && uv sync && launchctl kickstart -k gui/$(id -u)/tech.ityou.lorscan` |
| Refresh catalog | `uv run lorscan sync-catalog && uv run lorscan index-images` (after a new chapter releases) |

## Sharing with people on your network

LAN: anyone on the same Wi-Fi can hit `http://<your-mac-name>.local:8000`. Find `<your-mac-name>` with:

```sh
scutil --get LocalHostName
```

(Default is the name you set during macOS setup, with spaces replaced by dashes.)

Windows users on the LAN need Bonjour installed (it ships with iTunes, or via the standalone "Bonjour Print Services for Windows"). Otherwise they need to use the Mac's IP directly: `ipconfig getifaddr en0`.

## Remote access (optional)

If you want it reachable from outside your home, **don't port-forward** — lorscan has no auth. Use Tailscale or Cloudflare Tunnel instead.

The lazy choice is Tailscale: install on the host Mac and on each device, and the same `http://<your-mac-name>:8000` URL works from anywhere. No firewall changes, end-to-end encrypted, free for personal use.

## Alternative: LaunchDaemon (no auto-login required)

A LaunchDaemon runs at boot before any user logs in, so it survives power events without auto-login. The trade-off is a bit more setup (sudo, explicit `UserName` key so `~/.lorscan` resolves to your user, plist lives in `/Library/LaunchDaemons/`). If FileVault is preventing auto-login this is the right path; otherwise the LaunchAgent above is simpler.

Sketch:

```sh
sudo cp deploy/macmini/tech.ityou.lorscan.plist.template /Library/LaunchDaemons/tech.ityou.lorscan.plist
# Edit it: substitute __UV_PATH__/__REPO_PATH__/__LOG_PATH__ as install.sh does,
# and add a <key>UserName</key><string>YOUR_USER</string> dict entry.
sudo launchctl bootstrap system /Library/LaunchDaemons/tech.ityou.lorscan.plist
```

I haven't automated this path because most home setups don't need it.

## Troubleshooting

- **`launchctl print` shows last exit reason: SIGKILL / OOM** — only happens on Macs with very low RAM. Close other apps or upgrade.
- **Server doesn't restart after reboot** — auto-login isn't enabled, or FileVault is blocking it. See above.
- **Bonjour name doesn't resolve** — your router may be filtering mDNS between SSIDs (common on guest networks). Use the IP address as a fallback.
- **First scan is slow** — the CLIP model loads lazily on the first request (~5 s on Apple Silicon). Subsequent scans are fast.
