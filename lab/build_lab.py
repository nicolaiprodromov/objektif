"""Builds lab.blend, the room in which the pictures of the README are rendered.

    blender -b --factory-startup -P build_lab.py

Run it from any folder: it reads ../objektif.blend and writes lab.blend next to this script.

The lab is one closed room, 7.2 m square and 3 m high, lined with calibration patterns. Everything
is procedural, so the file needs no images:

- straight ahead, a wall of Siemens stars (the classic resolution target), one per 0.6 m cell;
- a black and white checkerboard floor with 0.6 m squares, and a tiled ceiling;
- graph-paper walls with a different ink on each, so every wall is easy to find in a fisheye
  picture: orange on the left, blue on the right, green behind the camera;
- a protractor band all the way round at eye height, with a tick every 5 degrees and a number every
  15, measured from the lens. The number at the edge of a picture is how far the lens sees;
- three strip lights in the ceiling and a row of small bulbs, which the Aperture turns into bokeh;
- in front of the chart, on plinths, an 18 % grey ball, a ColorChecker and a mirror ball.

The camera and the lens are appended from ../objektif.blend (its "camera" collection), so a rebuild
picks up the current rig. The lens is left at the lab's defaults (LAB_LENS); render_lab.py changes
it per picture.
"""
import math
import os

import bmesh
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
RIG_BLEND = os.path.normpath(os.path.join(HERE, os.pardir, "objektif.blend"))
LAB_BLEND = os.path.join(HERE, "lab.blend")

RIG_COLLECTION = "camera"          # the collection in objektif.blend that holds the camera and the lens
CAMERA_OBJECT = "Camera"
LENS_OBJECT = "Physical Lens"
LENS_MODIFIER = "Physical Lens Rig"

# The room, in metres, on the 0.6 m grid of the patterns. The camera looks along +Y.
HALF_WIDTH = 3.6       # side walls at x = -3.6 and x = +3.6
FRONT = 4.8            # the Siemens-star wall
BACK = -2.4            # the wall behind the camera
HEIGHT = 3.0           # the ceiling
EYE = 1.2              # camera height; the protractor band runs round the room at this height
CELL = 0.6             # floor squares, ceiling tiles and chart cells
STAR_RADIUS = 0.24
STAR_SPOKE_PAIRS = 18  # 18 black and 18 white spokes
BAND_BELOW, BAND_ABOVE = 0.08, 0.22   # the protractor band runs from EYE - 0.08 to EYE + 0.22
LABEL_STEP = 15        # a number every 15 degrees
# The protractor's centre. Rays leave the glass as if they came from a point about 0.12 m in front
# of the camera (tests/optics_check.py traces it; at 180 degrees the best point is 0.12 m for both
# formats), so the camera stands that far behind the centre. Then the band reads the true angle of
# every ray to within about 0.25 degrees.
PROTRACTOR = (0.0, 0.0)
CAMERA_BACK = 0.12

# Colours (linear). Each graph-paper wall has its own tinted paper and ink.
WHITE = (0.75, 0.75, 0.75)
BLACK = (0.02, 0.02, 0.02)
GRAPH_PAPER = {"left": ((0.72, 0.55, 0.40), (0.60, 0.10, 0.01)),     # (paper, ink)
               "right": ((0.42, 0.55, 0.70), (0.01, 0.09, 0.45)),
               "back": ((0.45, 0.62, 0.45), (0.01, 0.22, 0.04))}

# The lens as the lab leaves it. Angles are in degrees, menus by item name (see set_input).
LAB_LENS = {
    "Field of View": 180.0, "Format": "Full Frame", "Image Circle": 1.5,
    "Chromatic Aberration": 0.2, "Edge Darkening": 1.0, "Distance": 0.1,
    "Front Dome": 0.15, "Refractive Index": 2.0, "Barrel": True,
    "Colour Sampling": "Stochastic", "Cell Size": 1, "Matrix Order": 3, "Filter Pattern": "Bayer",
    "Red Share": 0.25, "Blue Share": 0.25, "White Share": 0.0, "Pattern Offset": (0.0, 0.0, 0.0),
    "Filter Saturation": 0.5, "Neutral Gains": True, "Auto Headroom": True, "Sensor Exposure": 0.75,
    "Depth of Field": False, "Aperture Radius": 20.0, "Focus Distance": 2.6, "Follow Camera Focus": False,
    "Aperture Pattern": "Spiral", "Blades": 0, "Rotation": 0.0, "Squeeze": 1.0,
    "Spherical Aberration": 0.0, "Cat's Eye": 0.0,
    "Segments": 128, "Rings": 8,
}

# The X-Rite ColorChecker Classic in sRGB, row by row from the top left.
COLOR_CHECKER = [
    (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
    (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
    (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
    (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
]


# ----------------------------------------------------------------------------- the lens inputs

def _lens_inputs(tree):
    return {item.name: item for item in tree.interface.items_tree
            if item.item_type == "SOCKET" and item.in_out == "INPUT"}


def _menu_items(tree, identifier):
    """{item name: stored value} of a menu input. The modifier stores the integer id of the chosen
    item; the names live on the Menu Switch node that the input feeds."""
    for node in tree.nodes:
        if node.bl_idname != "GeometryNodeMenuSwitch":
            continue
        for link in node.inputs["Menu"].links:
            if link.from_node.bl_idname == "NodeGroupInput" and link.from_socket.identifier == identifier:
                return {s.name: int(s.identifier.split("_")[1]) for s in node.inputs
                        if s.identifier.startswith("Item_")}
    return {}


def set_input(lens, name, value):
    """Set an input of the lens modifier by its name, as shown in the modifier panel.
    Menus take the item name, angles are in degrees: set_input(lens, "Field of View", 150)."""
    mod = lens.modifiers[LENS_MODIFIER]
    tree = mod.node_group
    items = _lens_inputs(tree)
    if name not in items:
        raise KeyError("the lens modifier has no input %r; it has: %s" % (name, ", ".join(items)))
    item = items[name]
    if item.socket_type == "NodeSocketMenu":
        choices = _menu_items(tree, item.identifier)
        if value not in choices:
            raise KeyError("%r is not an item of the %r menu; it has: %s" % (value, name, ", ".join(choices)))
        value = choices[value]
    elif item.socket_type == "NodeSocketFloat":
        value = math.radians(value) if getattr(item, "subtype", "") == "ANGLE" else float(value)
    elif item.socket_type == "NodeSocketInt":
        value = int(value)       # an int written into a float input (or the reverse) breaks the modifier
    elif item.socket_type == "NodeSocketBool":
        value = bool(value)
    mod[item.identifier] = value
    lens.update_tag(refresh={"DATA"})    # writing an ID property does not notify the depsgraph


def set_lens(lens, values):
    for name, value in values.items():
        set_input(lens, name, value)


# ----------------------------------------------------------------------------- shader nodes

class Nodes:
    """Writes a node tree as nested calls: n.math("ADD", a, b) returns the new node's output socket.
    An argument is either a socket (it gets linked) or a plain value (it becomes the default)."""

    def __init__(self, tree):
        self.tree = tree
        self.count = 0

    def new(self, idname, **props):
        node = self.tree.nodes.new(idname)
        for key, value in props.items():
            setattr(node, key, value)
        column, row = divmod(self.count, 8)
        node.location = (column * 220.0 - 1800.0, 600.0 - row * 170.0)
        self.count += 1
        return node

    def feed(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        elif socket.type == "VECTOR" and isinstance(value, (int, float)):
            socket.default_value = (value, value, value)
        elif socket.type == "RGBA" and len(value) == 3:
            socket.default_value = (*value, 1.0)
        else:
            socket.default_value = value

    def math(self, op, a, b=0.0):
        node = self.new("ShaderNodeMath", operation=op)
        self.feed(node.inputs[0], a)
        self.feed(node.inputs[1], b)
        return node.outputs[0]

    def vec(self, op, a, b=None, scale=None):
        node = self.new("ShaderNodeVectorMath", operation=op)
        self.feed(node.inputs[0], a)
        if b is not None:
            self.feed(node.inputs[1], b)
        if scale is not None:
            self.feed(node.inputs["Scale"], scale)
        return node.outputs["Value"] if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else node.outputs["Vector"]

    def xyz(self, vector):
        node = self.new("ShaderNodeSeparateXYZ")
        self.feed(node.inputs[0], vector)
        return node.outputs[0], node.outputs[1], node.outputs[2]

    def mix(self, factor, a, b):
        node = self.new("ShaderNodeMix", data_type="RGBA")
        inputs = {s.identifier: s for s in node.inputs}
        self.feed(inputs["Factor_Float"], factor)
        self.feed(inputs["A_Color"], a)
        self.feed(inputs["B_Color"], b)
        return {s.identifier: s for s in node.outputs}["Result_Color"]

    def group(self, group, **inputs):
        node = self.new("ShaderNodeGroup", node_tree=group)
        for name, value in inputs.items():
            self.feed(node.inputs[name], value)
        return node.outputs[0]

    def uv(self):
        return self.new("ShaderNodeUVMap", uv_map="UVMap").outputs["UV"]


def shader_group(name, inputs, outputs):
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for socket_name, kind in inputs:
        group.interface.new_socket(socket_name, in_out="INPUT", socket_type=kind)
    for socket_name, kind in outputs:
        group.interface.new_socket(socket_name, in_out="OUTPUT", socket_type=kind)
    n = Nodes(group)
    return group, n, n.new("NodeGroupInput"), n.new("NodeGroupOutput")


def make_grid_lines():
    """Lab - Grid Lines: 1 on the lines of a square grid of UV (in metres), 0 between them."""
    group, n, gin, gout = shader_group(
        "Lab - Grid Lines",
        [("Vector", "NodeSocketVector"), ("Spacing", "NodeSocketFloat"), ("Width", "NodeSocketFloat")],
        [("Line", "NodeSocketFloat")])
    spacing = gin.outputs["Spacing"]
    cells = n.vec("SCALE", gin.outputs["Vector"], scale=n.math("DIVIDE", 1.0, spacing))
    offset = n.vec("SUBTRACT", n.vec("FRACTION", n.vec("ADD", cells, 0.5)), 0.5)
    distance = n.vec("SCALE", n.vec("ABSOLUTE", offset), scale=spacing)   # metres to the nearest line, per axis
    dx, dy, _ = n.xyz(distance)
    line = n.math("LESS_THAN", n.math("MINIMUM", dx, dy), n.math("MULTIPLY", gin.outputs["Width"], 0.5))
    group.links.new(line, gout.inputs["Line"])
    return group


def make_graph_paper(grid_lines):
    """Lab - Graph Paper: fine lines every 0.1 m, stronger ones every 0.5 m, bold ones every metre."""
    group, n, gin, gout = shader_group(
        "Lab - Graph Paper",
        [("Vector", "NodeSocketVector"), ("Paper", "NodeSocketColor"), ("Ink", "NodeSocketColor")],
        [("Color", "NodeSocketColor")])
    uv = gin.outputs["Vector"]
    fine = n.math("MULTIPLY", n.group(grid_lines, Vector=uv, Spacing=0.1, Width=0.006), 0.5)
    mid = n.math("MULTIPLY", n.group(grid_lines, Vector=uv, Spacing=0.5, Width=0.012), 0.8)
    bold = n.group(grid_lines, Vector=uv, Spacing=1.0, Width=0.024)
    ink = n.math("MAXIMUM", n.math("MAXIMUM", fine, mid), bold)
    group.links.new(n.mix(ink, gin.outputs["Paper"], gin.outputs["Ink"]), gout.inputs["Color"])
    return group


def material(name):
    mat = bpy.data.materials.new(name)
    mat.node_tree.nodes.clear()
    n = Nodes(mat.node_tree)
    return mat, n, n.new("ShaderNodeOutputMaterial")


def surface(mat, n, out, color, roughness=0.8, metallic=0.0):
    bsdf = n.new("ShaderNodeBsdfPrincipled")
    n.feed(bsdf.inputs["Base Color"], color)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    mat.node_tree.links.new(bsdf.outputs[0], out.inputs["Surface"])
    mat.diffuse_color = (*color, 1.0) if isinstance(color, tuple) else mat.diffuse_color   # solid view colour
    return mat


def emitter(name, color, strength, sampling):
    mat, n, out = material(name)
    emission = n.new("ShaderNodeEmission")
    n.feed(emission.inputs["Color"], color)
    emission.inputs["Strength"].default_value = strength
    mat.node_tree.links.new(emission.outputs[0], out.inputs["Surface"])
    mat.cycles.emission_sampling = sampling
    return mat


def make_materials():
    grid_lines = make_grid_lines()
    graph_paper = make_graph_paper(grid_lines)
    mats = {}

    for wall, (paper, ink) in GRAPH_PAPER.items():
        mat, n, out = material("Lab Graph Paper (%s wall)" % wall)
        surface(mat, n, out, n.group(graph_paper, Vector=n.uv(), Paper=paper, Ink=ink), roughness=0.85)
        mats[wall] = mat

    # The chart wall: a Siemens star in every cell, on white with faint cell lines.
    mat, n, out = material("Lab Siemens Chart")
    local = n.vec("SUBTRACT", n.vec("FRACTION", n.vec("SCALE", n.uv(), scale=1.0 / CELL)), (0.5, 0.5, 0.0))
    lx, ly, _ = n.xyz(local)
    radius = n.math("MULTIPLY", n.vec("LENGTH", local), CELL)
    turns = n.math("MULTIPLY", n.math("ARCTAN2", ly, lx), STAR_SPOKE_PAIRS / (2.0 * math.pi))
    spokes = n.math("MULTIPLY", n.math("LESS_THAN", n.math("FRACT", turns), 0.5),
                    n.math("LESS_THAN", radius, STAR_RADIUS))
    ring = n.math("MULTIPLY", n.math("GREATER_THAN", radius, STAR_RADIUS),
                  n.math("LESS_THAN", radius, STAR_RADIUS + 0.008))
    paper = n.mix(n.math("MULTIPLY", n.group(grid_lines, Vector=n.uv(), Spacing=CELL, Width=0.005), 0.5),
                  WHITE, (0.1, 0.1, 0.1))
    surface(mat, n, out, n.mix(n.math("MAXIMUM", spokes, ring), paper, BLACK), roughness=0.7)
    mats["front"] = mat

    mat, n, out = material("Lab Checker Floor")
    checker = n.new("ShaderNodeTexChecker")
    n.feed(checker.inputs["Vector"], n.uv())
    checker.inputs["Scale"].default_value = 1.0 / CELL      # squares of CELL metres
    n.feed(checker.inputs["Color1"], WHITE)
    n.feed(checker.inputs["Color2"], BLACK)
    surface(mat, n, out, checker.outputs["Color"], roughness=0.4)
    mats["floor"] = mat

    mat, n, out = material("Lab Ceiling Tiles")
    lines = n.group(grid_lines, Vector=n.uv(), Spacing=CELL, Width=0.03)
    surface(mat, n, out, n.mix(lines, (0.40, 0.40, 0.40), (0.05, 0.05, 0.05)), roughness=0.9)
    mats["ceiling"] = mat

    # The protractor band: black, with a white line at eye height (the horizon of a level camera) and
    # white ticks hanging from it at every 5 degrees of angle from the lens axis, seen from the
    # protractor's centre. The ticks at the numbers (every LABEL_STEP) are longer and wider.
    mat, n, out = material("Lab Protractor Band")
    px, py, pz = n.xyz(n.new("ShaderNodeNewGeometry").outputs["Position"])
    azimuth = n.math("MULTIPLY", n.math("ARCTAN2", n.math("SUBTRACT", px, PROTRACTOR[0]),
                                        n.math("SUBTRACT", py, PROTRACTOR[1])), 180.0 / math.pi)
    below = n.math("SUBTRACT", EYE, pz)          # metres below the horizon line

    def ticks(step, half_width, length):
        steps = n.math("ADD", n.math("DIVIDE", azimuth, step), 0.5)
        off = n.math("MULTIPLY", n.math("ABSOLUTE", n.math("SUBTRACT", n.math("FRACT", steps), 0.5)), step)
        hangs = n.math("MULTIPLY", n.math("GREATER_THAN", below, -0.004), n.math("LESS_THAN", below, length))
        return n.math("MULTIPLY", n.math("LESS_THAN", off, half_width), hangs)

    horizon = n.math("LESS_THAN", n.math("ABSOLUTE", below), 0.006)
    marks = n.math("MAXIMUM", n.math("MAXIMUM", ticks(5.0, 0.12, 0.04), ticks(float(LABEL_STEP), 0.22, 0.07)),
                   horizon)
    surface(mat, n, out, n.mix(marks, (0.012, 0.012, 0.012), (0.8, 0.8, 0.8)), roughness=0.6)
    mats["band"] = mat

    for name, color, roughness, metallic in (
            ("label", (0.8, 0.8, 0.8), 0.6, 0.0), ("plinth", (0.62, 0.62, 0.62), 0.55, 0.0),
            ("grey ball", (0.18, 0.18, 0.18), 0.6, 0.0), ("mirror ball", (0.92, 0.92, 0.92), 0.02, 1.0),
            ("board", BLACK, 0.5, 0.0), ("cord", BLACK, 0.5, 0.0)):
        mat, n, out = material("Lab %s" % name.title())
        surface(mat, n, out, color, roughness, metallic)
        mats[name] = mat

    mat, n, out = material("Lab ColorChecker Patches")
    surface(mat, n, out, n.new("ShaderNodeVertexColor", layer_name="Patch").outputs["Color"], roughness=0.9)
    mats["patches"] = mat

    mats["strip"] = emitter("Lab Strip Light", (1.0, 1.0, 1.0), 14.0, "FRONT")
    # The bulbs are there to be seen (and turned into bokeh), not to light the room.
    mat, n, out = material("Lab Bulb")
    blackbody = n.new("ShaderNodeBlackbody")
    blackbody.inputs["Temperature"].default_value = 2700.0
    emission = n.new("ShaderNodeEmission")
    n.feed(emission.inputs["Color"], blackbody.outputs[0])
    emission.inputs["Strength"].default_value = 40.0
    mat.node_tree.links.new(emission.outputs[0], out.inputs["Surface"])
    mat.cycles.emission_sampling = "NONE"
    mats["bulb"] = mat
    return mats


# ----------------------------------------------------------------------------- geometry

def add_object(name, mesh, mat, collection):
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def quad(name, corners, uv_of, mat, collection):
    """A one-face object. corners run counter-clockwise seen from the side that faces the room;
    uv_of(corner) gives the UV of a corner, in metres."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv.data[loop.index].uv = uv_of(corners[loop.vertex_index])
    return add_object(name, mesh, mat, collection)


def box(name, centre, size, mat, collection):
    (cx, cy, cz), (hx, hy, hz) = centre, (s * 0.5 for s in size)
    verts = [(cx + dx * hx, cy + dy * hy, cz + dz * hz) for dz in (-1, 1) for dy in (-1, 1) for dx in (-1, 1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    return add_object(name, mesh, mat, collection)


def from_bmesh(name, build, location, mat, collection, smooth=True):
    bm = bmesh.new()
    build(bm)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if smooth:
        mesh.shade_smooth()
    obj = add_object(name, mesh, mat, collection)
    obj.location = location
    return obj


def sphere(name, location, radius, mat, collection):
    return from_bmesh(name, lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=radius),
                      location, mat, collection)


def rod(name, location, radius, length, mat, collection):
    return from_bmesh(name, lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=radius,
                                                             radius2=radius, depth=length),
                      location, mat, collection)


# Where a level ray from the tripod meets the walls, and how text on each wall is turned.
WALL_NORMAL = {"front": (0.0, -1.0), "back": (0.0, 1.0), "left": (1.0, 0.0), "right": (-1.0, 0.0)}
WALL_TURN = {"front": 0.0, "back": 180.0, "left": 90.0, "right": -90.0}


def wall_point(azimuth):
    """Where a level ray from the protractor's centre meets the walls: (x, y, wall)."""
    s, c = math.sin(math.radians(azimuth)), math.cos(math.radians(azimuth))
    ox, oy = PROTRACTOR
    hits = []
    if c > 1e-9:
        hits.append(((FRONT - oy) / c, "front"))
    if c < -1e-9:
        hits.append(((BACK - oy) / c, "back"))
    if s > 1e-9:
        hits.append(((HALF_WIDTH - ox) / s, "right"))
    if s < -1e-9:
        hits.append(((-HALF_WIDTH - ox) / s, "left"))
    t, wall = min(hits)
    return ox + t * s, oy + t * c, wall


def build_room(mats, collection):
    w, f, b, h = HALF_WIDTH, FRONT, BACK, HEIGHT
    quad("Floor", [(-w, b, 0), (w, b, 0), (w, f, 0), (-w, f, 0)], lambda p: (p[0], p[1]), mats["floor"], collection)
    quad("Ceiling", [(-w, b, h), (-w, f, h), (w, f, h), (w, b, h)], lambda p: (p[0], p[1]), mats["ceiling"], collection)
    quad("Chart Wall", [(-w, f, 0), (w, f, 0), (w, f, h), (-w, f, h)], lambda p: (p[0], p[2]), mats["front"], collection)
    quad("Back Wall", [(w, b, 0), (-w, b, 0), (-w, b, h), (w, b, h)], lambda p: (-p[0], p[2]), mats["back"], collection)
    quad("Left Wall", [(-w, b, 0), (-w, f, 0), (-w, f, h), (-w, b, h)], lambda p: (p[1], p[2]), mats["left"], collection)
    quad("Right Wall", [(w, f, 0), (w, b, 0), (w, b, h), (w, f, h)], lambda p: (-p[1], p[2]), mats["right"], collection)

    # The protractor band, 3 mm in front of each wall (the shader draws its marks from the position).
    lo, hi, e = EYE - BAND_BELOW, EYE + BAND_ABOVE, 0.003
    band_uv = lambda p: (0.0, 0.0)
    quad("Band Front", [(-w, f - e, lo), (w, f - e, lo), (w, f - e, hi), (-w, f - e, hi)], band_uv, mats["band"], collection)
    quad("Band Back", [(w, b + e, lo), (-w, b + e, lo), (-w, b + e, hi), (w, b + e, hi)], band_uv, mats["band"], collection)
    quad("Band Left", [(-w + e, b, lo), (-w + e, f, lo), (-w + e, f, hi), (-w + e, b, hi)], band_uv, mats["band"], collection)
    quad("Band Right", [(w - e, f, lo), (w - e, b, lo), (w - e, b, hi), (w - e, f, hi)], band_uv, mats["band"], collection)

    # A white number on the band above every LABEL_STEP degrees, left and right alike.
    for azimuth in range(-180 + LABEL_STEP, 181, LABEL_STEP):
        x, y, wall = wall_point(azimuth)
        nx, ny = WALL_NORMAL[wall]
        curve = bpy.data.curves.new("Label %d" % azimuth, "FONT")
        curve.body = "%d\u00b0" % abs(azimuth)
        curve.size = 0.17
        curve.align_x = "CENTER"
        curve.materials.append(mats["label"])
        label = bpy.data.objects.new(curve.name, curve)
        label.location = (x + nx * 0.006, y + ny * 0.006, EYE + 0.045)
        label.rotation_euler = (math.radians(90.0), 0.0, math.radians(WALL_TURN[wall]))
        collection.objects.link(label)


def build_props(mats, collection):
    y, top = 2.6, 0.75
    box("Plinth Grey Ball", (-0.6, y, top / 2), (0.3, 0.3, top), mats["plinth"], collection)
    box("Plinth Chart", (0.0, y, top / 2), (0.5, 0.3, top), mats["plinth"], collection)
    box("Plinth Mirror Ball", (0.6, y, top / 2), (0.3, 0.3, top), mats["plinth"], collection)
    sphere("Grey Ball", (-0.6, y, top + 0.12), 0.12, mats["grey ball"], collection)
    sphere("Mirror Ball", (0.6, y, top + 0.12), 0.12, mats["mirror ball"], collection)

    # The ColorChecker: 6 x 4 patches on a black board standing on the middle plinth.
    patch, gap = 0.068, 0.012
    width, height = 6 * patch + 7 * gap, 4 * patch + 5 * gap
    box("ColorChecker Board", (0.0, y, top + height / 2), (width, 0.012, height), mats["board"], collection)
    verts, faces = [], []
    front = y - 0.007
    for index in range(24):
        row, col = divmod(index, 6)
        x0 = -width / 2 + gap + col * (patch + gap)
        z1 = top + height - gap - row * (patch + gap)
        base = len(verts)
        verts += [(x0, front, z1 - patch), (x0 + patch, front, z1 - patch), (x0 + patch, front, z1), (x0, front, z1)]
        faces.append((base, base + 1, base + 2, base + 3))
    mesh = bpy.data.meshes.new("ColorChecker Patches")
    mesh.from_pydata(verts, [], faces)
    colors = mesh.color_attributes.new("Patch", "FLOAT_COLOR", "CORNER")
    for poly in mesh.polygons:
        rgb = [((c / 255.0) / 12.92 if c / 255.0 <= 0.04045 else ((c / 255.0 + 0.055) / 1.055) ** 2.4)
               for c in COLOR_CHECKER[poly.index]]
        for loop_index in poly.loop_indices:
            colors.data[loop_index].color = (*rgb, 1.0)
    add_object("ColorChecker Patches", mesh, mats["patches"], collection)


def build_lights(mats, collection):
    # Three strip lights along the room, just under the ceiling, facing down.
    for i, x in enumerate((-2.4, 0.0, 2.4)):
        z, hw = HEIGHT - 0.02, 0.07
        quad("Strip Light %d" % (i + 1), [(x - hw, BACK + 0.6, z), (x - hw, FRONT - 0.6, z), (x + hw, FRONT - 0.6, z),
                                          (x + hw, BACK + 0.6, z)],
             lambda p: (p[0], p[1]), mats["strip"], collection)
    # A row of small bulbs on cords, between the plinths and the chart. They only show themselves (to the
    # camera and in the mirror ball) and light nothing, so they add no noise.
    radius = 0.05
    for i, (x, z) in enumerate(((-2.4, 2.25), (-1.2, 2.45), (0.0, 2.15), (1.2, 2.45), (2.4, 2.25))):
        bulb = sphere("Bulb %d" % (i + 1), (x, 3.8, z), radius, mats["bulb"], collection)
        for attr in ("visible_diffuse", "visible_transmission", "visible_volume_scatter", "visible_shadow"):
            setattr(bulb, attr, False)
        length = HEIGHT - z - radius
        rod("Cord %d" % (i + 1), (x, 3.8, z + radius + length / 2), 0.003, length, mats["cord"], collection)


# ----------------------------------------------------------------------------- the rig and the scene

def append_rig(scene):
    with bpy.data.libraries.load(RIG_BLEND, link=False) as (src, dst):
        if RIG_COLLECTION not in src.collections:
            raise RuntimeError("%s has no %r collection" % (RIG_BLEND, RIG_COLLECTION))
        dst.collections = [RIG_COLLECTION]
        dst.materials = [m for m in src.materials if m == "Lens Glass (Refraction)"]
    scene.collection.children.link(dst.collections[0])
    for mat in dst.materials:
        mat.use_fake_user = True     # the modifier's other Glass Material; keep it in the file
    camera, lens = bpy.data.objects[CAMERA_OBJECT], bpy.data.objects[LENS_OBJECT]

    camera.location = (PROTRACTOR[0], PROTRACTOR[1] - CAMERA_BACK, EYE)
    camera.rotation_euler = (math.radians(90.0), 0.0, 0.0)     # level, looking along +Y
    cam = camera.data
    cam.type, cam.lens, cam.sensor_width, cam.sensor_fit = "PERSP", 50.0, 36.0, "AUTO"
    cam.shift_x = cam.shift_y = 0.0
    cam.clip_start, cam.clip_end = 0.01, 100.0
    cam.dof.use_dof = False              # the lens has its own aperture
    scene.camera = camera
    set_lens(lens, LAB_LENS)
    return camera, lens


def setup_scene(scene):
    scene.frame_start = scene.frame_end = scene.frame_current = 1
    scene.render.engine = "CYCLES"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1600, 900, 100
    scene.render.use_compositing = False
    cy = scene.cycles
    cy.device = "GPU"                    # used when the preferences have a GPU; otherwise Cycles falls back to the CPU
    cy.samples, cy.use_adaptive_sampling, cy.adaptive_threshold = 512, True, 0.01
    cy.use_denoising, cy.denoiser = True, "OPENIMAGEDENOISE"
    cy.filter_width = 1.5
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces = 8, 4, 4
    cy.transmission_bounces, cy.transparent_max_bounces, cy.volume_bounces = 8, 8, 0
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.sample_clamp_indirect = 10.0
    view = scene.view_settings
    view.view_transform, view.look, view.exposure, view.gamma = "AgX", "AgX - Medium High Contrast", 0.0, 1.0

    world = bpy.data.worlds.new("Lab World")
    world.color = (0.0, 0.0, 0.0)
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs["Strength"].default_value = 0.0
    scene.world = world


def look_through_camera():
    """Open lab.blend looking through the camera, like Numpad 0."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.region_3d.view_perspective = "CAMERA"


def forget_local_folders():
    """The startup file's file browsers open on the user's Documents folder, which would be saved into
    lab.blend. Blank them. The whole buffer is filled first, because a .blend keeps the old text that
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


def lens_messages(lens):
    bpy.context.view_layer.update()
    return [(w.type, w.message) for w in lens.modifiers[LENS_MODIFIER].node_warnings]


def clear_startup_file():
    """Remove what Blender's startup file brings: the cube, light and camera, their data, the collection."""
    for blocks in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights,
                   bpy.data.collections):
        for block in list(blocks):
            blocks.remove(block)


def main():
    clear_startup_file()
    bpy.context.preferences.filepaths.save_version = 0   # the script rebuilds lab.blend, so no .blend1
    scene = bpy.context.scene
    setup_scene(scene)
    mats = make_materials()
    collections = {}
    for name in ("Lab Room", "Lab Props", "Lab Lights"):
        collections[name] = bpy.data.collections.new(name)
        scene.collection.children.link(collections[name])
    build_room(mats, collections["Lab Room"])
    build_props(mats, collections["Lab Props"])
    build_lights(mats, collections["Lab Lights"])
    camera, lens = append_rig(scene)
    look_through_camera()
    forget_local_folders()
    for kind, message in lens_messages(lens):
        print("lens %s: %s" % (kind.lower(), message))
    bpy.ops.wm.save_as_mainfile(filepath=LAB_BLEND, compress=True)
    print("wrote", LAB_BLEND)


if __name__ == "__main__":
    main()
