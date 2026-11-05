"""Renders the product shot of showcase.blend into ../docs/showcase.jpg.

    blender -b showcase.blend -P render_showcase.py
    options: --scale 50 (percent of 1920 x 1080)   --samples 64   --gpu 0 (render on that GPU only)   --out FILE

The picture is written as JPEG, quality 92.
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, os.pardir, "docs", "showcase.jpg"))


def use_gpu(index=None):
    """Render on the GPU when there is one (all of them, or only the one at `index`)."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.refresh_devices()
        # prefs.devices keeps entries for GPUs that are gone; picking one makes Cycles fall back to the CPU.
        gpus = [d for d in prefs.get_devices_for_type(kind) if d.type == kind]
        if not gpus:
            continue
        if index is not None and not 0 <= index < len(gpus):
            raise SystemExit("--gpu %d: there are %d %s devices (0 to %d)" % (index, len(gpus), kind, len(gpus) - 1))
        for device in prefs.devices:
            device.use = False
        for device in (gpus if index is None else [gpus[index]]):
            device.use = True
        return "%s: %s" % (kind, ", ".join(d.name for d in gpus if d.use))
    return None


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    scale, samples, gpu, out = 100, None, None, OUT
    while args:
        arg = args.pop(0)
        if arg not in ("--scale", "--samples", "--gpu", "--out") or not args:
            raise SystemExit("unknown option %r (see the docstring)" % arg)
        value = args.pop(0)
        if arg == "--out":
            out = os.path.abspath(value)
            continue
        try:
            number = int(value)
        except ValueError:
            raise SystemExit("%s needs a whole number, not %r" % (arg, value))
        if arg == "--scale":
            scale = number
        elif arg == "--samples":
            samples = number
        else:
            gpu = number

    scene = bpy.context.scene
    # The picture file must not record the blend's path or this computer's name.
    scene.render.use_stamp_filename = False
    scene.render.use_stamp_hostname = False
    device = use_gpu(gpu)
    scene.cycles.device = "GPU" if device else "CPU"
    scene.cycles.denoising_use_gpu = bool(device)
    print("rendering on", device or "the CPU")
    scene.render.resolution_percentage = scale
    if samples:
        scene.cycles.samples = samples
    settings = scene.render.image_settings
    settings.file_format, settings.color_mode, settings.quality = "JPEG", "RGB", 92
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
