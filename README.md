# U-Prox Cloud for Home Assistant

A custom Home Assistant integration for monitoring U-Prox Cloud hubs and their connected devices.

> **Status: early development.** U-Prox has not published the cloud API used here. This integration is based on observed portal traffic, so cloud-side changes may require updates.

## Features

- Sign in to U-Prox Cloud and choose a hub.
- Stream hub and accessory updates over the cloud WebSocket session.
- Expose hub online, mains power, tamper, SIM, and Wi-Fi status.
- Expose hub battery and available cellular/Wi-Fi signal measurements.
- Expose accessory state, temperature, battery, and signal measurements when provided by the panel.
- Optionally record redacted incoming and outgoing WebSocket messages for troubleshooting.

The integration is read-only: it opens a panel `Setup` session and sends the session keepalive, but does not issue arm/disarm, relay, or configuration-change commands.

## Installation

### HACS

1. In HACS, open **Integrations** and select **Custom repositories** from the menu.
2. Add this repository's GitHub URL and choose **Integration** as the category.
3. Install **U-Prox Cloud** and restart Home Assistant.

### Manual

Copy `custom_components/u-prox` into the `custom_components` directory under your Home Assistant configuration directory, then restart Home Assistant.

## Configuration

1. In Home Assistant, open **Settings > Devices & services > Add integration**.
2. Search for **U-Prox Cloud**.
3. Enter the cloud account email and password.
4. Select the hub to add.

Home Assistant stores the credentials in the config entry. The integration sends the lowercase MD5 password digest observed in the portal's HTTPS login request and uses the returned authorization token for the panel API and WebSocket session.

## Entities

Each configured hub has diagnostic entities for:

- Online, mains power, tamper, SIM 1/2, and Wi-Fi connection status.
- Hub battery and cellular/Wi-Fi signal levels when available.

Reported sensors expose state, temperature (when available), battery percentage, and signal strength in dBm. Key fobs expose state, battery, and signal. Other component types are currently represented by diagnostic state entities. Component updates are matched by serial or index to avoid assigning one accessory's measurements to another.

## Message logging

The **WebSocket message logging** switch is attached to the hub and is off by default. Turning it on also records a redacted snapshot of the current panel state. Subsequent incoming and outgoing WebSocket application messages are written as JSON Lines to:

```text
custom_components/u-prox/websocket_messages.jsonl
```

The file rotates at 4 MiB, retaining one `.1` backup. Passwords, tokens, PINs, contact details, and other sensitive fields are redacted. Names and serials are replaced with consistent pseudonyms so messages remain correlatable. HTTP login and panel-list traffic, including authorization headers, is not logged. The log is excluded from Git; review it before sharing regardless.

## Security and limitations

- The cloud API is undocumented and may change without notice.
- The decoded JWT expiry is used only to schedule a refresh before expiration; the integration does not treat the decoded payload as signature verification.
- The cloud account must have permission to open a panel setup session.
- Avoid sharing credentials, authorization tokens, or unredacted panel logs.

## Troubleshooting

Enable **WebSocket message logging** temporarily, reproduce the issue, turn logging off, then inspect the JSONL file. Share only the relevant redacted records. Do not post the raw authorization token, login hash, PINs, contact details, or network credentials.