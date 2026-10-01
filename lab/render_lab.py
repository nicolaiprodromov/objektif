"""Renders the lab pictures of the README into ../docs/lab/.

    blender -b lab.blend -P render_lab.py                       # every shot
    blender -b lab.blend -P render_lab.py -- with_lens fov_100  # only these
    blender -b lab.blend -P render_lab.py -- --list             # the shot names
    options: --scale 50 (percent of 1600 x 900)   --gpu 0 (render on that GPU only)   --out DIR

Every shot starts from the lab's lens (build_lab.LAB_LENS) and changes only what its name says.
Before it renders, a shot checks the lens's own messages: any warning stops the script, and the
angle the lens reports must be the Field of View asked for.

Full pictures are written as JPEG (quality 92, no chroma subsampling, so colour fringes survive).
Crops are PNG, enlarged with nearest-neighbour so each render pixel stays a crisp square.

The Aperture gives every pixel one point of the aperture, so a single render of a blur is an
ordered dither of 64 points (the 8 x 8 sensor matrix). The aperture shots render their crop 8
times larger and average each 8 x 8 block in linear light, which sums all 64 points: the picture
the dither stands for, with the bokeh's true shape.
"""
import math
import os
import re
import sys
import time

import bpy
import numpy as np
import OpenImageIO as oiio
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_lab as lab  # noqa: E402

OUT = os.path.normpath(os.path.join(HERE, os.pardir, "docs", "lab"))
SCRATCH = os.path.join(HERE, "scratch")        # the full render of every shot, ignored by git
FOCUS_TARGET = "ColorChecker Patches"          # the Aperture focuses here


class Shot:
    def __init__(self, name, lens=None, *, bare=False, crop=None, zoom=1, full=True, samples=None,
                 denoise=True, pixel_filter=None, tilt=0.0, binning=1):
        self.name = name
        self.lens = lens or {}      # changes to LAB_LENS
        self.bare = bare            # hide the lens: the plain 50 mm camera
        self.crop = crop            # (left, top, width, height) as fractions of the frame
        self.zoom = zoom            # nearest-neighbour enlargement of the crop
        self.full = full            # also write the full picture
        self.samples = samples      # None = the lab's 512 (adaptive)
        self.denoise = denoise
        self.pixel_filter = pixel_filter
        self.tilt = tilt            # camera pitch in degrees, up is positive
        self.binning = binning      # render the crop this many times larger, average in linear light
        if binning > 1 and (crop is None or full):
            raise ValueError("%s: a binned shot renders only its crop" % name)


EDGE = (0.845, 0.39, 0.15, 0.20)           # the 45 and 60 degree marks at the right edge, 180 degrees Full Frame
CHART = (0.455, 0.55, 0.09, 0.14)          # the middle of the ColorChecker at 100 degrees
BOKEH = (0.39, 0.12, 0.22, 0.60)           # a bulb above the ColorChecker at 100 degrees
# The aperture is a look control: through a 180 degree lens a real one gives almost no blur (see
# docs/README.md), so it is far larger than the glass. The pixel filter keeps rays on their cells.
DOF = {"Depth of Field": True, "Field of View": 100.0, "Aperture Radius": 250.0}
DOF_RENDER = dict(full=False, samples=16, denoise=False, pixel_filter=0.01, binning=8)
ONE_SAMPLE = dict(full=False, samples=1, denoise=False, pixel_filter=0.01)

SHOTS = [
    # With and without
    Shot("without_lens", bare=True),
    Shot("with_lens"),
    # Field of View (Full Frame); 180 is with_lens
    Shot("fov_100", {"Field of View": 100.0}),
    Shot("fov_140", {"Field of View": 140.0}),
    # Format; Full Frame is with_lens
    Shot("format_circular", {"Format": "Circular"}),
    Shot("format_custom", {"Format": "Custom", "Image Circle": 1.5}),
    # Glass and mount
    Shot("barrel_off", {"Format": "Custom", "Image Circle": 0.6, "Barrel": False}),
    Shot("tilted", {"Format": "Circular"}, tilt=35.0),
    # Chromatic Aberration at the right edge; 0.2 is the lab's default
    Shot("aberration_0", {"Chromatic Aberration": 0.0}, crop=EDGE, zoom=2, full=False),
    Shot("aberration_0.2", crop=EDGE, zoom=2, full=False),
    Shot("aberration_1", {"Chromatic Aberration": 1.0}, crop=EDGE, zoom=2, full=False),
    # Aperture: focused on the ColorChecker, three shapes. (Blades work too, but with 64 aperture points
    # a polygon's edges come out scalloped at this bokeh size; the Grid's square reads more clearly.)
    Shot("aperture_round", DOF, crop=BOKEH, **DOF_RENDER),
    Shot("aperture_grid", dict(DOF, **{"Aperture Pattern": "Grid"}), crop=BOKEH, **DOF_RENDER),
    Shot("aperture_anamorphic", dict(DOF, **{"Squeeze": 2.0}), crop=BOKEH, **DOF_RENDER),
    # Sensor at 1 sample per pixel
    Shot("sensor_stochastic", {"Field of View": 100.0, "Colour Sampling": "Stochastic"}, crop=CHART, zoom=3,
         **ONE_SAMPLE),
    Shot("sensor_mono", {"Field of View": 100.0, "Colour Sampling": "Mono"}, crop=CHART, zoom=3, **ONE_SAMPLE),
    Shot("sensor_filter_array", {"Field of View": 100.0, "Colour Sampling": "Filter Array"}, crop=CHART, zoom=3,
         **ONE_SAMPLE),
]


# ----------------------------------------------------------------------------- setup

def use_gpu(index=None):
    """Render on the GPU when there is one (all of them, or only the one at `index`)."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.refresh_devices()
        gpus = [d for d in prefs.devices if d.type == kind]
        if not gpus:
            continue
        if index is not None and not 0 <= index < len(gpus):
            raise SystemExit("--gpu %d: there are %d %s devices (0 to %d)" % (index, len(gpus), kind, len(gpus) - 1))
        for device in prefs.devices:
            device.use = False
        for device in (gpus if index is None else [gpus[index]]):
            device.use = True
        return "%s: %s" % (kind, ", ".join(d.name for d in gpus if d.use))
    return None


def focus_distance(lens):
    """Metres from the front of the glass (the vertex of its world side) to the focus target."""
    evaluated = lens.evaluated_get(bpy.context.evaluated_depsgraph_get())
    vertex = Vector(evaluated.data.attributes["lens_front_vertex"].data[0].vector)
    target = bpy.data.objects[FOCUS_TARGET]
    centre = sum((target.matrix_world @ Vector(corner) for corner in target.bound_box), Vector()) / 8.0
    return (centre - evaluated.matrix_world @ vertex).length


def apply(scene, camera, lens, shot, scale):
    lab.set_lens(lens, dict(lab.LAB_LENS, **shot.lens))
    lens.hide_render = shot.bare
    camera.rotation_euler = (math.radians(90.0 + shot.tilt), 0.0, 0.0)
    cy = scene.cycles
    cy.samples = shot.samples or 512
    cy.use_adaptive_sampling = shot.samples is None
    cy.use_denoising = shot.denoise
    cy.filter_width = 1.5 if shot.pixel_filter is None else shot.pixel_filter
    render = scene.render
    render.resolution_percentage = scale * shot.binning
    render.use_border = render.use_crop_to_border = shot.binning > 1
    if shot.binning > 1:                  # render only the crop (the border's y runs from the bottom)
        left, top, width, height = shot.crop
        render.border_min_x, render.border_max_x = left, left + width
        render.border_min_y, render.border_max_y = 1.0 - top - height, 1.0 - top
    bpy.context.view_layer.update()
    if dict(lab.LAB_LENS, **shot.lens)["Depth of Field"] and "Focus Distance" not in shot.lens:
        lab.set_input(lens, "Focus Distance", focus_distance(lens))
        bpy.context.view_layer.update()


def check_lens(lens, shot):
    """Stop on any warning of the rig; check the angle it reports."""
    messages = [(w.type, w.message) for w in lens.modifiers[lab.LENS_MODIFIER].node_warnings]
    problems = [m for kind, m in messages if kind != "INFO"]
    if problems:
        raise RuntimeError("%s: the lens warns: %s" % (shot.name, "; ".join(problems)))
    info = " ".join(m for kind, m in messages if kind == "INFO")
    if not shot.bare:
        wanted = dict(lab.LAB_LENS, **shot.lens)["Field of View"]
        got = re.search(r"Lens: ([\d.]+) deg", info)
        if not got or abs(float(got.group(1)) - wanted) > 0.5:
            raise RuntimeError("%s: asked for %.0f deg, the lens says: %s" % (shot.name, wanted, info))
    return info


# ----------------------------------------------------------------------------- images

def read(path):
    image = oiio.ImageBuf(path)
    return image.get_pixels(oiio.UINT8)[..., :3]


def write(path, pixels, jpeg=False):
    spec = oiio.ImageSpec(pixels.shape[1], pixels.shape[0], 3, oiio.UINT8)
    if jpeg:
        spec.attribute("Compression", "jpeg:92")
        spec.attribute("jpeg:subsampling", "4:4:4")
    out = oiio.ImageOutput.create(path)
    out.open(path, spec)
    out.write_image(np.ascontiguousarray(pixels))
    out.close()


def crop(pixels, box, zoom):
    h, w = pixels.shape[:2]
    left, top, width, height = box
    x0, y0 = int(round(left * w)), int(round(top * h))
    x1, y1 = min(w, x0 + int(round(width * w))), min(h, y0 + int(round(height * h)))
    return enlarge(pixels[y0:y1, x0:x1], zoom)


def enlarge(pixels, zoom):
    return pixels.repeat(zoom, axis=0).repeat(zoom, axis=1) if zoom > 1 else pixels


def render_binned(scene, shot):
    """Render the shot's crop to EXR, average blocks of binning x binning pixels in linear light and
    turn the result into display colours with the scene's view transform, like a render."""
    settings = scene.render.image_settings
    exr = os.path.join(SCRATCH, shot.name + ".exr")
    settings.file_format, settings.color_mode, settings.color_depth, settings.exr_codec = "OPEN_EXR", "RGB", "16", "ZIP"
    scene.render.filepath = exr
    bpy.ops.render.render(write_still=True)
    linear = oiio.ImageBuf(exr).get_pixels(oiio.FLOAT)[..., :3]
    os.remove(exr)                        # tens of megabytes, and only needed for this average
    b = shot.binning
    h, w = linear.shape[0] // b * b, linear.shape[1] // b * b
    binned = linear[:h, :w].reshape(h // b, b, w // b, b, 3).mean(axis=(1, 3))
    image = bpy.data.images.new(shot.name, binned.shape[1], binned.shape[0], alpha=True, float_buffer=True)
    rgba = np.ones(binned.shape[:2] + (4,), np.float32)
    rgba[..., :3] = binned
    image.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).ravel())   # Blender's rows run bottom-up
    png = os.path.join(SCRATCH, shot.name + ".png")
    settings.file_format, settings.color_depth = "PNG", "8"
    image.save_render(png, scene=scene)
    bpy.data.images.remove(image)
    return read(png)


# ----------------------------------------------------------------------------- main

def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    names, scale, gpu, out = [], 100, None, OUT
    while args:
        arg = args.pop(0)
        if arg == "--list":
            print("\n".join(s.name for s in SHOTS))
            return
        if arg in ("--scale", "--gpu", "--out"):
            if not args:
                raise SystemExit("%s needs a value" % arg)
            value = args.pop(0)
            try:
                if arg == "--scale":
                    scale = int(value)
                elif arg == "--gpu":
                    gpu = int(value)
                else:
                    out = os.path.abspath(value)
            except ValueError:
                raise SystemExit("%s needs a whole number, not %r" % (arg, value))
        else:
            names.append(arg)
    unknown = set(names) - {s.name for s in SHOTS}
    if unknown:
        raise SystemExit("unknown shots: %s (see --list)" % ", ".join(sorted(unknown)))
    shots = [s for s in SHOTS if not names or s.name in names]
    os.makedirs(out, exist_ok=True)
    os.makedirs(SCRATCH, exist_ok=True)

    scene = bpy.context.scene
    device = use_gpu(gpu)
    scene.cycles.device = "GPU" if device else "CPU"
    scene.cycles.denoising_use_gpu = bool(device)
    print("rendering on", device or "the CPU")
    camera, lens = scene.camera, bpy.data.objects[lab.LENS_OBJECT]

    for shot in shots:
        apply(scene, camera, lens, shot, scale)
        info = check_lens(lens, shot)
        started = time.time()
        written = []
        if shot.binning > 1:
            path = os.path.join(out, shot.name + ".png")
            write(path, enlarge(render_binned(scene, shot), shot.zoom))
            written.append(path)
        else:
            full_png = os.path.join(SCRATCH, shot.name + ".png")
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_depth = "8"
            scene.render.filepath = full_png
            bpy.ops.render.render(write_still=True)
            pixels = read(full_png)
            if shot.full:
                path = os.path.join(out, shot.name + ".jpg")
                write(path, pixels, jpeg=True)
                written.append(path)
            if shot.crop:
                path = os.path.join(out, shot.name + ("_crop" if shot.full else "") + ".png")
                write(path, crop(pixels, shot.crop, shot.zoom))
                written.append(path)
        print("%-22s %5.1f s  %s  -> %s" % (shot.name, time.time() - started, info or "(no lens)",
                                             ", ".join(os.path.basename(p) for p in written)))
    scene.render.use_border = False


if __name__ == "__main__":
    main()
