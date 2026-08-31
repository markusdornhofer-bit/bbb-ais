"""Turn an MBTiles vector-tile archive into plain lon/lat geometry.

The covered area is small (a single harbour), so the whole base map is
decoded once at startup and handed to the browser in one go. That keeps the
client free of any map library — it only has to draw polylines.
"""
import math
import sqlite3
import zipfile
from pathlib import Path

from webmap.mvt import decode_tile

# Short geometry codes for the wire format. "Point" and "Polygon" must not
# collapse onto the same letter, hence explicit two-letter codes.
_GEOM_CODE = {"Point": "pt", "LineString": "ln", "Polygon": "pg"}

# Layers kept from the Shortbread sheet. Buildings, roads and their labels
# are deliberately absent: on the 35 x 36 nm sheet they are 100 000 features
# that say nothing about vessels.
#
# Measured 30.08.2026, whole sheet at zoom 14 (BeagleBone decodes ~21x
# slower than the development machine — 89.6 s there against 4.0 s here):
#   everything                 65 219 features   ~104 s on the BeagleBone
#   this list                  23 828 features    ~55 s
#   this list without `land`    4 993 features    ~13 s
#
# `land` alone is 18 835 of those features and is pure decoration — forest,
# scrub, orchards, gardens. It is in because the tinted ground was asked
# for; drop it first if start-up time ever matters more than the green.
LAYERS = (
    "ocean",
    "water_polygons",
    "land",
    "sites",
    "pier_polygons",
    "street_polygons",
    "pier_lines",
    "water_lines",
    "boundaries",
    "bridges",
    "ferries",
    "public_transport",
    "place_labels",
    "boundary_labels",
    "water_polygons_labels",
    "water_lines_labels",
)
_WANTED = frozenset(LAYERS)

# Polygonebenen, aus deren Rand die Kuestenlinie abgeleitet wird.
_KUESTE = frozenset(("ocean", "water_polygons"))


def find_mbtiles(search_dirs):
    """Locate an .mbtiles file, extracting it from a .zip when needed."""
    search_dirs = [Path(d) for d in search_dirs]
    for folder in search_dirs:
        if not folder.is_dir():
            continue
        found = sorted(folder.glob("*.mbtiles"))
        if found:
            return found[0]

    for folder in search_dirs:
        if not folder.is_dir():
            continue
        for archive in sorted(folder.glob("*.zip")):
            with zipfile.ZipFile(archive) as zf:
                members = [n for n in zf.namelist() if n.endswith(".mbtiles")]
                if not members:
                    continue
                target_dir = search_dirs[-1] / "map"
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / Path(members[0]).name
                if not target.exists():
                    with zf.open(members[0]) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                return target
    return None


def _kunstkante(a, b, extent):
    """True for a segment that only exists because the tile clipped the
    polygon at its own edge.

    Vector tiles cut every polygon at the tile border (here at -64 and
    extent+64), so a sheet assembled from 1482 tiles carries a straight
    edge along every tile boundary. Stroking the polygon outline therefore
    draws a mesh at the tile spacing over the water — a second coordinate
    grid, which is exactly how this was noticed. Such a segment is always
    axis-parallel *and* outside the tile's own area; a real coastline
    running along the same line stays inside it."""
    (ax, ay), (bx, by) = a, b
    if ax == bx and (ax < 0 or ax > extent):
        return True
    return ay == by and (ay < 0 or ay > extent)


def _kuestenlinie(parts, extent):
    """The runs of a polygon outline that are genuine coast, as open
    polylines — the clipped edges dropped."""
    aus = []
    for part in parts:
        lauf = []
        for i in range(len(part) - 1):
            if _kunstkante(part[i], part[i + 1], extent):
                if len(lauf) > 1:
                    aus.append(lauf)
                lauf = []
            else:
                if not lauf:
                    lauf.append(part[i])
                lauf.append(part[i + 1])
        if len(lauf) > 1:
            aus.append(lauf)
    return aus


def _tile_to_lonlat(x, y, z, px, py, extent):
    """Tile-local pixel -> WGS84 degrees (inverse Web Mercator)."""
    n = 1 << z
    lon = (x + px / extent) / n * 360.0 - 180.0
    ymerc = (y + py / extent) / n
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ymerc))))
    return lon, lat


def load_basemap(mbtiles_path, zoom=None):
    """Decode every tile at one zoom level into lon/lat features."""
    db = sqlite3.connect(str(mbtiles_path))
    meta = dict(db.execute("SELECT name, value FROM metadata"))

    if zoom is None:
        zoom = db.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()[0]

    # "coastline" is not in the sheet; it is derived below from the water
    # polygons so the shore can be stroked without the tile clip edges.
    out = {name: [] for name in LAYERS}
    out["coastline"] = []
    rows = db.execute(
        "SELECT tile_column, tile_row, tile_data FROM tiles WHERE zoom_level = ?",
        (zoom,),
    ).fetchall()

    for col, row, data in rows:
        y = (1 << zoom) - 1 - row  # MBTiles rows are TMS, tiles are XYZ
        try:
            layers = decode_tile(data, _WANTED)
        except Exception:
            continue  # a single corrupt tile must not kill the whole map
        for name in LAYERS:
            layer = layers.get(name)
            if not layer:
                continue
            extent = layer["extent"]
            for feat in layer["features"]:
                parts = [
                    [
                        [round(v, 6) for v in _tile_to_lonlat(col, y, zoom, px, py, extent)]
                        for px, py in part
                    ]
                    for part in feat["parts"]
                ]
                entry = {"t": _GEOM_CODE[feat["type"]], "c": parts}
                label = feat["properties"].get("name")
                if label:
                    entry["n"] = label
                # "kind" distinguishes landcover classes (forest, beach, ...)
                # so the client can tint them individually.
                kind = feat["properties"].get("kind")
                if kind:
                    entry["k"] = kind
                out[name].append(entry)

                if name in _KUESTE:
                    laeufe = _kuestenlinie(feat["parts"], extent)
                    if laeufe:
                        out["coastline"].append({"t": "ln", "c": [
                            [[round(v, 6)
                              for v in _tile_to_lonlat(col, y, zoom, px, py, extent)]
                             for px, py in lauf]
                            for lauf in laeufe
                        ]})

    bounds = [float(v) for v in meta.get("bounds", "-180,-85,180,85").split(",")]
    return {
        "zoom": zoom,
        "bounds": bounds,
        "name": meta.get("name", "map"),
        # MBTiles calls this `attribution`; `author` is only what some older
        # exports used. Reading the wrong key left it silently empty, and
        # OpenStreetMap data may not be shown without its credit.
        "attribution": meta.get("attribution") or meta.get("author", ""),
        "layers": out,
    }
