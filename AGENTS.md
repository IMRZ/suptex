# AGENTS.md

Notes for whoever changes `suptex.py`, and for reading a `.stpi` / `.stpd` pair without Crux3D's
`stupid.exe`. Everything below is measured unless it says OPEN, and the probes need only python3.

Re-measure a field before building on it: these notes can be wrong.

Measured on Shogun 2 `campaign_maps/bos_japan/display/Supertexture/` and on the Empire `world_` pair:

| texture       | index    | data          |
| ------------- | -------- | ------------- |
| bos_japan     | 27,376 B | 113,364,106 B |
| Empire world_ | 218,520 B | 178,165,184 B |

All four Shogun 2 sheets pass validation, so nothing here is bos_japan specific:

| sheet     | size        | base  | levels | tiles | blocks |
| --------- | ----------- | ----- | ------ | ----- | ------ |
| sho_japan | 32768x16384 | 64x32 | 6      | 2730  | 21840  |
| gem_japan | 32768x16384 | 64x32 | 6      | 2730  | 21840  |
| bos_japan | 16384x16384 | 32x32 | 6      | 1365  | 10920  |
| sho_tut   | 8192x8192   | 16x16 | 5      | 341   | 2728   |

## `.stpd`: the pixel data

Shogun 2: a flat sequence of blocks with no file header at all.

    <u32 compressed_size><u32 uncompressed_size><zlib data of compressed_size bytes>

Walking it is the whole reader for this file:

```python
off, blocks = 0, []
while off < len(d):
    comp, unc = struct.unpack_from("<II", d, off)
    blocks.append((off, comp, unc))
    off += 8 + comp
```

For bos_japan that walk gives **10,920 blocks**, every `unc` is exactly **32,768**, every block is a
complete zlib stream, and `off` lands exactly on the file size. 10,920 is 1,365 tiles times 8 blocks,
and 1,365 is the tile count of a six level pyramid over the 32x32 base.

Empire: **one zlib stream per tile**, no 8-byte block headers, holding a 128-byte DDS header
(`DDS `, 512x512, pitch 262,144, fourcc `DXT5`) and then the same 262,144 bytes of BC3.

## `.stpi`: the index

### Shogun 2

A 36-byte header, then six level groups, the base level first.

Header, nine little-endian u32:
`6, 16384, 16384, 512, 262144, 6, 32, 32, 0` = layers, width, height, tile size, tile bytes, layers
again, base tiles x, base tiles y, unknown zero. Fields 5 and 8 are OPEN.

The base level's records start straight after the header. Each later group starts with a two u32 group
header, `<rows>, <byte offset of the group's first tile in .stpd>`. It is rows, not columns: on the two
64x32 sheets those differ, and reading the field as the column count is what made sho_japan and
gem_japan fail until it was measured instead of assumed.

| level | grid  | tiles | first id | group header    |
| ----- | ----- | ----- | -------- | --------------- |
| base  | 32x32 | 1024  | 1        | in the header   |
| 2     | 16x16 | 256   | 1025     | (16, 84445103)  |
| 3     | 8x8   | 64    | 1281     | (8, 106140931)  |
| 4     | 4x4   | 16    | 1345     | (4, 111583349)  |
| 5     | 2x2   | 4     | 1361     | (2, 112932247)  |
| 6     | 1x1   | 1     | 1365     | (1, 113273728)  |

One tile is one 20-byte record, five u32:

| field | meaning                                                                       |
| ----- | ----------------------------------------------------------------------------- |
| 0     | tile size on disk, the tile's eight block headers plus its eight zlib payloads |
| 1     | uncompressed tile size, 262,144 for every tile                                 |
| 2     | tile id, 1..1,365, carrying on across the level groups                         |
| 3     | per level constant, `0xffffff00` on the base, `0x332c8500` on levels 2..6, OPEN |
| 4     | byte offset just past the tile, i.e. the next tile's start                     |

Field 4 holds for 1,359 of the 1,365 records. The five exceptions are the last record of a level
group, where it carries the next group's row count instead (16, 8, 4, 2, 1). Sum the sizes yourself
and do not trust that field.

The parse check that pins all of this, and passes on bos_japan: the record area is 6,835 u32
(= 1,365 x 5 + 5 group headers x 2) and all of them are consumed, ids run 1..1,365 in order, every
record's field 0 equals its eight blocks' `8 + comp` summed, and the running offset ends on
113,364,106.

The first 76 bytes, which is the header and the first two records:

    0000  06 00 00 00   layers           6
    0004  00 40 00 00   width            16384
    0008  00 40 00 00   height           16384
    000c  00 02 00 00   tile size        512
    0010  00 00 04 00   tile bytes       262144
    0014  06 00 00 00   layers again     6
    0018  20 00 00 00   base tiles x     32
    001c  20 00 00 00   base tiles y     32
    0020  00 00 00 00   zero
    0024  48 03 00 00   tile 1 on disk   840
    0028  00 00 04 00   tile 1 inflated  262144
    002c  01 00 00 00   tile 1 id        1
    0030  00 ff ff ff   tile 1 flag      0xffffff00
    0034  48 03 00 00   tile 1 ends at   840
    0038  48 03 00 00   tile 2 on disk   840

And the first 16 bytes of the `.stpd`, which is the first block of tile 1:

    0000  61 00 00 00   compressed       97
    0004  00 80 00 00   inflated         32768
    0008  78 da ...     zlib

### Empire

`world_` is 65536x32768, 512 px tiles, 7 levels over a 128x64 base, so the pyramid is 10,922 tiles.
The same idea as Shogun 2 with a different index and a different tile payload:

- **32-byte header**, not 36, and no trailing zero: the ninth u32 is the first record's offset.
- **The group header before each mip is `(tiles x, tiles y)`**, not `(rows, offset)` as on Shogun 2.
  There are six of them because the base level has none, so `32 + 6 * 8 + 10,922 * 20 = 218,520`,
  the file size exactly.
- **Record fields are offset, compressed size, raw size, a hash, a flag.** There is no tile id: the
  third field is the raw size here, which is why a Shogun 2 shaped parser throws on
  `record 1 carries tile id 262272`.
- **Records are seeks, not a walk.** Identical tiles share one stored stream: 6,294 of the 10,922
  records point at offset 0, a single 581-byte black tile, so the file holds 2,653 distinct tiles in
  ascending offset order. Walking streams sequentially instead fails part way with a zlib header
  error, which is what makes a valid file look corrupt.
- **Each tile is one zlib stream**, with no 8-byte block headers, holding a 128-byte DDS header
  (`DDS `, 512x512, pitch 262,144, fourcc `DXT5`) and then the same 262,144 bytes of BC3 as Shogun 2.
- **The variant is detected, not passed**: `byteLength - tiles * 20 - (layers - 1) * 8` is 36 on
  Shogun 2 and 32 on Empire, so `read_index` picks the layout from the file itself.

## The tiles are BC3 (DXT5)

Each tile is 262,144 B, which is 512x512 in BC3: 16 bytes per 4x4 block, 128 blocks per row, row
major. The eight zlib blocks of 32,768 B are the tile's eight bands of 64 pixel rows, in order.
libsquish in `stupid.exe` is the encoder.

Evidence, if the shape is ever doubted. Scoring a candidate decode by the mean horizontal difference
between neighbouring pixels separates texture from noise without needing a reference image, and on
the top level (tile 1,365, which is the whole sheet at 512x512):

| interpretation of the tile bytes | mean abs dx |
| -------------------------------- | ----------- |
| raw bytes read as 8-bit grey     | 55.95       |
| BC1 (DXT1), two 512x512 planes   | 30.55       |
| BC3 whole tile                   | 2.32        |

The same test parts the two 16-byte block formats: reading the first eight bytes as DXT3's sixteen
4-bit alphas scores 53.28, as DXT5's two endpoints plus six index bytes 0.40, so the payload is DXT5
and not DXT3.

Assert the decode before building on it. The raw 8-bit read of a base tile looks like fine noise with
64-pixel column structure, and that is exactly what sent a first attempt down the wrong path for a
while.

The block layout `decode_bc3` relies on: alpha endpoints at bytes 0-1, alpha indices 3 bits each at
2-7, colour endpoints 565 at 8-11, colour indices 2 bits each at 12-15. The colour index base is byte
12, not byte 4.

## Levels, layers and sheets: one word, three meanings

Three different things get called a layer, and only the first is what the index means by `layers`.
Mixing the first two up is what makes "preview all layers" ambiguous.

1. **A mip level**, also just a level or a mip. This is the header's first field and `header["layers"]`
   here. Level 1 is the base, the finest sheet. Every level after it halves both dimensions while the
   tile size stays 512, until the level is a single tile, or two when the base is not square:

   | texture            | levels | base                         | top level        |
   | ------------------ | ------ | ---------------------------- | ---------------- |
   | `world_` (Empire)  | 7      | 65536x32768, 128x64 tiles    | 1024x512, 2x1    |
   | sho_japan, gem_japan | 6    | 32768x16384, 64x32 tiles     | 1024x512, 2x1    |
   | bos_japan          | 6      | 16384x16384, 32x32 tiles     | 512x512, 1 tile  |
   | sho_tut            | 5      | 8192x8192, 16x16 tiles       | 512x512, 1 tile  |

   The levels are **stored, not generated**: each one has its own records and its own tiles, so
   nothing is downscaled to produce them, and the smallest level is instant.
2. **A sheet of pixels inside a tile.** One BC3 tile carries four 8-bit planes, and which sheet each
   plane holds differs by game. This is what `stupid.exe` means when it writes "a pair of layers", or
   offers a "normal" or a "relief" layer, and it has nothing to do with levels.
3. **A level in the code** is bookkeeping for one level only: its grid and its record list.
   `levels[3]` is the fourth level, not a sheet of pixels.

## Which plane holds which sheet

Measured by decoding one tile and comparing our four planes against both of the files `stupid.exe`
writes for that tile (the tile-500 table further down):

| game     | plane    | the sheet                             |
| -------- | -------- | ------------------------------------- |
| Empire   | R, G, B  | the coloured map, colour in the file  |
| Empire   | A        | the water and land mask, white water  |
| Shogun 2 | G        | palette indices                       |
| Shogun 2 | A, R, B  | the normal map                        |

- **Empire has no normal sheet.** `stupid.exe` writes `<stem>.bmp` (24-bit, the colour) and
  `<stem>.alpha.bmp` (8-bit, the mask) and nothing else, which is why Empire needs no palette bitmap
  while Shogun 2 does.
- **Shogun 2's A plane is not a mask**, it belongs to the normal map: A, R and B together reproduce
  the output of `stupid.exe` at RMSE 0.0008, while its 8-bit output is the G plane on its own. So the
  second file there is `<stem>.normal.bmp` rather than `<stem>.alpha.bmp`, and no mask sheet has been
  found in that variant.
- **The palette** is a 1x256 true colour TGA sitting beside the pair (`Parchment_Colour_Mapping.tga`),
  applied in reversed entry order, and it is not stored in either file.

On tile 500, base cell 19,15, the two outputs of `stupid.exe` against our planes:

| tool output            | what it is                                                                                                                                    |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `t500.bmp`, 8-bit      | our **G** plane: 69% of bytes identical, mean absolute difference 0.3, the same four commonest values in the same order (186, 190, 178, 182). Same plane, not bit exact, so do not diff it byte for byte |
| `t500.normal.bmp`, 24-bit | read as RGB it is our **A**, **R**, **B**, each to within 0.1                                                                                |

## Traps

- **An index read without validating it first is a hazard, not just a wrong answer.** A nonsense
  levels field sends the level loop off allocating before anything else can fail, and passing the
  `.stpd` where the `.stpi` belongs does exactly that. Validate the header, the size relations and the
  record area against the file length before trusting any of it. `index_problem` and `check_pair` in
  `suptex.py` are that check, and they name the swap when they see it.
- **Rendered tiles are checked before decoding.** Every tile's decoded BC3 body must match the
  expected tile size. Empire also checks the record's raw-size claim and requires a DXT5 DDS header.
  Shogun 2 currently checks only the combined tile body size; it does not validate each block's
  declared uncompressed size or the record's raw-size field.
- **A void tile matches every plane.** An all-black tile, deep sea or outside the map, has all four
  planes equal, so test on a tile with terrain on it. Tile 1 of bos_japan is pure black.
- **Both sheets are map shaped**, so eyeballing proves nothing. Compare against `stupid.exe`: under
  1/255 means the right plane, 0.2 to 0.37 means the wrong one.
- **Walking Empire's tiles sequentially fails part way with a zlib header error**, because its offsets
  are seeks into a deduplicated file. It reads exactly like a corrupt file.
- **The Shogun 2 group header's first word is the row count, not the column count.**
- **Record field 3 is a tile id on Shogun 2 and the raw size on Empire**, so a Shogun 2 shaped parser
  dies with `record 1 carries tile id 262272`.
- **A base level export is unusable in a viewer, so do not write one to look at.** The README's Size
  and Runtime section has the sizes; a mid level is the biggest whole image worth exporting, and
  `pyramid` is how a base level does come out, one 512 px tile per file.
- **Holding a base level whole costs several copies of the sheet at once**, which can take the whole
  machine down instead of failing in one process. Stream one band of rows: that is what `sheet_rows`
  does, and `MAX_BAND_BYTES` refuses a band over 512 MiB rather than trying. Streaming keeps the
  process alive, it does not make the resulting image any easier to open.

## Verifying a change

- Export the smallest level first, which takes under a second, and run `info`, which is free because
  it reads only the index.
- The neighbour-difference score above tells a real decode from noise without an image viewer (BC3
  about 2.3, raw bytes about 56), and a correct sheet looks like terrain.
- `example.stpi` / `example.stpd` is the checked in sample, and it is **Empire shaped only**: a
  32-byte header, one zlib stream per tile around a DDS header, seeks instead of a running offset,
  two identical tiles sharing one stream (five records, four streams), and an eight band alpha ladder
  across each tile, so every alpha index and the interpolation table are exercised. Its mask render
  reads 255, 0, 219, 182, 146, 109, 73, 36.
- There is no Shogun 2 fixture, so a change to the Shogun 2 path is unverified without a real pair.
  Its cases are the 8-block walk, the id sequence, the `(rows, offset)` group header and the per level
  flag, none of which the sample exercises.

## OPEN

1. The per-level constant. It is `0xffffff00` on the base level of all four Shogun 2 sheets, and it
   varies per texture on the mips (`0x332c8500` on bos_japan, `0x2ac62e00` on sho_tut), which reads
   like a per-texture id or a hash. Reading does not need it. A writer would.
2. Other titles. The Empire `world_` pair is solved, see "Empire" above. Napoleon is still
   unmeasured, and `stupid.exe`'s own `create-napoleon` verb suggests it has a layout of its own.
3. What `stupid.exe` calls the normal map is its 24-bit output holding (A, R, B) in that order, as
   measured above. Why it orders the channels that way is unexplained.
4. The per-level constant aside, the rest is consistent on bos_japan: the base level's data is the
   first 84,445,103 bytes, every group header's offset agrees with the running sum, and level 3
   assembles into a seamless sheet, so cells are row major in record order.
