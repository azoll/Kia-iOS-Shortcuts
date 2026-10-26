# Natural language climate commands

## Goal

Andrew wants to speak a complete request such as "start my car at 80 degrees with seat warmers at 3 and rear defrost on" and have the service submit the corresponding command to his 2026 Kia Carnival Hybrid SX.

## Scope

Extend the current Flask bridge with front-seat heating and ventilation, rear-window and mirror defrost, and a winter preset. Add a deterministic natural language parser with preview and execution endpoints. Retain the existing structured command routes. A constrained parser avoids a new model dependency for a small command set and rejects text it cannot interpret completely.

The SX has heated and ventilated front seats and heated mirrors. Andrew confirmed that his vehicle does not have a heated steering wheel. Do not enable steering-wheel heat or expose rear-seat heater settings.

## Acceptance criteria

- The example sentence produces an 80 F climate request, front-seat heat level 3, and rear/mirror defrost enabled.
- Seat levels 1, 2, and 3 map to the U.S. library's low, medium, and high values. Level 0 turns the front-seat controls off.
- Front-seat heating and ventilation cannot be requested together.
- A preview parses and validates the complete command without initializing the Kia client.
- Execution submits exactly one supported command after validation.
- Unknown words, conflicting settings, malformed input, unsupported hardware, and unverified door/liftgate commands cause no Kia client call.
- Lock, unlock, climate stop, presets, spoken numbers, temperature, duration, and defrost variations have focused tests.
- The example is checked against the actual U.S. library's generated request body with the network transport replaced by a test double.

## Siri input

The initial Shortcut uses Ask for Input to collect the full instruction after Siri launches the named shortcut. Do not claim that an arbitrary suffix after a shortcut's name is passed automatically. A single uninterrupted Siri utterance is a later iOS integration task.

## Vehicle verification

Local tests and source inspection do not establish that the Carnival accepts a cloud command. Live Kia account enrollment, credentials, and vehicle testing remain separate work. Door and liftgate controls must remain unavailable until a U.S. command is verified.
