"""Side-by-side proof image: Mono | filter array binned 2x2 in LINEAR light (+1 stop
to undo the auto headroom) | filter array binned 2x2 in DISPLAY space (what a
zoomed-out image viewer does). Uses the EXR/PNG renders of test_filter_array_colour.py
(renders/scratch/) and writes renders/noise/J_filter_array_colour_proof.png. Needs no .blend:

    blender -b -P test_filter_array_colour_compare.py"""
import bpy, os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import RENDERS as OUT, SCRATCH

def load(name):
    img = bpy.data.images.load(os.path.join(SCRATCH, name))
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px

def bin2(a):
    h, w, _ = a.shape
    return a[:h - h % 2, :w - w % 2].reshape(h // 2, 2, w // 2, 2, 3).mean(axis=(1, 3))

def srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)

def up2(a):
    return np.repeat(np.repeat(a, 2, axis=0), 2, axis=1)

mono_lin, cfa_lin, cfa_png = load("mono.exr"), load("cfa.exr"), load("cfa.png")
left = srgb(mono_lin)                                   # Mono, display encoded
mid = up2(srgb(bin2(cfa_lin) * 2.0))                    # linear 2x2 bin, +1 stop
right = up2(bin2(cfa_png))                              # display-space 2x2 bin (PNG values are already encoded)
h = min(left.shape[0], mid.shape[0], right.shape[0])
strip = np.concatenate([left[:h], np.ones((h, 4, 3)), mid[:h], np.ones((h, 4, 3)), right[:h]], axis=1)
rgba = np.concatenate([strip, np.ones(strip.shape[:2] + (1,))], axis=2)
img = bpy.data.images.new("compare", strip.shape[1], strip.shape[0], alpha=True, float_buffer=False)
img.colorspace_settings.name = "Non-Color"           # values are already display encoded
img.pixels[:] = rgba.ravel().tolist()
img.filepath_raw = os.path.join(OUT, "J_filter_array_colour_proof.png")
img.file_format = "PNG"
img.save()
print("MEAN mono %s | linear-binned cfa (+1 stop) %s | display-binned cfa %s" %
      (np.round(left.reshape(-1, 3).mean(0), 3), np.round(mid.reshape(-1, 3).mean(0), 3), np.round(right.reshape(-1, 3).mean(0), 3)))
