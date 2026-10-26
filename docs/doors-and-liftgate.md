# Sliding door and liftgate investigation

## Current finding

The 2026 Carnival Hybrid has physical power-door controls, but a working U.S. Kia Connect cloud command for opening or closing the sliding doors or liftgate has not been established. These actions are not exposed by this bridge. Natural language requests for them are rejected before Kia authentication or a vehicle command.

## Evidence checked

- The installed `hyundai-kia-connect-api` 4.41.1 `VehicleManager` and `KiaUvoApiUSA` classes have no sliding-door, liftgate, tailgate, or trunk actuation methods.
- The U.S. implementation reads door and trunk open/closed indicators. A status field is not a control command.
- Kia's [2026 Carnival Hybrid power sliding door guide](https://www.kiaffg.com/2026/carnivalhev/power-sliding-doors.html) documents the physical buttons and smart key.
- Kia's [2026 Carnival Hybrid power liftgate guide](https://www.kiaffg.com/2026/carnivalhev/power-liftgate) documents the physical buttons and smart key.
- Public source and documentation searches did not establish a working U.S. cloud endpoint. This does not prove that none exists.

## Owner portal inspection, 2026-10-26

Andrew signed into the U.S. owner portal. Read-only inspection of the enrolled vehicle's dashboard and Vehicle Status panel showed cached door and trunk open/closed indicators. No sliding-door or liftgate open/close controls were visible in the inspected views. The displayed status timestamp was from the previous day; it was not a live observation of the vehicle.

This does not establish whether the Kia Access mobile app has additional controls or whether an undocumented endpoint exists. Andrew was actively driving, so no status refresh, remote vehicle command, or actuation test was performed.

## Mobile app screenshot

After parking, Andrew supplied a screenshot of the app's Remote Commands screen. It shows Start Engine, Stop Engine, Lock, Unlock, SVM 360, Valet Alerts ON/OFF, Valet Mode ON/OFF, and Horn & Lights. No sliding-door or liftgate open/close control appears on this screen.

This establishes the visible app options, not successful vehicle execution or working API endpoints for the additional security features. No command was executed as part of reviewing the screenshot.

## Next verification step

Inspect the app's climate settings for temperature, front-seat heat, and rear defrost. Configure hosting and credentials securely, then test supported commands with the vehicle parked. Door and liftgate cloud actuation remains unverified. If an app control is subsequently found, inspect its normal authenticated request before adding an implementation. Deployment and live command testing remain pending.

Do not substitute generic unlock for opening a sliding door, copy an overseas endpoint into the U.S. client, or report success from a guessed URL. The Siri integration and parser can route these actions once a working control is established.

## Hardware profile

Andrew's vehicle is a U.S. 2026 Carnival Hybrid SX. Kia's [2026 HEV equipment chart](https://www.kiamedia.com/us/en/models/carnival-hev/2026/features) lists heated mirrors and heated/ventilated front seats as standard. Andrew confirmed no heated steering wheel. The [2026 Hybrid feature guide](https://dealervideos.kia.com/ffg/ka13/2026/2026_carnival_hev_ffg.pdf) states that mirror heaters operate with rear-window defrost. Remote acceptance of accessory settings remains subject to vehicle testing.
