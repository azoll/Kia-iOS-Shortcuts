"""Parse a bounded set of car instructions without executing any commands."""

import re


class CommandParseError(Exception):
    """The instruction cannot be fully interpreted as one supported command."""


CAR = r"(?:(?:my|the)\s+)?(?:kia\s+carnival|kia|carnival|car|van|sirius)"
ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
LEVELS = {"off": 0, "low": 1, "medium": 2, "high": 3}
LEVEL = r"(?P<value>\d+|off|low|medium|high)"

# The first matching action must begin the instruction. Nothing is executed here.
ACTIONS = [
    (rf"(?:prepare|warm up)\s+{CAR}\s+for winter\b", "start_climate", {"preset": "winter"}),
    (rf"(?:remote start|start|turn on)(?:\s+{CAR})?(?:\s+climate)?\b", "start_climate", {}),
    (rf"(?:warm up|warm|heat|preheat)(?:\s+{CAR})?\b", "start_climate", {"preset": "warm"}),
    (rf"(?:cool down|cool|precool)(?:\s+{CAR})?\b", "start_climate", {"preset": "cool"}),
    (rf"set(?:\s+{CAR}(?:'s)?)?\s+(?:temperature|climate)\b", "start_climate", {}),
    (rf"(?:stop|turn off)(?:\s+{CAR}(?:'s)?)?(?:\s+(?:climate|engine))?\b", "stop_climate", {}),
    (rf"lock(?:\s+{CAR}(?:'s)?)?(?:\s+(?:the\s+)?doors)?\b", "lock", {}),
    (rf"unlock(?:\s+{CAR}(?:'s)?)?(?:\s+(?:the\s+)?doors)?\b", "unlock", {}),
]

SEAT_HEAT = r"(?:(?:both\s+)?front\s+|both\s+)?(?:seat warmers?|seat heaters?|heated seats?|seat heat)"
SEAT_VENT = r"(?:(?:both\s+)?front\s+|both\s+)?(?:seat ventilation|ventilated seats?|seat cooling|seat coolers?)"
REAR = r"(?:rear|back)(?:\s+(?:window|windshield))?\s+(?:defrost|defroster|defogger)"
FRONT = r"(?:(?:front(?:\s+windshield)?|windshield)\s+)?(?:defrost|defroster|defogger)"
CLAUSES = []
for seat in ("driver", "passenger"):
    for mode, pattern in (("seat_heat", SEAT_HEAT), ("seat_ventilation", SEAT_VENT)):
        CLAUSES.append((rf"{seat}(?:'s)?\s+{pattern}(?:\s+(?:at|to|on))?(?:\s+level)?\s+{LEVEL}\b",
                        f"{seat}_{mode}", "level"))
    CLAUSES.append((rf"{seat}(?:'s)?\s+seat\s+(?P<value>off)\b", f"{seat}_seat_heat", "level"))
CLAUSES += [
    (rf"{SEAT_HEAT}(?:\s+(?:at|to|on))?(?:\s+level)?\s+{LEVEL}\b", "seat_heat", "level"),
    (rf"{SEAT_VENT}(?:\s+(?:at|to|on))?(?:\s+level)?\s+{LEVEL}\b", "seat_ventilation", "level"),
    (rf"(?:turn\s+)?(?P<value>on|off)\s+(?:the\s+)?{REAR}\b", "rear_defrost", "bool"),
    (rf"(?:turn\s+)?(?:the\s+)?{REAR}\s+(?P<value>on|off)\b", "rear_defrost", "bool"),
    (rf"(?:turn\s+)?(?P<value>on|off)\s+(?:the\s+)?{FRONT}\b", "defrost", "bool"),
    (rf"(?:turn\s+)?(?:the\s+)?{FRONT}\s+(?P<value>on|off)\b", "defrost", "bool"),
    (rf"(?P<value>{REAR})\b", "rear_defrost", "true"),
    (rf"(?P<value>{FRONT})\b", "defrost", "true"),
    (r"(?:for\s+)?(?P<value>\d+)\s+minutes?\b", "duration", "int"),
    (r"(?:(?:at|to|temperature(?:\s+(?:at|to))?)\s+)?(?P<value>\d+)\s*(?:degrees?(?:\s+fahrenheit)?|°\s*f?|fahrenheit|f)\b", "temperature_f", "int"),
    (r"(?:at|to|temperature(?:\s+(?:at|to))?)\s+(?P<value>\d+)\b", "temperature_f", "int"),
    (r"(?:using\s+)?(?P<value>default|warm|cool|winter)\s+preset\b", "preset", "str"),
]


def normalize(text):
    text = text.lower().replace("’", "'").strip()
    # Normalize spoken numbers without dropping signs, units, or other words.
    def tens(match):
        base = {"sixty": 60, "seventy": 70, "eighty": 80}[match[1]]
        return str(base + ONES.get(match[2], 0))
    text = re.sub(r"\b(sixty|seventy|eighty)(?:[ -]+(one|two|three|four|five|six|seven|eight|nine))?\b", tens, text)
    text = re.sub(r"\b(" + "|".join(ONES) + r")\b", lambda m: str(ONES[m[0]]), text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^please\s+", "", text)
    text = re.sub(r"^(?:(?:hey\s+)?siri[:,]?\s+)?tell\s+sirius\s+to\s+", "", text)
    return re.sub(r"^please\s+", "", text).rstrip(".! ")


def parse_command(text):
    """Return one action and explicit fields, refusing unconsumed text."""
    if not isinstance(text, str) or not text.strip() or len(text) > 400:
        raise CommandParseError("text must contain an instruction of at most 400 characters.")
    text = normalize(text)
    if re.search(r"\b(?:steering wheel|rear seats?|second row)\b", text):
        raise CommandParseError("This SX supports front-seat controls; steering-wheel and rear-seat heat are unavailable.")
    if re.search(r"\b(?:lift\s?gate|tailgate|trunk|sliding doors?)\b", text) or re.search(r"\b(?:open|close)\b.*\bdoors?\b", text):
        raise CommandParseError("Sliding-door and liftgate commands are unverified for this U.S. vehicle.")
    if re.search(r"\b(?:celsius|centigrade)\b|°\s*c\b", text):
        raise CommandParseError("Use a Fahrenheit temperature for this U.S. vehicle.")
    action = None
    for pattern, candidate, defaults in ACTIONS:
        match = re.match(pattern, text)
        if match:
            action = candidate
            parameters = dict(defaults)
            remaining = text[match.end():]
            break
    if action is None:
        raise CommandParseError("Use start, turn on, warm up, cool down, set temperature, stop, turn off, lock, or unlock; the vehicle name is optional.")
    seen = set()
    while remaining.strip():
        # Only grammatical separators can be discarded, never unknown words.
        remaining = re.sub(r"^(?:\s+|,|\band\b|\bwith\b|\bthe\b)+", "", remaining)
        if not remaining:
            raise CommandParseError("The instruction ends with an incomplete setting.")
        if action != "start_climate":
            raise CommandParseError("Use one command at a time; this action takes no climate settings.")
        for pattern, field, kind in CLAUSES:
            match = re.match(pattern, remaining)
            if not match:
                continue
            if field in seen:
                raise CommandParseError(f"Specify {field} only once.")
            seen.add(field)
            value = match["value"]
            if kind == "int":
                value = int(value)
            elif kind == "level":
                value = LEVELS[value] if value in LEVELS else int(value)
            elif kind == "bool":
                value = value == "on"
            elif kind == "true":
                value = True
            parameters[field] = value
            remaining = remaining[match.end():]
            break
        else:
            raise CommandParseError("Some of the instruction was not understood. No command was sent.")
    return {"action": action, "parameters": parameters}
