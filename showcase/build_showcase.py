"""Builds showcase.blend, the product shot of objektif in the README.

    blender -b --factory-startup -P build_showcase.py

Run it from any folder: it writes showcase.blend next to this script. render_showcase.py renders the
picture into ../docs/showcase.jpg.

The rig itself is one glass element and a black tube (docs/README.md). For the picture it is dressed
up as a real objective: a cine fisheye prime on a small cinema camera. Its front element has the
rig's shape, a domed front and a concave bowl facing the camera, and sits in a barrel with gear rings,
printed scales, an inner element and an iris. None of this geometry is used by the lens. It exists
only to be photographed, with ordinary glass shaders.

The camera's side screen shows ../docs/lab/format_circular.jpg, a picture the real lens made.

Sizes are in millimetres. The lens is built along its own +Z axis, from the mount (z = 0) to the
front, and an empty turns that axis to world -Y, so the camera looks toward -Y.
"""
import math
import os

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
SHOWCASE_BLEND = os.path.join(HERE, "showcase.blend")
SCREEN_IMAGE = os.path.normpath(os.path.join(HERE, os.pardir, "docs", "lab", "format_circular.jpg"))

MM = 0.001

# The camera body: a box on a baseplate, its front face at y = 0, the lens mount in the middle of it.
BODY_X, BODY_Y, BODY_Z = 50.0, 118.0, 100.0     # half width, depth, height
BASE_TOP = 14.0                                  # the body stands on a baseplate this high
MOUNT_Z = BASE_TOP + BODY_Z / 2                  # height of the lens axis
FRONT_PLATE = -3.0                               # front face of the plate that carries the mount
FLANGE_Y = -6.5                                  # the lens's mount face (lens z = 0)

# The shot: where the picture camera looks, and from where (azimuth from the lens axis toward -X, the
# camera's right side as its operator sees it; elevation; distance in metres).
TARGET = (-4.0, -16.0, 60.0)
SHOT_AZIMUTH, SHOT_ELEVATION, SHOT_DISTANCE = 42.0, 15.0, 0.86
SHOT_FOCAL, SHOT_FSTOP = 85.0, 11.0

# The lens. The front element is the rig's kind of glass: a domed front and a concave bowl at the back.
DOME_EDGE_Z, DOME_APEX_Z, DOME_RADIUS = 92.0, 106.0, 34.8
BOWL_RIM_Z, BOWL_VERTEX_Z, BOWL_RADIUS = 86.0, 100.0, 20.0
FRONT_FACE_Z = 96.0                              # the printed front ring around the glass

# Printed markings. The font is Neue Montreal Regular, installed on the machine that builds the file
# (it is not free to share, so it is not in the repository). The text becomes meshes, so showcase.blend
# does not need the font. Without it the build falls back to Blender's own font, and says so.
FONT_FILE = r"C:\Windows\Fonts\NeueMontreal-Regular.otf"
FRONT_TEXT_TOP = "objektif  \u00b7  PHYSICAL FISHEYE  180\u00b0"
FRONT_TEXT_BOTTOM = "GEOMETRY NODES  \u00b7  RAY PORTAL  \u00b7  CYCLES"
FOCUS_SCALE = ["\u221e", "3", "1.5", "1", ".7", ".5", ".4", ".3"]
IRIS_SCALE = ["2", "2.8", "4", "5.6", "8", "11", "16"]
SIDE_LABELS = ["MENU", "ISO", "WB", "FPS"]
BUTTON_Y = [94.0 - 16.0 * k for k in range(len(SIDE_LABELS))]   # from the back of the body: left to right
SIDE_X = -(BODY_X - 0.4)                         # the -X side of the body behind its front section


# ----------------------------------------------------------------------------- materials

def principled(name, color, roughness, metallic=0.0, inputs=None):
    mat = bpy.data.materials.new(name)
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    for key, value in (inputs or {}).items():
        bsdf.inputs[key].default_value = value
    mat.diffuse_color = (*color, 1.0)
    return mat


def add_grain(mat, scale, strength):
    """A fine bump in object space, like powder coat or a textured finish."""
    tree = mat.node_tree
    bsdf = tree.nodes["Principled BSDF"]
    coords = tree.nodes.new("ShaderNodeTexCoord")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 2.0
    bump = tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = 0.00005
    tree.links.new(coords.outputs["Object"], noise.inputs["Vector"])
    tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def glass(name, ior, film_nm):
    """Clear glass with an anti-reflection coating: the thin film tints its reflections."""
    return principled(name, (1.0, 1.0, 1.0), 0.0, inputs={
        "Transmission Weight": 1.0, "IOR": ior, "Thin Film Thickness": film_nm, "Thin Film IOR": 1.38})


def screen_material(image):
    mat = principled("Showcase Screen", (0.0, 0.0, 0.0), 0.04, inputs={"Emission Strength": 2.2})
    tree = mat.node_tree
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    tree.links.new(texture.outputs["Color"], tree.nodes["Principled BSDF"].inputs["Emission Color"])
    return mat


def sweep_material():
    """The studio sweep: a glossy black floor that turns into a matt wall as it rises."""
    mat = principled("Showcase Studio Sweep", (0.016, 0.017, 0.02), 0.2)
    tree = mat.node_tree
    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    xyz = tree.nodes.new("ShaderNodeSeparateXYZ")
    ramp = tree.nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value, ramp.inputs["From Max"].default_value = 0.02, 0.6
    ramp.inputs["To Min"].default_value, ramp.inputs["To Max"].default_value = 0.16, 0.85
    tree.links.new(geometry.outputs["Position"], xyz.inputs["Vector"])
    tree.links.new(xyz.outputs["Z"], ramp.inputs["Value"])
    tree.links.new(ramp.outputs["Result"], tree.nodes["Principled BSDF"].inputs["Roughness"])
    return mat


def make_materials():
    m = {
        "paint": principled("Showcase Black Paint", (0.02, 0.02, 0.022), 0.36),
        "anodized": principled("Showcase Black Anodized", (0.035, 0.035, 0.038), 0.24, metallic=1.0),
        "gear": principled("Showcase Gear", (0.03, 0.03, 0.032), 0.38, metallic=1.0),
        "chrome": principled("Showcase Chrome", (0.86, 0.86, 0.87), 0.1, metallic=1.0),
        "accent": principled("Showcase Accent", (0.9, 0.24, 0.035), 0.3, metallic=1.0),
        "print": principled("Showcase Print", (0.82, 0.82, 0.8), 0.5),
        "print accent": principled("Showcase Print Accent", (0.95, 0.32, 0.04), 0.5),
        "inner": principled("Showcase Light Trap", (0.004, 0.004, 0.004), 0.75,
                            inputs={"Specular IOR Level": 0.2}),
        "iris": principled("Showcase Iris", (0.03, 0.03, 0.03), 0.45, metallic=0.6),
        # About a quarter wave of MgF2 for green light: the purple reflections of a coated lens.
        "front glass": glass("Showcase Glass (front element)", 1.62, 118.0),
        "inner glass": glass("Showcase Glass (inner element)", 1.75, 85.0),
        "body": principled("Showcase Camera Body", (0.014, 0.014, 0.016), 0.45),
        "red": principled("Showcase Record Red", (0.55, 0.015, 0.012), 0.3),
        "tally": principled("Showcase Tally Light", (0.3, 0.0, 0.0), 0.2,
                            inputs={"Emission Color": (1.0, 0.03, 0.02, 1.0), "Emission Strength": 25.0}),
        "sweep": sweep_material(),
    }
    add_grain(m["paint"], 2500.0, 0.06)
    add_grain(m["body"], 1800.0, 0.08)
    image = bpy.data.images.load(SCREEN_IMAGE, check_existing=True)
    image.filepath = "//" + os.path.relpath(SCREEN_IMAGE, HERE).replace("\\", "/")
    m["screen"] = screen_material(image)
    return m


# ----------------------------------------------------------------------------- geometry

def new_object(name, mesh, materials, collection, parent=None, sharp_angle=30.0):
    for mat in materials:
        mesh.materials.append(mat)
    mesh.shade_smooth()
    mesh.set_sharp_from_angle(angle=math.radians(sharp_angle))
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if parent:
        obj.parent = parent
    return obj


def ridges(count, depth, sharpness):
    """Radial offset of gear teeth or knurling at angle t: 0 on a ridge, -depth in a groove."""
    norm = math.tanh(sharpness)

    def offset(t):
        return -depth * 0.5 * (1.0 - math.tanh(sharpness * math.cos(count * t)) / norm)
    return offset


def lathe(name, profile, materials, collection, parent=None, segments=384, teeth=None, sharp_angle=30.0):
    """Revolves a profile around the lens axis. profile: (z, r, slot) or (z, r, slot, True) in mm,
    where slot picks the material of the strip that starts at this point and True puts the teeth
    on the point. Walk the profile (z to the right, r up) with the outside of the surface on the
    left: outer walls frontward, front faces inward, bores backward. Then the normals face out."""
    bm = bmesh.new()
    rings = []
    for point in profile:
        z, r = point[0], point[1]
        toothed = len(point) > 3 and point[3]
        if r < 1e-6:
            rings.append([bm.verts.new((0.0, 0.0, z * MM))])
            continue
        ring = []
        for i in range(segments):
            t = 2.0 * math.pi * i / segments
            rr = r + (teeth(t) if toothed else 0.0)
            ring.append(bm.verts.new((rr * math.cos(t) * MM, rr * math.sin(t) * MM, z * MM)))
        rings.append(ring)
    for k in range(len(rings) - 1):
        a, b, slot = rings[k], rings[k + 1], profile[k][2]
        if len(a) == 1 and len(b) == 1:
            continue
        for i in range(segments):
            j = (i + 1) % segments
            if len(a) == 1:
                verts = (a[0], b[j], b[i])
            elif len(b) == 1:
                verts = (a[i], a[j], b[0])
            else:
                verts = (a[i], a[j], b[j], b[i])
            bm.faces.new(verts).material_index = slot
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return new_object(name, mesh, materials, collection, parent, sharp_angle)


def arc(z_centre, radius, a_from, a_to, steps):
    """Points (z, r) of a sphere of the given radius centred on the axis at z_centre, from polar
    angle a_from to a_to (radians from the +z axis)."""
    return [(z_centre + radius * math.cos(a), radius * math.sin(a))
            for a in (a_from + (a_to - a_from) * s / steps for s in range(steps + 1))]


def rounded_box(name, lo, hi, radius, mat, collection, segments=6):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector(((lo[i] + (v.co[i] + 0.5) * (hi[i] - lo[i])) * MM for i in range(3)))
    bmesh.ops.bevel(bm, geom=list(bm.verts) + list(bm.edges), offset=radius * MM, segments=segments,
                    profile=0.5, affect="EDGES", clamp_overlap=True)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return new_object(name, mesh, [mat], collection, sharp_angle=40.0)


def cut(obj, cutters):
    """Subtract the cutter objects from obj (exact boolean), apply, and delete the cutters."""
    for cutter in cutters:
        mod = obj.modifiers.new("Cut", "BOOLEAN")
        mod.operation, mod.solver, mod.object = "DIFFERENCE", "EXACT", cutter
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    old = obj.data
    obj.modifiers.clear()
    obj.data = mesh
    bpy.data.meshes.remove(old)
    for cutter in cutters:
        mesh = cutter.data
        bpy.data.objects.remove(cutter)
        bpy.data.meshes.remove(mesh)


def flat_polygons(name, polygons, mat, collection, parent=None):
    """One object of flat faces; polygons are lists of 3D points in mm."""
    verts, faces = [], []
    for polygon in polygons:
        faces.append(tuple(range(len(verts), len(verts) + len(polygon))))
        verts += [Vector(p) * MM for p in polygon]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    return new_object(name, mesh, [mat], collection, parent)


# ----------------------------------------------------------------------------- text

_fonts = {}


def text_font():
    """FONT_FILE as a Blender font, or None for Blender's own font."""
    if FONT_FILE not in _fonts:
        if FONT_FILE and os.path.isfile(FONT_FILE):
            _fonts[FONT_FILE] = bpy.data.fonts.load(FONT_FILE, check_existing=True)
        else:
            print("font %r not found, printing in Blender's own font" % FONT_FILE)
            _fonts[FONT_FILE] = None
    return _fonts[FONT_FILE]


def glyphs(body, size, offset=0.0):
    """The filled outline of `body` in the text font, as (verts, faces) in mm, centred on the
    origin: x runs along the baseline, y up."""
    curve = bpy.data.curves.new("Text", "FONT")
    curve.body, curve.size, curve.offset = body, size, offset
    if text_font():
        curve.font = text_font()
    curve.align_x = "CENTER"
    curve.resolution_u = 4
    obj = bpy.data.objects.new("Text", curve)
    bpy.context.scene.collection.objects.link(obj)
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    verts = [Vector(v.co) for v in mesh.vertices]
    faces = [tuple(p.vertices) for p in mesh.polygons]
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(curve)
    bpy.data.meshes.remove(mesh)
    lo_y, hi_y = min(v.y for v in verts), max(v.y for v in verts)
    for v in verts:
        v.y -= (lo_y + hi_y) / 2.0       # centre vertically too
    return verts, faces


def text_width(body, size):
    verts, _ = glyphs(body, size)
    return max(v.x for v in verts) - min(v.x for v in verts)


class Print:
    """Collects printed text and marks for one object: every add() maps a piece of text from its
    flat (x, y) coordinates in mm to a point on the part, given as a function."""

    def __init__(self):
        self.verts, self.faces = [], []

    def add(self, body, size, place, offset=0.0):
        verts, faces = glyphs(body, size, offset)
        base = len(self.verts)
        self.verts += [Vector(place(v.x, v.y)) * MM for v in verts]
        self.faces += [tuple(base + i for i in f) for f in faces]

    def mesh(self, name):
        """The printing as a smooth-shaded mesh, without materials."""
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.shade_smooth()
        mesh.set_sharp_from_angle(angle=math.pi)
        return mesh

    def build(self, name, mat, collection, parent):
        return new_object(name, self.mesh(name), [mat], collection, parent, sharp_angle=180.0)


def on_barrel(radius, z_centre, angle):
    """Text upright when the camera is seen from the side: the baseline runs along the lens axis
    toward the front, the letters stand up around the barrel. angle is where the text sits around
    the axis, in degrees from +X toward up (90) and -X (180); it reads correctly on the -X side, the
    one the picture sees."""
    a0 = math.radians(angle)

    def place(x, y):
        t = a0 - y / radius
        r = radius + 0.12
        return r * math.cos(t), r * math.sin(t), z_centre + x
    return place


def on_front_ring(radius, z, angle, top=True):
    """Text around the front ring, read from the front: clockwise over the top with the letters
    pointing out, or counter-clockwise under the bottom with the letters pointing in."""
    a0 = math.radians(angle)

    def place(x, y):
        if top:
            t, r = a0 - x / radius, radius + y
        else:
            t, r = a0 + x / radius, radius - y
        return r * math.cos(t), r * math.sin(t), z + 0.03
    return place


# ----------------------------------------------------------------------------- the lens

PAINT, ANODIZED, CHROME, INNER = range(4)


def ease_flare(z0, r0, z1, r1, steps=12):
    """The trumpet-shaped front of the barrel: slow at first, then opening out."""
    return [(z0 + (z1 - z0) * s / steps, r0 + (r1 - r0) * (1.0 - math.cos(0.5 * math.pi * s / steps)), ANODIZED)
            for s in range(steps + 1)]


def build_lens(m, collection, view_angle):
    lens = bpy.data.objects.new("Objektif", None)
    lens.empty_display_type, lens.empty_display_size = "SINGLE_ARROW", 0.12
    lens.location = Vector((0.0, FLANGE_Y, MOUNT_Z)) * MM
    lens.rotation_euler = (math.radians(90.0), 0.0, 0.0)     # lens +Z to world -Y, lens +Y to world up
    collection.objects.link(lens)
    barrel_mats = [m["paint"], m["anodized"], m["chrome"], m["inner"]]

    # The barrel, from the bayonet to the front ring, then down the inside to a closed back.
    face_z = FRONT_FACE_Z
    profile = [
        (-4.0, 24.0, CHROME), (-4.0, 26.5, CHROME), (-0.3, 26.5, CHROME),
        (0.0, 26.8, ANODIZED), (0.0, 29.5, ANODIZED), (0.5, 30.0, ANODIZED), (3.6, 30.0, ANODIZED),
        (4.0, 30.4, PAINT), (4.0, 32.6, PAINT), (4.4, 33.0, PAINT), (27.0, 33.0, ANODIZED),
        (27.0, 33.8, ANODIZED), (27.4, 34.2, ANODIZED), (46.6, 34.2, ANODIZED), (47.0, 33.8, PAINT),
        (47.0, 33.5, PAINT), (73.0, 33.5, PAINT), (73.0, 34.8, PAINT), (73.3, 35.1, PAINT),
        (75.7, 35.1, PAINT), (76.0, 35.4, ANODIZED)]
    profile += ease_flare(76.0, 35.4, 89.0, 44.6)[1:]
    profile += [
        (89.6, 45.5, ANODIZED, True), (95.4, 45.5, ANODIZED, True), (face_z, 44.9, ANODIZED),
        (face_z, 37.4, INNER), (face_z - 0.8, 35.6, INNER), (74.0, 35.6, INNER), (74.0, 24.0, INNER),
        (40.0, 24.0, INNER), (40.0, 0.0, INNER)]
    lathe("Lens Barrel", profile, barrel_mats, collection, lens, segments=1200, teeth=ridges(200, 0.4, 1.5))

    lathe("Lens Accent Ring", [(8.0, 32.9, 0), (8.0, 33.3, 0), (8.3, 33.6, 0), (9.7, 33.6, 0), (10.0, 33.3, 0),
                               (10.0, 32.9, 0)], [m["accent"]], collection, lens)
    lathe("Lens Iris Ring", [
        (10.0, 32.9, PAINT), (10.0, 34.0, PAINT), (10.4, 34.4, PAINT), (18.6, 34.4, PAINT), (19.0, 34.4, ANODIZED),
        (19.0, 35.8, ANODIZED, True), (25.0, 35.8, ANODIZED, True), (25.0, 32.9, ANODIZED)],
        [m["paint"], m["gear"]], collection, lens, segments=880, teeth=ridges(88, 1.0, 2.5))
    lathe("Lens Focus Ring", [
        (49.0, 33.4, ANODIZED), (49.0, 37.8, ANODIZED, True), (57.0, 37.8, ANODIZED, True), (57.0, 36.6, PAINT),
        (72.4, 36.6, PAINT), (72.8, 36.2, PAINT), (72.8, 33.4, PAINT)],
        [m["paint"], m["gear"]], collection, lens, segments=920, teeth=ridges(92, 1.1, 2.5))

    # The front element: the rig's shape, a dome in front and a bowl facing the camera. Blackened edge.
    dome_r = (DOME_RADIUS ** 2 + (DOME_APEX_Z - DOME_EDGE_Z) ** 2) / (2.0 * (DOME_APEX_Z - DOME_EDGE_Z))
    bowl_r = (BOWL_RADIUS ** 2 + (BOWL_VERTEX_Z - BOWL_RIM_Z) ** 2) / (2.0 * (BOWL_VERTEX_Z - BOWL_RIM_Z))
    bowl = arc(BOWL_VERTEX_Z - bowl_r, bowl_r, 0.0, math.asin(BOWL_RADIUS / bowl_r), 24)
    dome = arc(DOME_APEX_Z - dome_r, dome_r, math.asin(DOME_RADIUS / dome_r), 0.0, 48)
    profile = [(z, r, 0) for z, r in bowl] + [(BOWL_RIM_Z, DOME_RADIUS, 1), (DOME_EDGE_Z, DOME_RADIUS, 0)]
    profile += [(z, r, 0) for z, r in dome[1:]]
    lathe("Lens Front Element", profile, [m["front glass"], m["paint"]], collection, lens, segments=256,
          sharp_angle=40.0)

    # Behind it, an inner element in a retaining ring, and the iris.
    inner = arc(71.0 - 82.2, 82.2, math.asin(22.0 / 82.2), 0.0, 8)
    profile = [(63.0 + 71.0 - z, r, 0) for z, r in reversed(inner)][:-1] + [(66.0, 22.0, 1), (68.0, 22.0, 0)]
    profile += [(z, r, 0) for z, r in inner[1:]]
    lathe("Lens Inner Element", profile, [m["inner glass"], m["paint"]], collection, lens, segments=192)
    lathe("Lens Retaining Ring", [(71.0, 24.0, 0), (71.0, 20.6, 0), (72.0, 20.6, 0), (72.0, 24.0, 0)],
          [m["inner"]], collection, lens, segments=192)
    build_iris(m, collection, lens, z=58.0, opening=7.5, outer=24.0, blades=9)
    for name, (printing, mat) in lens_prints(view_angle).items():
        printing.build(name, m[mat], collection, lens)
    return lens


def lens_prints(view_angle):
    """The printing on the lens, {object name: (Print, material)}: the front ring, the name and the
    scales on the side the picture sees."""
    front = Print()
    ring = (37.4 + 44.9) / 2.0
    front.add(FRONT_TEXT_TOP, 3.3, on_front_ring(ring, FRONT_FACE_Z, 90.0, top=True), offset=0.04)
    front.add(FRONT_TEXT_BOTTOM, 2.7, on_front_ring(ring, FRONT_FACE_Z, 270.0, top=False), offset=0.03)

    side = Print()
    accent = Print()
    name_len = 17.0
    side.add("objektif", 6.0 * name_len / text_width("objektif", 6.0), on_barrel(34.2, 37.0, view_angle - 5.5),
             offset=0.08)
    accent.add("180\u00b0 FISHEYE", 2.3, on_barrel(34.2, 37.0, view_angle + 4.0), offset=0.04)
    for k, label in enumerate(FOCUS_SCALE):
        angle = view_angle + (k - 3) * 7.5
        side.add(label, 2.6, on_barrel(36.6, 62.0, angle), offset=0.03)
        side.add("\u2014", 2.6, on_barrel(36.6, 69.4, angle + 0.6))
    for k, label in enumerate(IRIS_SCALE):
        side.add(label, 2.3, on_barrel(34.4, 14.5, view_angle + (k - 3) * 7.0), offset=0.03)
    accent.add("\u2014", 2.6, on_barrel(35.1, 74.5, view_angle + 0.6))      # focus index
    accent.add("\u2014", 2.6, on_barrel(33.0, 6.2, view_angle + 0.6))       # iris index
    return {"Lens Print (front ring)": (front, "print"), "Lens Print (side)": (side, "print"),
            "Lens Print (accent)": (accent, "print accent")}


def build_iris(m, collection, parent, z, opening, outer, blades):
    """Overlapping flat blades around a regular polygon opening, each a little in front of the last."""
    corners = [Vector((opening * math.cos(2 * math.pi * k / blades), opening * math.sin(2 * math.pi * k / blades)))
               for k in range(blades)]
    polygons = []
    for k in range(blades):
        a, b = corners[k], corners[(k + 1) % blades]
        d = (b - a).normalized()
        along = -a.dot(d) + math.sqrt(a.dot(d) ** 2 - (a.length ** 2 - outer ** 2))
        far = a + d * along                                # the blade's edge runs on past the corner
        a_far, a_start = math.atan2(far.y, far.x), math.atan2(a.y, a.x)
        while a_far < a_start:
            a_far += 2 * math.pi
        rim = [Vector((outer * math.cos(t), outer * math.sin(t)))
               for t in (a_far + (a_start - a_far) * s / 12 for s in range(13))]
        outline = [a, far] + rim
        height = z + 0.05 * k
        polygons.append([(p.x, p.y, height) for p in reversed(outline)])
    flat_polygons("Lens Iris", polygons, m["iris"], collection, parent)


# ----------------------------------------------------------------------------- the camera body

def build_body(m, collection, lens):
    x, y, z0, z1 = BODY_X, BODY_Y, BASE_TOP, BASE_TOP + BODY_Z
    rounded_box("Camera Baseplate", (-38.0, -12.0, 0.05), (38.0, y + 4.0, z0 + 1.0), 2.0, m["anodized"], collection)
    rounded_box("Camera Front", (-x, -0.5, z0), (x, 10.0, z1), 6.0, m["anodized"], collection)
    body = rounded_box("Camera Body", (-x + 0.4, 10.6, z0 + 0.4), (x - 0.4, y, z1 - 0.4), 6.0, m["body"], collection)
    cutters = []
    for k in range(8):           # vents across the top
        cy = 56.0 + 6.6 * k
        cutters.append(rounded_box("Vent", (-30.0, cy - 1.2, z1 - 3.0), (30.0, cy + 1.2, z1 + 2.0), 1.1,
                                   m["inner"], collection, segments=3))
    cut(body, cutters)
    rounded_box("Camera Front Plate", (-44.0, FRONT_PLATE, z0 + 6.0), (44.0, 0.0, z1 - 6.0), 3.0,
                m["anodized"], collection)
    rounded_box("Camera Shoe", (-9.0, 16.0, z1 - 1.0), (9.0, 44.0, z1 + 4.0), 1.0, m["anodized"], collection)

    # The mount ring on the plate, coaxial with the lens.
    mount = lathe("Camera Mount", [
        (-3.5, 33.6, 0), (-0.4, 33.6, 0), (0.0, 33.2, 0), (0.0, 27.4, 0), (-0.4, 27.0, 1), (-24.0, 27.0, 1)],
        [m["chrome"], m["inner"]], collection, segments=256)
    mount.location, mount.rotation_euler = lens.location.copy(), lens.rotation_euler.copy()
    rounded_box("Camera Lens Release", (24.0, FRONT_PLATE - 2.4, z0 + 12.0), (34.0, FRONT_PLATE + 0.5, z0 + 22.0),
                4.6, m["anodized"], collection, segments=8)
    tally = bpy.data.meshes.new("Camera Tally")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=1.8 * MM)
    bm.to_mesh(tally)
    bm.free()
    new_object("Camera Tally", tally, [m["tally"]], collection).location = Vector((-36.0, FRONT_PLATE, z1 - 12.0)) * MM

    # The -X side, which the picture sees: the screen, a record button and four buttons.
    sx, cy, cz, w, h = SIDE_X, 71.0, 80.0, 64.0, 36.0
    rounded_box("Camera Screen Bezel", (sx - 2.2, cy - w / 2 - 3.0, cz - h / 2 - 3.0),
                (sx + 1.0, cy + w / 2 + 3.0, cz + h / 2 + 3.0), 2.0, m["anodized"], collection)
    screen = bpy.data.meshes.new("Camera Screen")
    corners = [(sx - 2.25, cy + w / 2, cz - h / 2), (sx - 2.25, cy - w / 2, cz - h / 2),
               (sx - 2.25, cy - w / 2, cz + h / 2), (sx - 2.25, cy + w / 2, cz + h / 2)]
    screen.from_pydata([Vector(c) * MM for c in corners], [], [(0, 1, 2, 3)])
    uv = screen.uv_layers.new(name="UVMap")
    for loop, coords in zip(screen.loops, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[loop.index].uv = coords
    new_object("Camera Screen", screen, [m["screen"]], collection)

    rounded_box("Camera Record Button", (sx - 2.0, 12.0, z1 - 26.0), (sx + 1.0, 22.0, z1 - 16.0), 4.9,
                m["red"], collection, segments=8)
    for k, by in enumerate(BUTTON_Y):
        rounded_box("Camera Button %d" % (k + 1), (sx - 1.6, by - 4.2, 36.0), (sx + 1.0, by + 4.2, 44.4), 4.1,
                    m["anodized"], collection, segments=8)
    for name, (printing, mat) in body_prints().items():
        printing.build(name, m[mat], collection, None)


def body_prints():
    """The labels on the -X side of the body, {object name: (Print, material)}."""
    labels = Print()
    for label, by in zip(SIDE_LABELS, BUTTON_Y):
        labels.add(label, 2.4, lambda u, v, by=by: (SIDE_X - 0.05, by - u, 29.5 + v), offset=0.02)
    labels.add("REC", 2.4, lambda u, v: (SIDE_X - 0.05, 17.0 - u, BASE_TOP + BODY_Z - 33.0 + v), offset=0.02)
    return {"Camera Print": (labels, "print")}


# ----------------------------------------------------------------------------- the studio

def aim(obj, location, target):
    obj.location = location
    obj.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()


def from_target(target, azimuth, elevation, distance):
    """A point seen from target: azimuth in degrees from the lens axis (-Y) toward -X, elevation in
    degrees above the horizon, distance in metres."""
    a, e = math.radians(azimuth), math.radians(elevation)
    return target + Vector((-math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * distance


def area_light(name, collection, target, azimuth, elevation, distance, size, power, color=(1.0, 1.0, 1.0)):
    light = bpy.data.lights.new(name, "AREA")
    light.shape, light.size, light.size_y = "RECTANGLE", size[0], size[1]
    light.energy, light.color = power, color
    obj = bpy.data.objects.new(name, light)
    collection.objects.link(obj)
    aim(obj, from_target(target, azimuth, elevation, distance), target)
    return obj


def build_studio(m, collection):
    target = Vector(TARGET) * MM
    camera_data = bpy.data.cameras.new("Shot")
    camera_data.lens, camera_data.sensor_width = SHOT_FOCAL, 36.0
    camera_data.clip_start, camera_data.clip_end = 0.01, 20.0
    camera_data.dof.use_dof = True
    camera_data.dof.aperture_fstop = SHOT_FSTOP
    camera = bpy.data.objects.new("Shot", camera_data)
    collection.objects.link(camera)
    aim(camera, from_target(target, SHOT_AZIMUTH, SHOT_ELEVATION, SHOT_DISTANCE), target)
    # Focus on the front ring of the lens.
    camera_data.dof.focus_distance = (camera.location - Vector((0.0, FLANGE_Y - FRONT_FACE_Z, MOUNT_Z)) * MM).length

    # Softboxes. Their reflections are what draws the barrel and the glass.
    area_light("Key Softbox", collection, target, 65.0, 45.0, 0.9, (0.9, 0.6), 22.0)
    area_light("Top Softbox", collection, target, 10.0, 78.0, 0.8, (1.2, 0.35), 18.0)
    area_light("Fill", collection, target, -35.0, 28.0, 1.0, (0.6, 0.6), 3.0, (0.85, 0.92, 1.0))
    area_light("Rim (-X side)", collection, target, 150.0, 38.0, 0.6, (0.1, 0.9), 16.0)
    area_light("Rim (+X side)", collection, target, -150.0, 38.0, 0.6, (0.1, 0.9), 16.0, (0.9, 0.95, 1.0))

    # A sweep behind the camera, seen from the shot: glossy floor curving up into a matt wall.
    shot_dir = (camera.location - target).to_2d().normalized()
    back = -shot_dir
    side = Vector((back.y, -back.x))
    bend, radius = 1.1, 0.8
    profile = [(-3.0, 0.0), (bend, 0.0)]
    profile += [(bend + radius * math.sin(a), radius - radius * math.cos(a))
                for a in (math.pi / 2 * s / 16 for s in range(1, 17))]
    profile += [(bend + radius, 3.0)]
    verts, faces = [], []
    for s, h in profile:
        for w in (-3.0, 3.0):
            p = Vector((target.x, target.y)) + back * s + side * w
            verts.append((p.x, p.y, h))
    for k in range(len(profile) - 1):
        faces.append((2 * k, 2 * k + 1, 2 * k + 3, 2 * k + 2))
    mesh = bpy.data.meshes.new("Studio Sweep")
    mesh.from_pydata(verts, [], faces)
    sweep = new_object("Studio Sweep", mesh, [m["sweep"]], collection, sharp_angle=180.0)
    if sweep.data.polygons[0].normal.z < 0:
        sweep.data.flip_normals()

    # A soft pool of light on the floor behind the camera body, to lift it off the background.
    glow = bpy.data.lights.new("Backdrop Glow", "SPOT")
    glow.energy, glow.spot_size, glow.spot_blend, glow.color = 25.0, math.radians(45.0), 1.0, (0.55, 0.7, 1.0)
    glow.shadow_soft_size = 0.05
    obj = bpy.data.objects.new("Backdrop Glow", glow)
    collection.objects.link(obj)
    behind = Vector((back.x, back.y, 0.0))
    ground = Vector((target.x, target.y, 0.0))
    aim(obj, ground + behind * 0.5 + Vector((0.0, 0.0, 1.2)), ground + behind * 0.75)
    return camera


def setup_scene(scene, camera):
    scene.camera = camera
    scene.frame_start = scene.frame_end = scene.frame_current = 1
    scene.render.engine = "CYCLES"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1920, 1080, 100
    scene.render.use_compositing = False
    cy = scene.cycles
    cy.device = "GPU"                    # used when the preferences have a GPU; otherwise Cycles falls back to the CPU
    cy.samples, cy.use_adaptive_sampling, cy.adaptive_threshold = 512, True, 0.008
    cy.use_denoising, cy.denoiser = True, "OPENIMAGEDENOISE"
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces = 24, 4, 12
    cy.transmission_bounces, cy.transparent_max_bounces, cy.volume_bounces = 24, 8, 0
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.sample_clamp_indirect = 10.0
    view = scene.view_settings
    view.view_transform, view.look, view.exposure, view.gamma = "AgX", "AgX - Medium High Contrast", 0.0, 1.0

    world = bpy.data.worlds.new("Studio")
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.004, 0.0045, 0.006, 1.0)
    background.inputs["Strength"].default_value = 1.0
    scene.world = world


# ----------------------------------------------------------------------------- the file

def look_through_camera():
    """Open showcase.blend looking through the camera, like Numpad 0."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.region_3d.view_perspective = "CAMERA"


def forget_local_folders():
    """The startup file's file browsers open on the user's Documents folder, which would be saved into
    the file. Blank them. The whole buffer is filled first, because a .blend keeps the old text that
    follows a shorter string."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                params = getattr(space, "params", None) if space.type == "FILE_BROWSER" else None
                if params is None:
                    continue
                fill = "_" * (params.bl_rna.properties["directory"].length_max - 1)
                as_bytes = isinstance(params.directory, bytes)
                params.directory = fill.encode() if as_bytes else fill
                params.directory = b"" if as_bytes else ""


def clear_startup_file():
    """Remove what Blender's startup file brings: the cube, light and camera, their data, the collection."""
    for blocks in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights,
                   bpy.data.collections):
        for block in list(blocks):
            blocks.remove(block)


def view_angle():
    """Where the picture camera sits around the lens axis (degrees, as in on_barrel): the side
    scales and the name are printed there."""
    target = Vector(TARGET) * MM
    shot = from_target(target, SHOT_AZIMUTH, SHOT_ELEVATION, SHOT_DISTANCE)
    return math.degrees(math.atan2(shot.z - MOUNT_Z * MM, shot.x))


def main():
    clear_startup_file()
    bpy.context.preferences.filepaths.save_version = 0   # the script rebuilds showcase.blend, so no .blend1
    scene = bpy.context.scene
    m = make_materials()
    collections = {}
    for name in ("Objektif", "Camera Body", "Studio"):
        collections[name] = bpy.data.collections.new(name)
        scene.collection.children.link(collections[name])
    lens = build_lens(m, collections["Objektif"], view_angle())
    build_body(m, collections["Camera Body"], lens)
    camera = build_studio(m, collections["Studio"])
    setup_scene(scene, camera)
    look_through_camera()
    forget_local_folders()
    # The text is meshes now. A loaded font keeps a user after its text is deleted, and Blender would
    # save it with a path into this machine's font folder, so drop every font no text object uses.
    used = {getattr(c, slot) for c in bpy.data.curves if c.bl_rna.identifier == "TextCurve"
            for slot in ("font", "font_bold", "font_italic", "font_bold_italic")}
    for font in list(bpy.data.fonts):
        if font not in used:
            bpy.data.fonts.remove(font)
    bpy.ops.wm.save_as_mainfile(filepath=SHOWCASE_BLEND, compress=True)
    print("wrote", SHOWCASE_BLEND)


if __name__ == "__main__":
    main()
