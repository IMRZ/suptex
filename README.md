# suptex

`suptex` exports campaign-map supertextures from Total War `.stpi` / `.stpd` file pairs as PNGs. It supports Shogun 2 (including Rise of the Samurai and Fall of the Samurai) and Empire: Total War. Python 3 is the only requirement.

## Quick Start

Try the included sample first:

```sh
python3 suptex.py example.stpi example.stpd --out map.png
```

For a game texture, pass the matching index and data files. They are usually together under `campaign_maps/<campaign>/display/Supertexture/` in the game install.

```sh
python3 suptex.py supertexture.stpi supertexture.stpd --out map.png
```

By default, suptex exports the smallest stored level: a quick, low-resolution preview. Use `info` to see the available levels before choosing a larger export:

```sh
python3 suptex.py info supertexture.stpi supertexture.stpd
```

## Choose What to Export

Each file pair contains a pyramid of stored levels. Level 1 is the largest; higher level numbers are progressively smaller. The smallest level is the default.

| Goal | Command |
| --- | --- |
| Export a particular level | `python3 suptex.py supertexture.stpi supertexture.stpd --level 4 --out map.png` |
| Export every sheet in the default level | `python3 suptex.py supertexture.stpi supertexture.stpd --all --out sheets.png` |
| Export tiles for every level | `python3 suptex.py pyramid supertexture.stpi supertexture.stpd --out tiles` |
| Stop a pyramid at zoom 3 | `python3 suptex.py pyramid supertexture.stpi supertexture.stpd --zoom 3 --out tiles` |

`--all` writes separate files with sheet names appended to the output stem: Empire produces `_colour` and `_mask`; Shogun 2 produces `_colour` and `_normal`.

### Sheets and Palettes

The available sheets differ by game:

| Game | Sheet | Selection |
| --- | --- | --- |
| Empire | Coloured map | `--render rgb` (default) |
| Empire | Water and land mask | `--render a` |
| Shogun 2 | Coloured map | `--render g --palette Parchment_Colour_Mapping.tga` (default plane is `g`) |
| Shogun 2 | Normal map | `--render arb` |

Shogun 2 stores palette indices rather than colour. Its `Parchment_Colour_Mapping.tga` is a separate file beside the pair; without it, the map is exported as greyscale indices. Empire stores its colour in the pair and has no normal sheet. Shogun 2 has no mask sheet.

`--render` accepts a combination of `r`, `g`, `b`, and `a`. `--palette` applies to a single channel; it is for Shogun 2 map colours.

### Pyramid Tiles

`pyramid` writes one PNG per tile as `<out>/<zoom>/<x>_<y>.png`. Zoom 0 is the smallest level, usually one or two tiles; zoom increases toward the full-resolution base. Rows count down from the top, as in common XYZ map tile schemes. Add `--all` to write every sheet, or `--fast` for quicker, larger PNGs.

## Size and Runtime

Use `pyramid` for the full-resolution base level rather than exporting it as one image. A base can exceed two billion pixels; although suptex streams its work, image viewers and editors may not be able to open the resulting PNG. Pyramid mode keeps output split into 512 px tiles.

The decoder processes one band of rows at a time for a single-image export and one tile at a time in pyramid mode. A measured run took about 68 seconds for 682 tiles in pure Python, so a complete large pyramid can take a few minutes. `--fast` lowers PNG compression effort, trading smaller output files for speed.

## Sample Files

`example.stpi` and `example.stpd` are a small, synthetic Empire-format pair (128 x 128 pixels, two levels, 64 px tiles). Its colour sheet contains white glyphs on black, and its mask is a greyscale ladder.

```sh
python3 suptex.py info example.stpi example.stpd
python3 suptex.py example.stpi example.stpd --all --out sheets.png
```

The first command lists the dimensions and estimated memory for each level. The second writes the default level's colour and mask sheets.

## Scope and Format Notes

suptex is a reader and exporter, not a viewer or modding toolchain. `pyramid` writes tile files; it does not serve them from the original pair. Editing textures or rebuilding pairs would require a writer.

For measured file layouts, decoding details, validation notes, and known format traps, see [AGENTS.md](AGENTS.md). The format was measured against Crux3D's `stupid.exe`; the implementation is independently written and includes no code from it. The reader and format notes were developed with AI assistance, so verify results against a real game pair before relying on them. Napoleon: Total War has not been tested.

## Licence

Public domain under the Unlicense; see [LICENSE](LICENSE).