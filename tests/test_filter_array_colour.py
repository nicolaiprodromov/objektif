"""Where does the colour shift of the filter array come from?
Renders Mono (truth) and Filter Array RGGB (gains 4/2/4) at 64 spp, filter 0.01,
as linear EXR and as display PNG, then compares 2x2 block averages.
The four files go to renders/scratch/, where test_filter_array_colour_compare.py reads them.
Nothing is saved to the .blend."""
import bpy, os, sys, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import set_input, plain_render, LENS_OBJECT, SCRATCH as OUT

scene = bpy.context.scene
lens = bpy.data.objects[LENS_OBJECT]
plain_render(scene)                      # objektif.blend: compositor, camera DOF and Raw view off
vs = scene.view_settings
print("VIEW TRANSFORM:", vs.view_transform, "| look:", vs.look, "| exposure:", vs.exposure, "| gamma:", vs.gamma)
print("pixel filter:", scene.cycles.pixel_filter_type, scene.cycles.filter_width, "| samples in file:", scene.cycles.samples)

scene.cycles.samples = 64
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
scene.cycles.filter_width = 0.01
scene.render.resolution_x, scene.render.resolution_y = 640, 360
scene.render.resolution_percentage = 100
scene.camera.data.dof.use_dof = False
SAT = float(next((a[4:] for a in sys.argv if a.startswith("sat=")), "1.0"))
EXPO = float(next((a[5:] for a in sys.argv if a.startswith("expo=")), "0.0"))
HEAD = next((a[5:] for a in sys.argv if a.startswith("head=")), "1") == "1"
print("SETTINGS saturation", SAT, "sensor exposure", EXPO, "auto headroom", HEAD)
for key, value in {"Depth of Field": False, "Cell Size": 1, "Matrix Order": 2, "Filter Pattern": "Bayer",
                   "Red Share": 0.25, "Blue Share": 0.25, "Filter Saturation": SAT, "Neutral Gains": True,
                   "Auto Headroom": HEAD, "Sensor Exposure": EXPO}.items():
    set_input(lens, key, value)

def render(name, fmt):
    ims = scene.render.image_settings
    if fmt == "EXR":
        ims.file_format = "OPEN_EXR"; ims.color_depth = "32"; ims.color_mode = "RGB"
    else:
        ims.file_format = "PNG"; ims.color_depth = "8"; ims.color_mode = "RGB"
    path = os.path.join(OUT, name)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path

def load(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px

def block2(a):
    h, w, _ = a.shape
    return a[:h - h % 2, :w - w % 2].reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3))

set_input(lens, "Colour Sampling", "Mono")
mono_exr = load(render("mono.exr", "EXR"))
mono_png = load(render("mono.png", "PNG"))
set_input(lens, "Colour Sampling", "Filter Array")
cfa_exr = load(render("cfa.exr", "EXR"))
cfa_png = load(render("cfa.png", "PNG"))

for label, a, b in (("LINEAR (EXR)", mono_exr, cfa_exr), ("DISPLAY (PNG, view transform applied)", mono_png, cfa_png)):
    ma, mb = block2(a), block2(b)
    mask = ma.mean(axis=2) > 0.02
    ratio = (mb[mask] + 1e-6) / (ma[mask] + 1e-6)
    print("%-42s 2x2 block average, filter array / mono:  R %.3f  G %.3f  B %.3f   (1.000 = identical)"
          % (label, np.median(ratio[:, 0]), np.median(ratio[:, 1]), np.median(ratio[:, 2])))
    print("%-42s mean of whole image, mono -> cfa:  R %.3f -> %.3f   G %.3f -> %.3f   B %.3f -> %.3f"
          % ("", a[..., 0].mean(), b[..., 0].mean(), a[..., 1].mean(), b[..., 1].mean(), a[..., 2].mean(), b[..., 2].mean()))
print("linear EXR: fraction of filter-array pixels with a channel above 1.0 (would clip on a display): %.1f%%"
      % (100.0 * (cfa_exr.max(axis=2) > 1.0).mean()))
