"""Minimal Mapbox Vector Tile (MVT) reader.

Written by hand rather than pulling in a protobuf dependency: the BeagleBone
should not need a compiler toolchain, and only a small, well-defined subset
of the format is required here.

Wire format reference: protobuf encoding + vector_tile.proto v2.
"""
import gzip
import zlib

_POINT, _LINESTRING, _POLYGON = 1, 2, 3
_GEOM_TYPE_NAME = {_POINT: "Point", _LINESTRING: "LineString", _POLYGON: "Polygon"}


def _read_varint(buf, pos):
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _zigzag(value):
    return (value >> 1) ^ (-(value & 1))


def _iter_fields(buf, pos, end):
    """Yield (field_number, wire_type, value_or_slice, new_pos)."""
    while pos < end:
        key, pos = _read_varint(buf, pos)
        field, wire = key >> 3, key & 0x07
        if wire == 0:
            value, pos = _read_varint(buf, pos)
            yield field, wire, value
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            yield field, wire, (pos, pos + length)
            pos += length
        elif wire == 5:
            yield field, wire, (pos, pos + 4)
            pos += 4
        elif wire == 1:
            yield field, wire, (pos, pos + 8)
            pos += 8
        else:
            raise ValueError(f"unsupported wire type {wire}")


def _packed_varints(buf, start, end):
    values = []
    pos = start
    while pos < end:
        value, pos = _read_varint(buf, pos)
        values.append(value)
    return values


def _decode_value(buf, start, end):
    for field, wire, val in _iter_fields(buf, start, end):
        if field == 1 and wire == 2:
            return buf[val[0]:val[1]].decode("utf-8", errors="replace")
        if field in (4, 5) and wire == 0:
            return val
        if field == 6 and wire == 0:
            return _zigzag(val)
        if field == 7 and wire == 0:
            return bool(val)
    return None


def _decode_geometry(commands, extent, geom_type):
    """Turn command integers into rings/lines of tile-local coordinates."""
    parts, current = [], []
    x = y = 0
    i = 0
    while i < len(commands):
        header = commands[i]
        i += 1
        cmd, count = header & 0x07, header >> 3
        if cmd == 1:  # MoveTo
            for _ in range(count):
                x += _zigzag(commands[i]); y += _zigzag(commands[i + 1]); i += 2
                if current:
                    parts.append(current)
                current = [(x, y)]
        elif cmd == 2:  # LineTo
            for _ in range(count):
                x += _zigzag(commands[i]); y += _zigzag(commands[i + 1]); i += 2
                current.append((x, y))
        elif cmd == 7:  # ClosePath
            if current:
                current.append(current[0])
                parts.append(current)
                current = []
        else:
            break
    if current:
        parts.append(current)
    return parts


def _decode_feature(buf, start, end, keys, values, extent):
    tags, geometry, geom_type = [], [], 0
    for field, wire, val in _iter_fields(buf, start, end):
        if field == 2 and wire == 2:
            tags = _packed_varints(buf, val[0], val[1])
        elif field == 3 and wire == 0:
            geom_type = val
        elif field == 4 and wire == 2:
            geometry = _packed_varints(buf, val[0], val[1])
    if geom_type not in _GEOM_TYPE_NAME:
        return None

    props = {}
    for i in range(0, len(tags) - 1, 2):
        try:
            props[keys[tags[i]]] = values[tags[i + 1]]
        except IndexError:
            pass
    return {
        "type": _GEOM_TYPE_NAME[geom_type],
        "parts": _decode_geometry(geometry, extent, geom_type),
        "properties": props,
    }


def decode_tile(data, wanted=None):
    """Decode raw (optionally gzip/zlib compressed) tile bytes into
    {layer_name: {"extent": int, "features": [...]}}.

    `wanted` limits the work to those layer names. Feature geometry is by far
    the most expensive part of decoding, and a Shortbread tile carries plenty
    the chart never draws — buildings and addresses alone outnumber
    everything else. Skipping them here is what keeps a large area's start-up
    time on the BeagleBone reasonable."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    elif data[:1] == b"\x78":
        data = zlib.decompress(data)

    layers = {}
    for field, wire, val in _iter_fields(data, 0, len(data)):
        if field != 3 or wire != 2:
            continue
        lstart, lend = val
        name, extent, keys, values, feature_spans = None, 4096, [], [], []
        for lf, lw, lv in _iter_fields(data, lstart, lend):
            if lf == 1 and lw == 2:
                name = data[lv[0]:lv[1]].decode("utf-8", errors="replace")
            elif lf == 2 and lw == 2:
                feature_spans.append(lv)
            elif lf == 3 and lw == 2:
                keys.append(data[lv[0]:lv[1]].decode("utf-8", errors="replace"))
            elif lf == 4 and lw == 2:
                values.append(_decode_value(data, lv[0], lv[1]))
            elif lf == 5 and lw == 0:
                extent = lv
        if name is None or (wanted is not None and name not in wanted):
            continue
        features = []
        for fstart, fend in feature_spans:
            feat = _decode_feature(data, fstart, fend, keys, values, extent)
            if feat and feat["parts"]:
                features.append(feat)
        layers[name] = {"extent": extent, "features": features}
    return layers
