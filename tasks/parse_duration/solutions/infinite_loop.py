def parse_duration(text):
    # Bug: forgets to advance i on a unit character -> loops forever.
    text = text.strip()
    if not text:
        raise ValueError("empty")
    total, i, num = 0, 0, ""
    while i < len(text):
        if text[i].isdigit():
            num += text[i]
            i += 1
        elif text[i] in "hms":
            total += int(num or 0) * {"h": 3600, "m": 60, "s": 1}[text[i]]
        else:
            raise ValueError("bad char")
    return total
