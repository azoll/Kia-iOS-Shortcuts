# Sliding door and liftgate investigation

## Current finding

The 2026 Carnival Hybrid has physical power-door controls, but a working U.S. Kia Connect cloud command for opening or closing the sliding doors or liftgate has not been established. These actions are not exposed by this bridge. Natural language requests for them are rejected before Kia authentication or a vehicle command.

## Evidence checked

- The installed `hyundai-kia-connect-api` 4.41.1 `VehicleManager` and `KiaUvoApiUSA` classes have no sliding-door, liftgate, tailgate, or trunk actuation methods.
- The U.S. implementation reads door and trunk open/closed indicators. A status field is not a control command.
- Kia's [2026 Carnival Hybrid power sliding door guide](https://www.kiaffg.com/2026/carnivalhev/power-sliding-doors.html) documents the physical buttons and smart key.
- Kia's [2026 Carnival Hybrid power liftgate guide](https://www.kiaffg.com/2026/carnivalhev/power-liftgate) documents the physical buttons and smart key.
- Public source and documentation searches did not establish a working U.S. cloud endpoint. This does not prove that none exists.

## Next verification step

Inspect the controls actually offered for Andrew's enrolled vehicle in the U.S. Kia Access app or owner portal. If a control exists, inspect its normal authenticated request, add the corresponding U.S. implementation, and test with the vehicle parked and the opening in view. Account access and live vehicle testing have not occurred in this project.

Do not substitute generic unlock for opening a sliding door, copy an overseas endpoint into the U.S. client, or report success from a guessed URL. The Siri integration and parser can route these actions once a working control is established.

## Hardware profile

Andrew's vehicle is a U.S. 2026 Carnival Hybrid SX. Kia's [2026 HEV equipment chart](https://www.kiamedia.com/us/en/models/carnival-hev/2026/features) lists heated mirrors and heated/ventilated front seats as standard. Andrew confirmed no heated steering wheel. The [2026 Hybrid feature guide](https://dealervideos.kia.com/ffg/ka13/2026/2026_carnival_hev_ffg.pdf) states that mirror heaters operate with rear-window defrost. Remote acceptance of accessory settings remains subject to vehicle testing.
