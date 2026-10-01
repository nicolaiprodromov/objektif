# Noise tests (1 sample, no denoising)

The experiments behind the rig's **Sensor** and **Aperture** panels (both are
now built in). The scripts here change `../objektif.blend` in memory only and
are kept as a record; [Scripts](#scripts) says how to run them.

Six renders at **1 sample per pixel**, no
denoiser, no adaptive sampling, pixel filter 0.01 px (the scene's own setting),
640 × 360. They were made to find out *where* the noise that appears with the
lens comes from. Open them at 100 %: they are meant to be read pixel by pixel.

| Render | What was changed | What it shows |
|---|---|---|
| [`A_nolens_1spp.png`](renders/noise/A_nolens_1spp.png) | lens hidden | The scene's own 1‑spp grain (soft sun, small point lamp, sky, 12 bounces). Baseline. |
| [`B_lens_ca050_1spp.png`](renders/noise/B_lens_ca050_1spp.png) | lens on, Chromatic Aberration 0.5 (default) | Red / green / blue confetti on top of the grain. |
| [`C_lens_ca000_1spp.png`](renders/noise/C_lens_ca000_1spp.png) | lens on, Chromatic Aberration **0** | **Identical** confetti, so it is not caused by dispersion. |
| [`D_nolens_dof_1spp.png`](renders/noise/D_nolens_dof_1spp.png) | lens hidden, camera at f/1.0 | An optical blur at 1 spp is exactly as grainy as the sharp image, just blurry as well. A blur element picks one neighbour per ray instead of summing them. |
| [`E_lens_single_portal_1spp.png`](renders/noise/E_lens_single_portal_1spp.png) | lens on, material rewired (in memory) to **one white portal** | Same grain as A: the refracting portal itself is deterministic and adds no noise at all. |
| [`F_lens_bayer_mosaic_1spp.png`](renders/noise/F_lens_bayer_mosaic_1spp.png) | lens on, red / green / blue portal chosen **per pixel** from the pixel index (RGGB Bayer pattern) | The confetti is gone, replaced by an exact colour mosaic. Look at it at 100 %; downscaled viewers shift the colours because they average display values, not light. |

### Depth of field inside the lens (`test_dithered_aperture.py`)

Same idea applied to the blur: the camera stays a pinhole and every pixel gets
**one** aperture point, chosen from its 4×4 Bayer‑matrix index (16 points on a
golden‑angle spiral, digit‑reversed so the colour classes of the filter array
spread over the whole aperture). Focus is a world distance along the pixel's
chief ray after the glass. 1280 × 720, aperture radius 200 mm (deliberately far
beyond what the 83 mm glass allows, see below), focus 3.7 m.

| Render | What it shows |
|---|---|
| [`G_lens_dof_bayer4x4_mono_1spp.png`](renders/noise/G_lens_dof_bayer4x4_mono_1spp.png) | Mono (one white portal) + dithered aperture, 1 spp. Out‑of‑focus edges break into an ordered pattern, not noise. |
| [`H_lens_dof_bayer4x4_rggb_1spp.png`](renders/noise/H_lens_dof_bayer4x4_rggb_1spp.png) | The same with the RGGB filter array, 1 spp. |
| [`I_lens_dof_bayer4x4_rggb_16spp.png`](renders/noise/I_lens_dof_bayer4x4_rggb_16spp.png) | H at 16 spp: the lighting grain goes, the bokeh pattern and the mosaic stay exactly where they are (all samples hit the same pixel cell). |
| [`G_crop_floor_3x.png`](renders/noise/G_crop_floor_3x.png), [`G_crop_ball_3x.png`](renders/noise/G_crop_ball_3x.png), [`I_crop_ball_3x.png`](renders/noise/I_crop_ball_3x.png) | 3× nearest‑neighbour crops of the blurred floor and the in‑focus ball. |

Why the aperture is oversized: a first attempt aimed the bundle at a focus
plane in *camera* space, exactly like Cycles' own DOF. It rendered everything
blurred — the bowl is a strong negative element (about −86 mm), so the
camera‑space focus that puts the *world* in focus is ~0.18 m, and only 0.46× of
the aperture gets through the glass. A 180° fisheye simply has almost infinite
depth of field; a physically possible aperture gives a sub‑pixel blur through
this lens. Visible blur therefore has to be a *look* control: the aperture disc
lives on the front element and may be as large as you like.

### Why the filter array looked wrong on screen (`test_filter_array_colour*.py`)

The finished Filter Array shifted colours (dark, green) although the maths said
it shouldn't. Measured against Mono at 64 spp on the same scene:

| | 2×2 block average, filter array / Mono |
|---|---|
| linear EXR, pure primaries, neutral gains | R 1.000 · G 1.000 · B 1.000 — the mosaic is exact |
| the same as an 8‑bit PNG | R 0.28 · G 0.52 · B 0.25 — **98.7 % of the cells were above 1.0 and clipped**; what survives is the share pattern ¼ / ½ / ¼ |
| saturation 0.5 + Auto Headroom, linear | R 0.500 · G 0.500 · B 0.500 — exact, one stop down |

[`J_filter_array_colour_proof.png`](renders/noise/J_filter_array_colour_proof.png) shows it: Mono | the mosaic binned 2×2 in
**linear** light (+1 stop) — identical to Mono to three decimals | the mosaic
binned in **display** space, which is what a zoomed‑out image viewer does —
dull and green. So: view the mosaic at 100 %, and keep the cells within the
display (Auto Headroom, lower Filter Saturation) or write EXR.

`test_subpixel_cells.py` tried cells of half a pixel with 4 and 16 samples so
the pixel would collect R+G+G+B itself: the colour is right on average but not
per pixel (Cycles does not split its samples evenly between the sub‑cells), so
it converges with samples exactly like Stochastic — not a 1‑spp solution.

### Every pattern and mode, checked (`test_pattern_layouts.py`, `test_colour_neutrality.py`)

`test_pattern_layouts.py` prints the dominant colour per pixel as a character
map (pure primaries, 16 spp): Bayer gives `GBGB / RGRG`, the offset shifts it,
X‑Trans reproduces Fujifilm's 6×6 layout, RGBW replaces one green per tile with
white, Random is random, and Hybrid at saturation 1 is identical to the Filter
Array. `test_colour_neutrality.py` compares 24×24 block averages against Mono
in linear light at 64 spp — colour balance for Bayer (pastel and pure),
X‑Trans, RGBW, Random, Columns and Hybrid (saturation 0.5, 0, with white) is
1.000 / 1.000 / 1.000 within ±0.002; the only tinted setup is *Neutral Gains*
off, by design. Columns at "⅓" needed the band edges snapped to whole cells
(8 columns realise 3 / 2 / 3), which the rig now does for all Bayer patterns.

## The finding

`Lens Glass (Portal)` combines three Ray Portals (red, green, blue, each with
its own IOR) with *Add Shader*. Cycles evaluates **one** closure per ray, chosen
at random with probability 1/3 and scaled by 3. That is correct on average, so
it converges with samples and the denoiser, but at 1 spp every pixel is one
pure primary at triple brightness. The choice being *random* is the whole
problem; render F replaces the random number by the pixel position and the
noise disappears, while the optics stay untouched.

## Scripts

Every script opens `objektif.blend` in a background Blender and changes it in
memory only; nothing is saved back to the .blend. Pictures go to
`renders/noise/`, intermediate EXR and PNG files to `renders/scratch/` (ignored
by git). Set the environment variable `OBJEKTIF_TEST_OUT` to a folder to write
there instead and leave the committed pictures alone. `lens_rig.py` holds the
shared bits: the output folders, `set_input()` (sets a lens input by name, menus
by item name) and `plain_render()`, which switches off what `objektif.blend`
adds on top of a plain render (compositor, camera depth of field, Raw view).

Run them from this folder:

```
blender -b ..\objektif.blend -P test_noise_sources.py               # A, B, C, D
blender -b ..\objektif.blend -P test_deterministic_colour.py        # E, F
blender -b ..\objektif.blend -P test_filter_array_colour.py         # prints the table above; -- sat=0.5 expo=0 head=1
blender -b -P test_filter_array_colour_compare.py                   # J, from the files of the line above
blender -b ..\objektif.blend -P test_pattern_layouts.py             # character maps of every pattern
blender -b ..\objektif.blend -P test_colour_neutrality.py           # colour balance of every mode
blender -b ..\objektif.blend -P test_subpixel_cells.py              # half-pixel cells, 4 and 16 spp
python optics_check.py [fov] [format] [focal]                       # plain Python, no Blender; "stress" checks the rim
```

`test_dithered_aperture.py` (G, H, I) is the prototype that became the
Aperture panel. It patches the portal group as it was before that panel
existed, so on `objektif.blend` it stops with a message instead of rendering.

`test_deterministic_colour.py` contains the 20‑node prototype of the Bayer
selection: Texture Coordinate ▸ Window × resolution → floor → mod 2 → two Mix
Shaders with factors that are exactly 0 or 1 (Cycles skips closures with zero
weight, so the choice is deterministic).
