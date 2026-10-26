import re

_PAT = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def parse_duration(text):
    text = text.strip()
    m = _PAT.match(text)
    if not text or not m:
        raise ValueError(f"bad duration: {text!r}")
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s
