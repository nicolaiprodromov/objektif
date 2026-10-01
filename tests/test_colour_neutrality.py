"""Colour neutrality of every pattern / mode in linear light: block averages of the
sensor render divided by Mono, normalised so a neutral result reads 1 / 1 / 1."""
import bpy, os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import set_input, plain_render, LENS_OBJECT, SCRATCH as OUT
scene = bpy.context.scene
lens = bpy.data.objects[LENS_OBJECT]
scene.cycles.samples = 64
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
plain_render(scene)                      # objektif.blend: compositor, camera DOF and Raw view off
scene.cycles.filter_width = 0.01
scene.render.resolution_x, scene.render.resolution_y = 480, 288
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "OPEN_EXR"; scene.render.image_settings.color_depth = "32"
scene.camera.data.dof.use_dof = False
base = {"Colour Sampling": "Filter Array", "Cell Size": 1, "Matrix Order": 3, "Filter Pattern": "Bayer", "Red Share": 0.25,
        "Blue Share": 0.25, "White Share": 0.0, "Pattern Offset": (0.0, 0.0, 0.0), "Filter Saturation": 0.5,
        "Neutral Gains": True, "Auto Headroom": True, "Sensor Exposure": 0.0, "Depth of Field": False}

def load(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px

def blocks(a, n=24):
    h, w, _ = a.shape
    return a[:h - h % n, :w - w % n].reshape(h // n, n, w // n, n, 3).mean(axis=(1, 3))

def render(name):
    scene.render.filepath = os.path.join(OUT, "neu_%s.exr" % name)
    bpy.ops.render.render(write_still=True)
    return load(scene.render.filepath)

set_input(lens, "Colour Sampling", "Mono")
mono = blocks(render("mono"))
mask = mono.mean(axis=2) > 0.05
for name, over in (("bayer sat 0.5", {}), ("bayer pure", {"Filter Saturation": 1.0}), ("bayer raw gains", {"Neutral Gains": False}),
                   ("xtrans", {"Filter Pattern": "X-Trans"}), ("rgbw", {"White Share": 0.25}), ("random", {"Filter Pattern": "Random"}),
                   ("columns 1/3", {"Filter Pattern": "Columns", "Red Share": 0.333, "Blue Share": 0.333}),
                   ("hybrid sat 0.5", {"Colour Sampling": "Hybrid"}), ("hybrid sat 0", {"Colour Sampling": "Hybrid", "Filter Saturation": 0.0}),
                   ("hybrid rgbw", {"Colour Sampling": "Hybrid", "White Share": 0.25})):
    s = dict(base); s.update(over)
    for k, v in s.items():
        set_input(lens, k, v)
    a = blocks(render(name.replace(" ", "_").replace("/", "")))
    ratio = np.median(a[mask] / (mono[mask] + 1e-9), axis=0)
    print("NEUTRAL %-18s brightness %.3f   colour balance R %.3f  G %.3f  B %.3f" % (name, ratio.mean(), *(ratio / ratio.mean())))
