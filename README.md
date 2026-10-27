# Carnival Siri bridge

A personal fork of [EwahOuon/Kia-iOS-Shortcuts](https://github.com/EwahOuon/Kia-iOS-Shortcuts) for Andrew's 2026 Kia Carnival Hybrid. The original MIT license is retained.

Use Siri Shortcuts to request remote start/climate, temperature presets, locks, and unlocks through a U.S. Kia Connect account. Vehicle compatibility must be tested. Powered sliding doors and liftgate commands are not implemented.

## Current status

The bridge provides a local API, tests, and a [Cloud Run deployment guide](docs/cloud-run.md). Cloud deployment, service credentials, vehicle testing, and signed iOS Shortcut imports remain pending. An active Kia Connect plan with the relevant remote features is required.

## Run locally

Use Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

1. Run `uv sync --extra dev`.
2. Copy `.env.example` to `.env` and fill it in locally.
3. Generate a service token with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` and put it in `SECRET_KEY`. Never commit it.
4. Run `uv run --env-file .env python main.py`.
5. Run `uv run --extra dev python -m pytest -q` to test without Kia credentials or vehicle commands.

The local server listens on 127.0.0.1:8080. The health endpoint does not contact Kia. Use HTTPS for any remotely reachable deployment.

## Configuration

- `KIA_USERNAME` is the Kia account username.
- `KIA_PASSWORD` is the Kia account password.
- `KIA_PIN` is the account's remote-command PIN.
- `SECRET_KEY` is a service token of at least 32 characters.
- `VEHICLE_ID` selects a vehicle returned by `GET /list_vehicles`. This is the library's account vehicle ID, not necessarily the VIN. It is required when more than one vehicle is enrolled.
- `KIA_SESSION` optionally restores an enrolled remembered session from Secret Manager. Use the [Cloud Shell verification-code flow](docs/cloud-run.md#kia-verification-codes-and-remembered-sessions) to create it. The runtime refreshes it on first Kia access after startup; an expired or revoked remembered session needs enrollment again.

Set secrets through the host's environment settings. The example file contains empty values only. The app does not load `.env` itself; the local uv command loads it.

## Siri commands

Create a shortcut for each phrase below. These preset temperatures are starting defaults and can be changed in `PRESETS`.

| Shortcut name | Method and path | JSON body |
| - | - | - |
| Start my car | POST /start_climate | {} |
| Start my Kia Carnival | POST /start_climate | {} |
| Warm up my Carnival | POST /start_climate | {"preset":"warm"} |
| Cool down my Carnival | POST /start_climate | {"preset":"cool"} |
| Set my car temperature | POST /start_climate | {"temperature_f":72} |
| Stop my car climate | POST /stop_climate | {} |
| Lock my car | POST /lock_car | {} |
| Unlock my car | POST /unlock_car | {} |

In the iPhone Shortcuts app:

1. Add **Get Contents of URL** with the deployed service URL and the path above.
2. Select **POST**. Set the **Authorization** header to `Bearer YOUR_SERVICE_TOKEN`.
3. Set **Request Body** to **JSON** and add the fields from the table. The empty object uses defaults.
4. For **Set my car temperature**, add **Ask for Input**, select **Number**, and use its output as `temperature_f`.
5. Read the response's `message` field with **Get Dictionary Value**, then use **Speak Text** or **Show Result**. If the response has an `error` field instead, show that error and stop the shortcut.
6. Name the shortcut with the phrase you want Siri to run.

“Start my car” requests Kia remote start with climate. It is not a general engine or driving-control endpoint.

## Climate fields

`POST /start_climate` accepts:

- `preset`: default, warm, cool, or winter.
- `temperature_f`: an integer from 62 to 82 Fahrenheit.
- `duration`: an integer from 1 to 10 minutes.
- `defrost`: a JSON boolean.
- `rear_defrost`: a JSON boolean for the rear window and heated mirrors together.
- `seat_heat`: an integer from 0 to 3 for the two front seats, where 0 is off.
- `seat_ventilation`: an integer from 0 to 3 for the two front seats, where 0 is off.
- `driver_seat_heat`, `passenger_seat_heat`: individual front-seat heat levels from 0 to 3.
- `driver_seat_ventilation`, `passenger_seat_ventilation`: individual front-seat ventilation levels from 0 to 3.

Explicit fields override the preset. Default uses 72 F for 10 minutes with defrost off. Andrew's warm preset uses 80 F, front-seat heat level 3, front defrost, and rear/mirror defrost. His cool preset uses 67 F, front-seat ventilation level 2, and defrost off. Each preset runs for 10 minutes unless a shorter duration is requested. These presets also apply to the existing structured climate routes.

Unknown fields and invalid types are rejected before the app contacts Kia. Temperature changes use the remote-start climate request and may be subject to vehicle state restrictions.

The additional `winter` preset uses 74 F, 10 minutes, front defrost, rear/mirror defrost, and front-seat heat level 3. Explicit fields override it. Shared seat ventilation replaces a preset's shared seat heating. Do not explicitly specify heating and ventilation for the same seat, or shared heating and ventilation together.

Individual seat settings override shared fields and presets for that seat, regardless of field order. Different modes may be used for driver and passenger. For example, `{"preset":"winter","passenger_seat_heat":0}` keeps the driver on high and turns the passenger seat off. If individual settings have no shared setting or preset to supply the other seat, it defaults to off. Preview includes each seat's resolved setting. The pinned U.S. adapter sends all seats when any seat is configured, so omitted seats cannot be assumed to retain their prior setting.

Seat heat maps levels 1, 2, and 3 to low, medium, and high heat in the U.S. library. Ventilation uses the corresponding cooling levels. This SX has no heated steering wheel; the service keeps that setting off. Rear-seat controls are not exposed.

## Natural language commands

`POST /parse_command` previews a command without contacting Kia. `POST /execute_command` parses and validates it, then submits one command. They use the same Authorization header as the existing routes. Send a JSON object with only a `text` field:

```json
{"text":"start my car at 80 degrees with seat warmers at 3 and rear defrost on"}
```

The example resolves to:

```json
{
  "action": "start_climate",
  "parameters": {
    "temperature_f": 80,
    "duration": 10,
    "defrost": false,
    "rear_defrost": true,
    "seat_heat": 3
  }
}
```

This requests high heat on the two front seats, rear-window and mirror defrost, and no steering-wheel heat. Front windshield defrost stays off unless requested.

Additional examples:

- "Please start my Kia Carnival at eighty degrees with seat warmers at three and rear defrost on."
- "Cool down my car with seat ventilation at 2."
- "Start my car at 80 degrees with driver seat warmer at 3 and passenger seat ventilation at 2."
- "Prepare my car for winter with passenger seat off."
- "Warm up my car with front defrost off."
- "Prepare my car for winter."
- "Start my car at 72 degrees for five minutes."
- "Lock my car," "unlock my car," or "stop my car climate."
- "Unlock," "lock," "turn off," or "unlock Sirius."
- "Turn on at 80 degrees with defrost and seat warmers at 2."
- "Tell Sirius to unlock."
- "Tell Sirius to start the car 80 degrees with the seat warmers on two and rear defrost and defrost on."
- "Start the car warm" or "start the car cool."
- "Turn the car on" or "turn the car off."

This parser uses explicit regular-expression rules. It accepts the documented action and setting phrases, including spoken numbers and different setting orders. Short actions use the service's selected vehicle; a vehicle name is optional, and "Sirius" is an alias. Bare "defrost" enables front windshield defrost; "rear defrost" enables rear-window/mirror defrost separately. It rejects unrecognized words, conditions, schedules, conflicting settings, and multiple actions rather than dropping part of a request. It does not call a language model or require a model API key. A command can contain at most 400 characters.

Dictation corrections are context-specific: "Serious" is accepted in a vehicle-name position, "de frost" is accepted in a defrost setting, and "to"/"too" can mean level two only in a seat-level field. This does not enable general fuzzy matching, change temperature numbers, or guess lock versus unlock. Unknown dictation still causes no command.

Andrew selected "cool my seat down" to request remote climate at 67 F for 10 minutes, driver ventilation at level 2, and passenger seat conditioning off. This can start the car's remote climate; seat controls are not a separate seat-only API operation. Parser and validation errors include the same text in `error` and `message`, allowing the spoken-response Shortcut to announce a failed interpretation. Repeat the complete revised instruction; the bridge does not retain a clarification conversation.

For the first Siri integration, create a shortcut named **Car command**:

1. Add **Ask for Input**, select **Text**, and set its prompt to "What should the car do?"
2. Pass that input as `text` to `POST /parse_command` and show the returned `interpreted` action and parameters with **Show Result**. Test this preview before using the execution step.
3. To submit a command, send the original input to `POST /execute_command` instead. Read and speak its `message` field. If the response contains an `error`, speak it and stop.
4. Say "Hey Siri, Car command," then answer its prompt with the full instruction.

Launching the shortcut and supplying its instruction are separate parts of this initial Siri flow. The parser accepts a leading "tell Sirius to", optionally preceded by "Siri," when that text is supplied to the endpoint. This does not register a Siri invocation or cause Siri to forward an arbitrary spoken suffix. For direct fixed commands, use separate personal Shortcuts named "Unlock Sirius" or "Lock Sirius" that send fixed text without asking for input. A native app with App Intents is a separate integration option; its phrase and parameter limits still need testing before promising a single unrestricted sentence.

`GET /capabilities` lists this bridge's implemented controls and the known hardware constraints. It is not a live Kia feature-discovery response. Sliding-door and liftgate requests remain unverified and unavailable; see [the investigation](docs/doors-and-liftgate.md).

## Submission and completion

A command returns HTTP 202 and the Kia command identifier:

```json
{
  "status": "submitted",
  "command": "start_climate",
  "command_id": "identifier-returned-by-kia",
  "message": "Request submitted to Kia. Vehicle completion is not yet confirmed."
}
```

This response means Kia accepted the request. It does not confirm that the doors unlocked or climate started. Do not configure Siri to announce completed vehicle actions from this response. Do not automatically retry an ambiguous error; the previous request may already have reached Kia.

The app refreshes authentication through the community library and reuses the client within each process. It does not persist sessions across restarts or serverless instances. Kia OTP requirements need a dedicated enrollment flow; opening the Kia app is not assumed to authenticate this service.

`GET /auth_status` and `GET /list_vehicles` require the same Authorization header. The original raw-token header is still accepted for existing shortcuts. All vehicle-changing endpoints require POST.

## Development

The app factory accepts a client factory for isolated tests. The test suite uses fake account data and the real library's climate option class. It never contacts a real vehicle.

The first-release scope is in [docs/first-release.md](docs/first-release.md). The inherited Vercel configuration remains in the repo, but no deployment has been created or verified.

