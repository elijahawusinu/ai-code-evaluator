def parse_duration(text):
    # Accepts units in any order and ignores bad characters - too lenient.
    total, num = 0, ""
    for ch in text.strip():
        if ch.isdigit():
            num += ch
        elif ch in "hms" and num:
            total += int(num) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
    return total
