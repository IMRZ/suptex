# SPDX-License-Identifier: Unlicense

"""Read and export Total War supertexture pairs to PNG."""

import argparse
import struct
import sys
import zlib
from pathlib import Path

BLOCKS_PER_TILE = 8
DDS_HEADER_BYTES = 128
RECORD_BYTES = 20
PALETTE_BYTES = 768
CHANNEL_OFFSETS = {"r": 0, "g": 1, "b": 2, "a": 3}
SHEETS = {
    "shogun2": (("colour", "g"), ("normal", "arb")),
    "empire": (("colour", "rgb"), ("mask", "a")),
}
MAX_LAYERS = 32
MAX_TILES = 4000000
MAX_BAND_BYTES = 512 * 1024 * 1024
PNG_LEVEL = 6  # --fast drops this to level 1: quicker, bigger files
PROGRESS_EVERY = 64
IDAT_CHUNK_BYTES = 1 << 20


def main():
    argv = sys.argv[1:]

    if argv[:1] == ["info"]:
        return show_info(argv[1:])

    run_export(argv)


def run_export(argv):
    global PNG_LEVEL

    every_level = argv[:1] == ["pyramid"]
    args = parse_args(argv[1:] if every_level else argv)

    if args.all and args.render:
        sys.exit("--all writes every sheet, so it does not take --render")
    if every_level and args.level is not None:
        sys.exit("pyramid writes every level, so it does not take --level")
    if not every_level and args.zoom is not None:
        sys.exit("--zoom only applies to pyramid")
    if args.fast:
        PNG_LEVEL = 1

    stpi = Path(args.stpi).read_bytes()
    stpd = Path(args.stpd).read_bytes()

    check_pair(stpi, stpd, args.stpi)

    header, variant, levels = read_index(stpi)
    render = args.render or ("rgb" if variant == "empire" else "g")
    palette = read_palette(args.palette) if args.palette else None

    if palette and variant == "empire":
        print("note: Empire tiles carry their own colour, so the palette is not used")
        palette = None
    if palette and not args.all and len(render) != 1:
        print(f"note: the palette maps one channel, not {render}, so it is not used")
        palette = None

    stem = Path(args.stpi).stem

    if every_level:
        out = Path(args.out) if args.out else Path(f"{stem}_pyramid")
        out.mkdir(parents=True, exist_ok=True)
        numbers = range(len(levels), 0, -1)

        if args.zoom is not None:
            print(f"note: writing zooms 0 to {args.zoom}, of 0 to {len(levels) - 1}")
    else:
        number = args.level if args.level is not None else header["layers"]
        numbers = [number]
        out = Path(args.out) if args.out else Path(f"{stem}_level{number}.png")

    written = 0
    total = 0

    for number in numbers:
        if not 1 <= number <= len(levels):
            sys.exit(f"level {number} does not exist, this pair has levels 1 to {len(levels)}")

        level = levels[number - 1]
        zoom = len(levels) - number
        sheets = SHEETS[variant] if args.all else ((None, render),)

        if every_level and args.zoom is not None and zoom > args.zoom:
            continue

        reach = max(offset + record for offset, record, _raw in level["tiles"])

        if reach > len(stpd):
            sys.exit(f"the level's tiles reach {reach} bytes, past the end of {args.stpd} at {len(stpd)}")

        if every_level:
            count, size = write_zoom(stpd, variant, header, level, zoom, sheets, palette, out / str(zoom))
            written += count
            total += size
            continue

        for name, sheet in sheets:
            write_level(stpd, variant, header, level, number, sheet, palette if len(sheet) == 1 else None, sheet_out(out, name))

    if every_level:
        print(f"wrote {written} tiles, {size_text(total)}, to {out.resolve()}")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="export supertexture levels as pngs")
    parser.add_argument("stpi")
    parser.add_argument("stpd")
    parser.add_argument("--level", type=int, help="1 is the base level, the default is the smallest")
    parser.add_argument("--palette", help="a 1x256 TGA, for the Shogun 2 colours")
    parser.add_argument("--render", help="any run of r, g, b, a, for example rgb, arb or a")
    parser.add_argument("--all", action="store_true", help="every sheet, not just the map")
    parser.add_argument("--fast", action="store_true", help="quicker pngs, deflate level 1 instead of 6")
    parser.add_argument("--zoom", type=int, help="pyramid only: the highest zoom to write, 0 is one tile")
    parser.add_argument("--out", help="the png to write, or the directory for pyramid")
    return parser.parse_args(argv)


def size_text(count):
    return f"{count / 1024:.0f} KiB" if count < 2**20 else f"{count / 2**20:,.0f} MiB"


def show_info(argv):
    parser = argparse.ArgumentParser(prog="suptex.py info", description="list the levels of a supertexture pair")
    parser.add_argument("stpi")
    parser.add_argument("stpd", nargs="?")
    args = parser.parse_args(argv)

    header, variant, levels = read_index(Path(args.stpi).read_bytes())
    tile = header["tileSize"]

    print(f"{header['width']} x {header['height']}, {len(levels)} levels of {tile} px tiles, {variant}")

    for number, level in enumerate(levels, start=1):
        tiles_x, tiles_y = level["grid"]
        band = tiles_x * tile * 3 * tile
        print(f"  level {number}: {tiles_x * tile}x{tiles_y * tile}, {tiles_x} x {tiles_y} tiles, {len(level['tiles'])} tiles, {size_text(band)} peak")

    print(f"level 1 is the base and level {len(levels)} is the smallest, which is the default")

    if args.stpd is None:
        return

    size = Path(args.stpd).stat().st_size
    store = [(offset, record) for level in levels for offset, record, _raw in level["tiles"]]
    reach = max(offset + record for offset, record in store)

    if reach > size:
        sys.exit(f"the records reach {reach} bytes, past the end of {args.stpd} at {size}")

    summary = f"{size} bytes on disk, the tiles reach {reach}"

    if variant == "empire":
        summary += f", {len({offset for offset, _record in store})} distinct tiles"

    print(summary)


def index_problem(stpi):
    if len(stpi) < 32:
        return f"only {len(stpi)} bytes, shorter than the header"

    layers, width, height, tile, tile_bytes, _again, base_x, base_y = struct.unpack_from("<8I", stpi, 0)

    if not 1 <= layers <= MAX_LAYERS:
        return f"{layers} levels"
    if not 8 <= tile <= 4096 or tile & (tile - 1):
        return f"{tile} px tiles"
    if not 1 <= base_x <= 4096 or not 1 <= base_y <= 4096:
        return f"a base grid of {base_x} x {base_y} tiles"
    if width != tile * base_x or height != tile * base_y:
        return f"{width}x{height} pixels, which is not {base_x} x {base_y} tiles of {tile} px"
    if tile_bytes not in (tile * tile, tile * tile + DDS_HEADER_BYTES):
        return f"{tile_bytes} bytes per tile, where {tile} px of BC3 is {tile * tile}"

    tiles = sum(max(1, base_x >> n) * max(1, base_y >> n) for n in range(layers))

    if tiles > MAX_TILES:
        return f"{tiles} tiles"
    if len(stpi) < 32 + tiles * RECORD_BYTES:
        return f"{len(stpi)} bytes, too short for {tiles} records"

    return None


def check_pair(stpi, stpd, path):
    problem = index_problem(stpi)

    if problem is None:
        return

    hint = ""

    if index_problem(stpd) is None:
        hint = ". The other path looks like the index, so the two are probably swapped"

    sys.exit(f"{path} does not look like a .stpi index: {problem}{hint}")


def read_index(stpi):
    problem = index_problem(stpi)

    if problem is not None:
        sys.exit(f"the index is not valid: {problem}")

    layers, width, height, tile_size, tile_bytes, _again, base_x, base_y = struct.unpack_from("<8I", stpi, 0)
    grids = [(max(1, base_x >> n), max(1, base_y >> n)) for n in range(layers)]
    expected = sum(x * y for x, y in grids)
    overhead = len(stpi) - expected * RECORD_BYTES - (layers - 1) * 8
    variant = {36: "shogun2", 32: "empire"}.get(overhead)

    if variant is None:
        sys.exit(f"the index is {len(stpi)} bytes, which is neither format for {expected} tiles")

    at = 36 if variant == "shogun2" else 32
    levels = []
    data_offset = 0

    for number, (tiles_x, tiles_y) in enumerate(grids):
        if number > 0:
            at += 8

        tiles = []
        for _ in range(tiles_x * tiles_y):
            words = struct.unpack_from("<5I", stpi, at)
            at += RECORD_BYTES

            if variant == "shogun2":
                size, raw, offset = words[0], words[1], data_offset
                data_offset += size
            else:
                offset, size, raw = words[0], words[1], words[2]

            tiles.append((offset, size, raw))

        levels.append(dict(grid=(tiles_x, tiles_y), tiles=tiles))

    header = dict(layers=layers, width=width, height=height, tileSize=tile_size, tileBytes=tile_bytes)
    return header, variant, levels


def sheet_out(base, name):
    return base if name is None else base.with_name(f"{base.stem}_{name}{base.suffix}")


def write_level(stpd, variant, header, level, number, render, palette, out):
    tiles_x, tiles_y = level["grid"]
    tile = header["tileSize"]
    width, height = tiles_x * tile, tiles_y * tile
    channels = 3 if palette or len(render) == 3 else 1
    band_bytes = width * tile * channels

    if band_bytes > MAX_BAND_BYTES:
        sys.exit(
            f"level {number} is {width}x{height}, so one band of {tile} rows needs {band_bytes / 2**20:.0f} MiB, over the "
            f"{MAX_BAND_BYTES // 2**20} MiB this script will hold. Levels get bigger as the number goes down"
        )

    write_png(out, width, height, channels, sheet_rows(stpd, variant, header, level, render, palette))

    what = f"{render} through the palette" if palette else render
    print(f"{variant} level {number}: {tiles_x} x {tiles_y} tiles of {tile} px, {what}")
    print(f"wrote {out.resolve()}, {width}x{height}, {out.stat().st_size} bytes")


def sheet_rows(stpd, variant, header, level, render, palette):
    tiles_x, tiles_y = level["grid"]
    tile = header["tileSize"]
    channels = 3 if palette or len(render) == 3 else 1
    stride = tiles_x * tile * channels
    band = bytearray(stride * tile)

    for row in range(tiles_y):
        for column in range(tiles_x):
            data, _channels = tile_pixels(stpd, variant, header, level["tiles"], row * tiles_x + column, render, palette)

            for line in range(tile):
                start = line * stride + column * tile * channels
                band[start : start + tile * channels] = data[line * tile * channels : (line + 1) * tile * channels]

        for line in range(tile):
            yield bytes(band[line * stride : (line + 1) * stride])


def write_zoom(stpd, variant, header, level, zoom, sheets, palette, directory):
    directory.mkdir(parents=True, exist_ok=True)
    tiles_x, tiles_y = level["grid"]
    expected = tiles_x * tiles_y * len(sheets)
    count = 0
    size = 0

    for row in range(tiles_y):
        for column in range(tiles_x):
            for name, sheet in sheets:
                path = sheet_out(directory / f"{column}_{row}.png", name)
                write_tile(stpd, variant, header, level, row, column, sheet, palette if len(sheet) == 1 else None, path)
                count += 1
                size += path.stat().st_size

                if count % PROGRESS_EVERY == 0:
                    print(f"zoom {zoom}: {count} of {expected} tiles, {size_text(size)}")

    print(f"zoom {zoom}: {expected} tiles, {size_text(size)}")
    return count, size


def write_tile(stpd, variant, header, level, row, column, render, palette, out):
    size = header["tileSize"]
    at = row * level["grid"][0] + column
    data, channels = tile_pixels(stpd, variant, header, level["tiles"], at, render, palette)
    rows = (data[line * size * channels : (line + 1) * size * channels] for line in range(size))
    write_png(out, size, size, channels, rows)


def tile_pixels(stpd, variant, header, tiles, at, render, palette):
    size = header["tileSize"]
    offset, record, raw = tiles[at]
    body = tile_body(stpd, variant, offset, record, raw)

    if len(body) != size * size:
        sys.exit(f"tile at {offset} holds {len(body)} bytes, a {size} px BC3 tile is {size * size}")

    return render_bytes(decode_bc3(body, size), render, palette)


def tile_body(stpd, variant, offset, size, raw):
    if variant == "shogun2":
        body = bytearray()
        at = offset

        while at < offset + size:
            compressed, _uncompressed = struct.unpack_from("<2I", stpd, at)
            body += zlib.decompress(stpd[at + 8 : at + 8 + compressed])
            at += 8 + compressed

        return bytes(body)

    payload = zlib.decompress(stpd[offset : offset + size])

    if len(payload) != raw:
        sys.exit(f"tile at {offset} inflated to {len(payload)}, its record says {raw}")
    if payload[0:4] != b"DDS " or payload[84:88] != b"DXT5":
        sys.exit(f"tile at {offset} is not a DXT5 dds")

    return payload[DDS_HEADER_BYTES:]


def decode_bc3(body, tile):
    rgba = bytearray(tile * tile * 4)
    across = tile // 4

    for by in range(across):
        for bx in range(across):
            at = (by * across + bx) * 16
            alpha = alpha_table(body, at)
            colour = colour_table(body, at)
            colour_bits = int.from_bytes(body[at + 12 : at + 16], "little")
            alpha_bits = int.from_bytes(body[at + 2 : at + 8], "little")

            for pixel in range(16):
                row = by * 4 + pixel // 4
                column = bx * 4 + pixel % 4
                out = (row * tile + column) * 4
                rgb = ((colour_bits >> (2 * pixel)) & 3) * 3

                rgba[out] = colour[rgb]
                rgba[out + 1] = colour[rgb + 1]
                rgba[out + 2] = colour[rgb + 2]
                rgba[out + 3] = alpha[(alpha_bits >> (3 * pixel)) & 7]

    return rgba


def alpha_table(body, at):
    first, second = body[at], body[at + 1]

    if first > second:
        return [first, second] + [half_up(((7 - i) * first + i * second) / 7) for i in range(1, 7)]

    return [first, second] + [half_up(((4 - i) * first + (i + 1) * second) / 5) for i in range(4)] + [0, 255]


def colour_table(body, at):
    first = body[at + 8] | (body[at + 9] << 8)
    second = body[at + 10] | (body[at + 11] << 8)
    table = expand565(first) + expand565(second)

    if first > second:
        table += tuple(half_up((2 * table[i] + table[3 + i]) / 3) for i in range(3))
        table += tuple(half_up((table[i] + 2 * table[3 + i]) / 3) for i in range(3))
    else:
        table += tuple(half_up((table[i] + table[3 + i]) / 2) for i in range(3))
        table += (0, 0, 0)

    return table


def expand565(value):
    return (
        half_up(((value >> 11) & 31) * 255 / 31),
        half_up(((value >> 5) & 63) * 255 / 63),
        half_up((value & 31) * 255 / 31),
    )


def half_up(value):
    return int(value + 0.5)


def render_bytes(rgba, render, palette):
    pixels = len(rgba) // 4

    if palette:
        out = bytearray(pixels * 3)

        for i in range(pixels):
            at = rgba[i * 4 + 1] * 3
            out[i * 3 : i * 3 + 3] = palette[at : at + 3]

        return bytes(out), 3

    offsets = [CHANNEL_OFFSETS[name] for name in render]
    out = bytearray(pixels * len(offsets))

    for i in range(pixels):
        for channel, offset in enumerate(offsets):
            out[i * len(offsets) + channel] = rgba[i * 4 + offset]

    return bytes(out), len(offsets)


def write_png(path, width, height, channels, rows):
    compressor = zlib.compressobj(PNG_LEVEL)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2 if channels == 3 else 0, 0, 0, 0)

    with Path(path).open("wb") as file:
        file.write(b"\x89PNG\r\n\x1a\n")
        write_chunk(file, b"IHDR", ihdr)

        pending = bytearray()

        for row in rows:
            pending += compressor.compress(b"\0" + row)

            if len(pending) >= IDAT_CHUNK_BYTES:
                write_chunk(file, b"IDAT", bytes(pending))
                pending.clear()

        pending += compressor.flush()
        write_chunk(file, b"IDAT", bytes(pending))
        write_chunk(file, b"IEND", b"")


def write_chunk(file, name, data):
    file.write(struct.pack(">I", len(data)))
    file.write(name)
    file.write(data)
    file.write(struct.pack(">I", zlib.crc32(name + data)))


def read_palette(path):
    tga = Path(path).read_bytes()
    id_length, colour_map_type, image_type = tga[0], tga[1], tga[2]
    width, height = struct.unpack_from("<2H", tga, 12)
    depth = tga[16]

    if colour_map_type != 0 or image_type != 2 or width != 1 or depth % 8:
        sys.exit(f"{path} is not a 1 pixel wide uncompressed true colour TGA")

    entry = depth // 8
    at = 18 + id_length
    table = bytearray()

    for i in range(height):
        blue, green, red = tga[at + i * entry], tga[at + i * entry + 1], tga[at + i * entry + 2]
        table += bytes((red, green, blue))

    reversed_table = b"".join(table[i : i + 3] for i in range(len(table) - 3, -1, -3))
    return bytes(reversed_table[:PALETTE_BYTES].ljust(PALETTE_BYTES, b"\0"))


if __name__ == "__main__":
    main()
