"""Frozen control ids. Google labels that are not listed here are ignored."""

HANDS = ("L", "R")

TRIGGER_IDS = ("closed_fist", "open_palm")
SLIDER_IDS = ("palm_x", "palm_y", "palm_z")
CONTROL_IDS = TRIGGER_IDS + SLIDER_IDS

KIND = {
    "closed_fist": "trigger",
    "open_palm": "trigger",
    "palm_x": "slider",
    "palm_y": "slider",
    "palm_z": "slider",
}

# Only these two classifier labels become controls. Anything else is dropped,
# including gestures added by a later model.
GOOGLE_TO_ID = {
    "Closed_Fist": "closed_fist",
    "Open_Palm": "open_palm",
}

LABELS = {
    "closed_fist": "closed fist",
    "open_palm": "open palm",
    "palm_x": "palm X",
    "palm_y": "palm Y",
    "palm_z": "palm Z",
}


def control_key(hand, control_id):
    return f"{hand}:{control_id}"


def parse_key(key):
    hand, sep, control_id = key.partition(":")
    if sep and hand in HANDS and control_id in CONTROL_IDS:
        return hand, control_id
    return None


def sort_key(hand, control_id):
    return (HANDS.index(hand), CONTROL_IDS.index(control_id))
