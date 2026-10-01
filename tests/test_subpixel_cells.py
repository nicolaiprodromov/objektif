"""Sub-pixel sensor cells: cell = 0.5 px, 4 samples, 1 px box filter.
Sobol puts the 4 samples of a pixel into its 4 quadrants, each quadrant is a
different cell, so every pixel collects R + G + G + B itself, in linear light,
before the view transform. Compares against Mono. Output files go to renders/scratch/.
Nothing is saved."""
import bpy, os, sys, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import set_input, plain_render, LENS_OBJECT, ATTR_CELL, SCRATCH as OUT

scene = bpy.context.scene
lens = bpy.data.objects[LENS_OBJECT]
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
plain_render(scene)                      # objektif.blend: compositor, camera DOF and Raw view off
scene.render.resolution_x, scene.render.resolution_y = 640, 360
scene.render.resolution_percentage = 100
scene.camera.data.dof.use_dof = False
# pure RGGB cells at gains 4 / 2 / 4 (the rig's old Gain Red/Green/Blue inputs are now Neutral Gains)
for key, value in {"Depth of Field": False, "Cell Size": 1, "Matrix Order": 1, "Filter Pattern": "Bayer",
                   "Red Share": 0.25, "Blue Share": 0.25, "White Share": 0.0, "Pattern Offset": (0.0, 0.0, 0.0),
                   "Filter Saturation": 1.0, "Neutral Gains": True, "Auto Headroom": False,
                   "Sensor Exposure": 0.0}.items():
    set_input(lens, key, value)

# override the cell size attribute in the material with a constant (prototype only)
mat = bpy.data.materials["Lens Glass (Portal)"]
nt = mat.node_tree
cell_attr = [n for n in nt.nodes if n.type == "ATTRIBUTE" and n.attribute_name == ATTR_CELL][0]
val = nt.nodes.new("ShaderNodeValue")
val.outputs[0].default_value = 0.5
relinked = 0
for l in list(nt.links):
    if l.from_node == cell_attr:
        to = l.to_socket; nt.links.remove(l); nt.links.new(val.outputs[0], to); relinked += 1
matrix_node = [n for n in nt.nodes if n.type == "GROUP" and n.node_tree.name == "Lens - Sensor Matrix"][0]
print("RELINKED", relinked, "| Cell Size input now fed by:", [l.from_node.name for l in matrix_node.inputs["Cell Size"].links])
clamp = [n for n in matrix_node.node_tree.nodes if n.label in ("cell >= 1", "cell > 0")][0]
clamp.inputs[1].default_value = 1.0 / 64.0       # allow sub-pixel cells (the rig now clamps at 1/64 itself)

def render(name, fmt, spp, filt, width):
    scene.cycles.samples = spp
    scene.cycles.pixel_filter_type = filt
    scene.cycles.filter_width = width
    ims = scene.render.image_settings
    if fmt == "EXR":
        ims.file_format = "OPEN_EXR"; ims.color_depth = "32"; ims.color_mode = "RGB"
    else:
        ims.file_format = "PNG"; ims.color_depth = "8"; ims.color_mode = "RGB"
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    return scene.render.filepath

def load(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px

set_input(lens, "Colour Sampling", "Mono")
mono = load(render("sub_mono_64.exr", "EXR", 64, "BOX", 1.0))
set_input(lens, "Colour Sampling", "Filter Array")
for spp in (4, 16):
    cfa = load(render("sub_cfa_%d.exr" % spp, "EXR", spp, "BOX", 1.0))
    render("sub_cfa_%d.png" % spp, "PNG", spp, "BOX", 1.0)
    mask = mono.mean(axis=2) > 0.05
    ratio = (cfa[mask] + 1e-6) / (mono[mask] + 1e-6)
    print("SUBPIXEL cell 0.5 px, %2d spp, box 1 px: per-pixel filter array / mono  median R %.3f G %.3f B %.3f | "
          "pixels within 10%% on all channels: %.1f%%" % (spp, np.median(ratio[:, 0]), np.median(ratio[:, 1]), np.median(ratio[:, 2]),
                                                           100.0 * (np.abs(ratio - 1).max(axis=1) < 0.1).mean()))
