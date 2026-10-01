"""Verify the cell layouts: pure primaries, 16 spp, print a character map of the
dominant channel per pixel (R G B, W = white cell) for X-Trans, RGBW and Random."""
import bpy, os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import set_input, plain_render, LENS_OBJECT, SCRATCH as OUT
scene = bpy.context.scene
lens = bpy.data.objects[LENS_OBJECT]
scene.cycles.samples = 16
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
plain_render(scene)                      # objektif.blend: compositor, camera DOF and Raw view off
scene.cycles.filter_width = 0.01
scene.render.resolution_x, scene.render.resolution_y = 640, 360
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "OPEN_EXR"; scene.render.image_settings.color_depth = "32"
scene.camera.data.dof.use_dof = False
base = {"Colour Sampling": "Filter Array", "Cell Size": 1, "Matrix Order": 2, "Filter Pattern": "Bayer", "Red Share": 0.25,
        "Blue Share": 0.25, "White Share": 0.0, "Pattern Offset": (0.0, 0.0, 0.0), "Filter Saturation": 1.0,
        "Neutral Gains": True, "Auto Headroom": True, "Sensor Exposure": 0.0, "Depth of Field": False}

def load(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px[::-1]          # top row first

def cmap(a, x0, y0, w, h):
    rows = []
    for y in range(y0, y0 + h):
        row = ""
        for x in range(x0, x0 + w):
            p = a[y, x]
            if p.max() < 1e-4:
                row += "."
            elif p.min() > 0.3 * p.max():
                row += "W"
            else:
                row += "RGB"[int(p.argmax())]
        rows.append(row)
    return "\n".join(rows)

for name, over in (("bayer_rggb", {}), ("bayer_offset_1_0", {"Pattern Offset": (1.0, 0.0, 0.0)}),
                   ("xtrans", {"Filter Pattern": "X-Trans"}), ("rgbw", {"White Share": 0.25}),
                   ("random", {"Filter Pattern": "Random"}), ("hybrid_sat1", {"Colour Sampling": "Hybrid"})):
    s = dict(base); s.update(over)
    for k, v in s.items():
        set_input(lens, k, v)
    scene.render.filepath = os.path.join(OUT, "pat_%s.exr" % name)
    bpy.ops.render.render(write_still=True)
    a = load(scene.render.filepath)
    print("PATTERN %s\n%s" % (name, cmap(a, 300, 100, 12, 6)))
