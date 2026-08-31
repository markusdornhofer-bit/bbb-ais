"""Wrap raw NMEA/AIVDM lines in an IEC-61162 tag block carrying a unix
timestamp, so aisdb.decode_msgs (.nm4 format) can recover message time.
"""


def _checksum(content: str) -> str:
    cksum = 0
    for byte in content.encode("ascii", errors="replace"):
        cksum ^= byte
    return f"{cksum:02X}"


def wrap_tagblock(line: str, source: str, unixtime: int) -> str:
    content = f"s:{source},c:{unixtime},t:{unixtime}"
    return f"\\{content}*{_checksum(content)}\\{line}"


def strip_tagblock(line: str):
    """Reverse of wrap_tagblock: split a previously-archived line back into
    (payload, unixtime_or_None). Used when reprocessing raw .nm4 files;
    live serial input from the stick has no tag block to strip."""
    if not line.startswith("\\"):
        return line, None
    end = line.find("\\", 1)
    if end == -1:
        return line, None
    content = line[1:end].split("*")[0]
    payload = line[end + 1:]
    ts = None
    for field in content.split(","):
        if field.startswith("c:"):
            try:
                ts = int(field[2:])
            except ValueError:
                pass
    return payload, ts


def nmea_checksum_valid(line: str) -> bool:
    if "*" not in line or line[0] not in "!$":
        return False
    body, _, tail = line[1:].partition("*")
    tail = tail.strip()
    if len(tail) < 2:
        return False
    cksum = 0
    for byte in body.encode("ascii", errors="replace"):
        cksum ^= byte
    try:
        return cksum == int(tail[:2], 16)
    except ValueError:
        return False
