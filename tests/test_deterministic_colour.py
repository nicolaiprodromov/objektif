"""Throw-away diagnostic #2: make the portal material's colour choice deterministic
(in memory only; nothing is saved). Two variants:
  E) a single white portal  -> the lens adds zero noise
  F) a Bayer colour-filter-array mosaic chosen from the pixel position (RGGB)
Output PNGs go to renders/noise/.
"""
import bpy, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import RENDERS as OUT, LENS_OBJECT, plain_render, set_input

scene = bpy.context.scene
lens = bpy.data.objects[LENS_OBJECT]
RX, RY = 640, 360

scene.cycles.samples = 1
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
plain_render(scene)                      # objektif.blend: compositor, camera DOF and Raw view off
set_input(lens, "Depth of Field", False)   # the portals would also carry the rig's own aperture
set_input(lens, "Chromatic Aberration", 0.5)
scene.cycles.time_limit = 0
scene.render.resolution_x = RX
scene.render.resolution_y = RY
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
print("sampling pattern:", scene.cycles.sampling_pattern, "| blender", bpy.app.version_string)

mat = bpy.data.materials["Lens Glass (Portal)"]
nt = mat.node_tree
portals = {n.label.split(" - ")[-1]: n for n in nt.nodes
           if n.type == "GROUP" and n.node_tree and n.node_tree.name.startswith("Lens - Refraction Portal")}
final_mix = [n for n in nt.nodes if n.type == "MIX_SHADER" and n.label.startswith("bowl -> portal")][0]
print("portals found:", sorted(portals))

def render(name):
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)

def set_colour(portal, rgba):
    """The rig now feeds the portal colours from its sensor logic; a linked socket ignores
    its default value, so drop the link first."""
    sock = portal.inputs["Color"]
    for link in list(sock.links):
        nt.links.remove(link)
    sock.default_value = rgba

def math(op, a, b=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    if isinstance(a, bpy.types.NodeSocket):
        nt.links.new(a, n.inputs[0])
    else:
        n.inputs[0].default_value = a
    if b is not None:
        if isinstance(b, bpy.types.NodeSocket):
            nt.links.new(b, n.inputs[1])
        else:
            n.inputs[1].default_value = b
    return n.outputs[0]

# ---- E: one white portal, no stochastic closure choice at all ----------------
set_colour(portals["green"], (1.0, 1.0, 1.0, 1.0))
nt.links.new(portals["green"].outputs["Shader"], final_mix.inputs[2])
render("E_lens_single_portal_1spp.png")

# ---- F: Bayer CFA (RGGB) picked from the pixel index ------------------------
set_colour(portals["red"], (4.0, 0.0, 0.0, 1.0))     # 1 of 4 pixels
set_colour(portals["green"], (0.0, 2.0, 0.0, 1.0))   # 2 of 4 pixels
set_colour(portals["blue"], (0.0, 0.0, 4.0, 1.0))    # 1 of 4 pixels
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Window"], sep.inputs[0])
xm = math("MODULO", math("FLOOR", math("MULTIPLY", sep.outputs["X"], float(RX))), 2.0)
ym = math("MODULO", math("FLOOR", math("MULTIPLY", sep.outputs["Y"], float(RY))), 2.0)
is_red = math("MULTIPLY", xm, math("SUBTRACT", 1.0, ym))     # (odd x, even y)
is_blue = math("MULTIPLY", math("SUBTRACT", 1.0, xm), ym)    # (even x, odd y)
mix1 = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(is_red, mix1.inputs[0])
nt.links.new(portals["green"].outputs["Shader"], mix1.inputs[1])
nt.links.new(portals["red"].outputs["Shader"], mix1.inputs[2])
mix2 = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(is_blue, mix2.inputs[0])
nt.links.new(mix1.outputs[0], mix2.inputs[1])
nt.links.new(portals["blue"].outputs["Shader"], mix2.inputs[2])
nt.links.new(mix2.outputs[0], final_mix.inputs[2])
render("F_lens_bayer_mosaic_1spp.png")
