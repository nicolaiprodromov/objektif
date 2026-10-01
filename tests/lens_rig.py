"""Shared by the test scripts: where they write, and the lens modifier's inputs by name.

The scripts run inside Blender on objektif.blend, for example from this folder:

    blender -b ..\\objektif.blend -P test_pattern_layouts.py

Blender does not put a script's folder on sys.path, so each script adds its own folder
before it imports this module.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERS = os.path.join(HERE, "renders", "noise")    # finished pictures, shown in README.md
SCRATCH = os.path.join(HERE, "renders", "scratch")  # intermediate EXR / PNG files, ignored by git
_OUT = os.environ.get("OBJEKTIF_TEST_OUT")          # set it to keep the committed pictures untouched
if _OUT:
    RENDERS, SCRATCH = os.path.join(_OUT, "noise"), os.path.join(_OUT, "scratch")
for _folder in (RENDERS, SCRATCH):
    os.makedirs(_folder, exist_ok=True)

LENS_OBJECT = "Physical Lens"          # the lens object in objektif.blend
LENS_MODIFIER = "Physical Lens Rig"    # its Geometry Nodes modifier
ATTR_CELL = "lens_sensor_cell"         # the attribute that carries Cell Size to the glass material

_CAST = {"NodeSocketFloat": float, "NodeSocketInt": int, "NodeSocketBool": bool}


def plain_render(scene):
    """Switch off the parts of objektif.blend's look that would change what a test measures:
    its compositor (denoise, glare, sensor noise), the camera's own depth of field (it moves
    rays off their sensor cells; the rig warns about it) and the Raw view transform (PNG files
    would hold linear values instead of display colours)."""
    scene.render.use_compositing = False
    scene.camera.data.dof.use_dof = False
    view = scene.view_settings
    view.view_transform, view.look, view.exposure, view.gamma = "Standard", "None", 0.0, 1.0


def _inputs(tree):
    return {item.name: item for item in tree.interface.items_tree
            if item.item_type == "SOCKET" and item.in_out == "INPUT"}


def _menu_items(tree, identifier):
    """{item name: stored value} of a menu input. The modifier stores the integer id of the
    chosen item; the names live on the Menu Switch node that the input feeds."""
    for node in tree.nodes:
        if node.bl_idname != "GeometryNodeMenuSwitch":
            continue
        for link in node.inputs["Menu"].links:
            if link.from_node.bl_idname == "NodeGroupInput" and link.from_socket.identifier == identifier:
                return {s.name: int(s.identifier.split("_")[1]) for s in node.inputs
                        if s.identifier.startswith("Item_")}
    return {}


def set_input(lens, name, value):
    """Set an input of the lens modifier by name. Menus take the item name:
    set_input(lens, "Colour Sampling", "Mono")."""
    mod = lens.modifiers[LENS_MODIFIER]
    tree = mod.node_group
    items = _inputs(tree)
    if name not in items:
        raise KeyError("the lens modifier has no input %r; it has: %s" % (name, ", ".join(items)))
    item = items[name]
    if item.socket_type == "NodeSocketMenu" and isinstance(value, str):
        choices = _menu_items(tree, item.identifier)
        if value not in choices:
            raise KeyError("%r is not an item of the %r menu; it has: %s" % (value, name, ", ".join(choices)))
        value = choices[value]
    elif item.socket_type in _CAST:
        value = _CAST[item.socket_type](value)   # an int written into a float input breaks the modifier
    mod[item.identifier] = value
    lens.update_tag(refresh={"DATA"})    # writing an ID property does not notify the depsgraph
