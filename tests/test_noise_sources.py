"""Throw-away diagnostic: 1-spp renders of the Physical Lens demo scene.
Nothing is saved back to the .blend. Output PNGs go to renders/noise/."""
import bpy, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import RENDERS as OUT, plain_render, set_input as set_lens_input

scene = bpy.context.scene
lens = bpy.data.objects["Physical Lens"]

def set_input(name, value):
    set_lens_input(lens, name, value)

# 1 sample, no denoise, no adaptive sampling, small frame
scene.cycles.samples = 1
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
plain_render(scene)                      # objektif.blend: compositor, camera DOF and Raw view off
# the lens as it was when this was written: random colour portals, no aperture of its own
set_input("Colour Sampling", "Stochastic")
set_input("Depth of Field", False)
set_input("Chromatic Aberration", 0.5)
scene.cycles.time_limit = 0
scene.render.resolution_x = 640
scene.render.resolution_y = 360
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
print("Cycles device:", scene.cycles.device, "| pixel filter:", scene.cycles.pixel_filter_type, scene.cycles.filter_width)

def render(name):
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    print("wrote", scene.render.filepath)

# A) bare camera, 1 spp  -> baseline scene noise
lens.hide_render = True
render("A_nolens_1spp.png")

# B) lens with default Chromatic Aberration 0.5, 1 spp
lens.hide_render = False
render("B_lens_ca050_1spp.png")

# C) lens with Chromatic Aberration 0 (single portal), 1 spp
set_input("Chromatic Aberration", 0.0)
render("C_lens_ca000_1spp.png")

# D) bare camera with strong depth of field, 1 spp -> what an optical blur does at 1 spp
set_input("Chromatic Aberration", 0.5)
lens.hide_render = True
cam = scene.camera.data
cam.dof.use_dof = True
cam.dof.focus_distance = 3.8
cam.dof.aperture_fstop = 1.0
render("D_nolens_dof_1spp.png")
