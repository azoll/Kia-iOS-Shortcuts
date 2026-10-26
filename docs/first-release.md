# Carnival Siri commands

## Purpose

Andrew wants Siri to start and prepare his 2026 Kia Carnival Hybrid and control its locks without opening Kia Access. This fork keeps the existing Flask API and Hyundai Kia Connect library. A new app or a Home Assistant installation would add setup that this use case does not need.

## First change

Keep the upstream command paths. Allow the climate request to carry a Fahrenheit temperature, a warm or cool preset, a duration, and a defrost flag. Require authentication for account and command routes. Select a configured vehicle or the sole vehicle on the account. Report submission separately from completion.

## Acceptance criteria

- An unauthenticated request never reaches the Kia client.
- A valid climate request sends the selected Fahrenheit temperature and duration to the library.
- Warm and cool presets work, and explicit fields override preset values.
- Invalid JSON or unsupported options do not reach the Kia client.
- A multi-vehicle account requires an explicit vehicle identifier.
- Lock, unlock, climate start, and climate stop return HTTP 202 with a command identifier after submission.
- An upstream authentication or service error returns a useful message without upstream error details or credentials.
- Local tests use an injected client and do not send commands to a real vehicle.

## Deferred

Vehicle confirmation, Kia OTP enrollment and durable session storage, deployment, importing signed iOS Shortcut files, powered doors, liftgate operation, and driving assistance belong in later changes. A successful local test does not establish Carnival compatibility.
