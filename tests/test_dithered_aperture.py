"""Throw-away prototype: depth of field INSIDE the lens, sampled deterministically.

The camera stays a pinhole. The existing shader traces the pixel's ray through
the glass and knows where it leaves the front face (Q) and in which direction
(D2). This prototype adds:

  * a FOCUS POINT in the world:  W = Q + D2 * Focus Distance
  * an APERTURE on the front element: for every pixel ONE point Q' on a disc
    around Q, chosen from the pixel's 4x4 Bayer-matrix index (16 points on a
    golden-angle spiral) - nothing is random, so at 1 spp the blur is an
    ordered dither pattern instead of noise
  * the portal ray then leaves from Q' toward W

First attempt (kept in the chat, not here): aim the bundle at a focus plane in
the camera's own space, exactly like Cycles' DOF. The bowl is a strong negative
element (about -86 mm), so the camera-space focus that puts the WORLD in focus
is ~0.18 m, not 3.8 m, and the beam that gets through is 0.46x the aperture: a
180-degree fisheye simply has (almost) infinite depth of field. That is real
physics; to get a *visible* blur through this lens the aperture has to be
larger than the glass allows, which is why the disc lives on the front element
here and nothing blocks it. Modified in memory only; nothing is saved.

  G  mono (one white portal)      + dithered aperture, 1 spp
  H  RGGB colour filter array     + dithered aperture, 1 spp
  I  same as H at 16 spp (the pattern is stable, only the lighting grain goes)

Arguments after "--":  aperture=<mm>  focus=<m>  tag=<prefix>
Output PNGs go to renders/noise/.

This prototype is now the rig's Aperture panel. It patches the portal group as it was
before that panel existed, so on objektif.blend it stops with a message; G, H and I in
renders/noise/ are what it rendered.
"""
import bpy, os, math, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rig import RENDERS as OUT, plain_render

scene = bpy.context.scene
RX, RY = 1280, 720
APERTURE_MM = 40.0     # radius of the sampling disc on the front element
FOCUS = 3.7            # metres, from the front of the lens
GOLDEN = 2.39996323    # golden angle, radians
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
for a in ARGS:
    key, _, val = a.partition("=")
    if key == "aperture":
        APERTURE_MM = float(val)
    elif key == "focus":
        FOCUS = float(val)
TAG = next((a[4:] for a in ARGS if a.startswith("tag=")), "")

scene.cycles.samples = 1
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
plain_render(scene)                      # objektif.blend: compositor, camera DOF and Raw view off
scene.cycles.time_limit = 0
scene.render.resolution_x = RX
scene.render.resolution_y = RY
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"

lens = bpy.data.objects["Physical Lens"]
mod = lens.modifiers["Physical Lens Rig"]
ids = {item.name: item.identifier for item in mod.node_group.interface.items_tree
       if getattr(item, "in_out", None) == "INPUT"}
d = float(mod[ids["Distance"]])
tx, ty = float(mod[ids["Frame Half Width"]]), float(mod[ids["Frame Half Height"]])
BOWL_RADIUS = d * math.hypot(tx, ty)                      # Full Frame format: circle through the corners
R_AP = APERTURE_MM / 1000.0
print("bowl radius %.4f m (front element %.4f m), aperture radius %.4f m, focus %.1f m"
      % (BOWL_RADIUS, 2 * BOWL_RADIUS, R_AP, FOCUS))


def render(name):
    scene.render.filepath = os.path.join(OUT, TAG + name)
    bpy.ops.render.render(write_still=True)


class T:
    """Tiny node helper for a shader tree."""
    def __init__(self, tree):
        self.n, self.l = tree.nodes, tree.links

    def _feed(self, node, idx, val):
        sock = node.inputs[idx]
        if isinstance(val, bpy.types.NodeSocket):
            self.l.new(val, sock)
        elif val is not None:
            sock.default_value = val

    def math(self, op, a, b=None, c=None):
        n = self.n.new("ShaderNodeMath"); n.operation = op
        self._feed(n, 0, a); self._feed(n, 1, b); self._feed(n, 2, c)
        return n.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        n = self.n.new("ShaderNodeVectorMath"); n.operation = op
        self._feed(n, 0, a); self._feed(n, 1, b)
        if scale is not None:
            self._feed(n, "Scale", scale)
        return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH") else n.outputs[0]

    def xyz(self, x, y, z):
        n = self.n.new("ShaderNodeCombineXYZ")
        self._feed(n, 0, x); self._feed(n, 1, y); self._feed(n, 2, z)
        return n.outputs[0]

    def sep(self, v):
        n = self.n.new("ShaderNodeSeparateXYZ"); self.l.new(v, n.inputs[0])
        return n.outputs

    def pixel_index(self):
        tc = self.n.new("ShaderNodeTexCoord")
        w = self.sep(tc.outputs["Window"])
        px = self.math("FLOOR", self.math("MULTIPLY", w["X"], float(RX)))
        py = self.math("FLOOR", self.math("MULTIPLY", w["Y"], float(RY)))
        return px, py

    def bayer_digits(self, px, py):
        """m0, m1: the two base-4 digits of the 4x4 Bayer matrix at this pixel."""
        def M2(a, b):  # 2x2 Bayer: [[0,2],[3,1]]
            return self.math("MULTIPLY_ADD", self.math("MODULO", self.math("ADD", a, b), 2.0), 2.0, b)
        x0, y0 = self.math("MODULO", px, 2.0), self.math("MODULO", py, 2.0)
        x1 = self.math("MODULO", self.math("FLOOR", self.math("DIVIDE", px, 2.0)), 2.0)
        y1 = self.math("MODULO", self.math("FLOOR", self.math("DIVIDE", py, 2.0)), 2.0)
        return M2(x0, y0), M2(x1, y1)


# ---------------------------------------------------------------------------
# 1. Aperture sampling inside the portal group (shared by the three colours)
# ---------------------------------------------------------------------------
pg = bpy.data.node_groups["Lens - Refraction Portal (one colour)"]
_missing = [label for label in ("Q: exit point", "D2: back into air", "Q + eps * D2", "exit direction (world)")
            if not any(n.label == label for n in pg.nodes)]
if _missing:
    raise SystemExit("test_dithered_aperture.py: the portal group has no %s node. This prototype patches the group "
                     "from before the Aperture panel existed; the panel is this prototype, built in (Depth of Field, "
                     "Aperture Radius, Focus Distance)." % " / ".join(repr(m) for m in _missing))
t = T(pg)
Q_sock = [n for n in pg.nodes if n.label == "Q: exit point"][0].outputs[0]        # object space
D2_sock = [n for n in pg.nodes if n.label == "D2: back into air"][0].outputs[0]   # object space, unit
start = [n for n in pg.nodes if n.label == "Q + eps * D2"][0]                    # MULTIPLY_ADD(D2, eps, Q)
dir_w = [n for n in pg.nodes if n.label == "exit direction (world)"][0]          # Vector Transform of D2

px, py = t.pixel_index()
m0, m1 = t.bayer_digits(px, py)
# aperture index = digit-reversed Bayer index, so every colour class of the CFA
# (which uses the high digit) still spreads over the whole aperture
i_ap = t.math("MULTIPLY_ADD", m1, 4.0, m0)
r = t.math("MULTIPLY", t.math("SQRT", t.math("DIVIDE", t.math("ADD", i_ap, 0.5), 16.0)), R_AP)
th = t.math("MULTIPLY", i_ap, GOLDEN)
offset = t.xyz(t.math("MULTIPLY", r, t.math("COSINE", th)), t.math("MULTIPLY", r, t.math("SINE", th)), 0.0)

# world focus point on this pixel's chief ray, aperture point on the (flat) front face
W = t.vmath("MULTIPLY_ADD", D2_sock, t.xyz(FOCUS, FOCUS, FOCUS))
pg.links.new(Q_sock, W.node.inputs[2])
Qp = t.vmath("ADD", Q_sock, offset)
D2p = t.vmath("NORMALIZE", t.vmath("SUBTRACT", W, Qp))

# the portal now leaves from Q' toward W
pg.links.new(D2p, start.inputs[0])
pg.links.new(Qp, start.inputs[2])
pg.links.new(D2p, dir_w.inputs[0])

# ---------------------------------------------------------------------------
# 2. Material: G = one white portal, H/I = RGGB colour filter array
# ---------------------------------------------------------------------------
mat = bpy.data.materials["Lens Glass (Portal)"]
m = T(mat.node_tree)
portals = {n.label.split(" - ")[-1]: n for n in mat.node_tree.nodes
           if n.type == "GROUP" and n.node_tree is pg}
final_mix = [n for n in mat.node_tree.nodes if n.type == "MIX_SHADER" and n.label.startswith("bowl -> portal")][0]

portals["green"].inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
mat.node_tree.links.new(portals["green"].outputs["Shader"], final_mix.inputs[2])
render("G_lens_dof_bayer4x4_mono_1spp.png")

portals["red"].inputs["Color"].default_value = (4.0, 0.0, 0.0, 1.0)
portals["green"].inputs["Color"].default_value = (0.0, 2.0, 0.0, 1.0)
portals["blue"].inputs["Color"].default_value = (0.0, 0.0, 4.0, 1.0)
px2, py2 = m.pixel_index()
m0c, _ = m.bayer_digits(px2, py2)          # high digit of the Bayer index: 0 = R, 1 = B, 2/3 = G  -> RGGB
is_red = m.math("LESS_THAN", m0c, 0.5)
is_blue = m.math("MULTIPLY", m.math("GREATER_THAN", m0c, 0.5), m.math("LESS_THAN", m0c, 1.5))
mix1 = mat.node_tree.nodes.new("ShaderNodeMixShader")
mat.node_tree.links.new(is_red, mix1.inputs[0])
mat.node_tree.links.new(portals["green"].outputs["Shader"], mix1.inputs[1])
mat.node_tree.links.new(portals["red"].outputs["Shader"], mix1.inputs[2])
mix2 = mat.node_tree.nodes.new("ShaderNodeMixShader")
mat.node_tree.links.new(is_blue, mix2.inputs[0])
mat.node_tree.links.new(mix1.outputs[0], mix2.inputs[1])
mat.node_tree.links.new(portals["blue"].outputs["Shader"], mix2.inputs[2])
mat.node_tree.links.new(mix2.outputs[0], final_mix.inputs[2])
render("H_lens_dof_bayer4x4_rggb_1spp.png")

scene.cycles.samples = 16
render("I_lens_dof_bayer4x4_rggb_16spp.png")
