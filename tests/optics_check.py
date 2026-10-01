"""
optics_check.py - meridional ray tracer for the Physical Lens Rig.

Traces rays that leave Blender's pinhole camera (at the origin, looking down -Z)
through the glass element exactly as the geometry-nodes modifier builds it, and
reports the mapping

    camera angle (what the camera "thinks" it looks at)
        -> world angle (where the ray really goes after the lens)

so you can design a lens shape before rendering. Run with plain Python:

    python optics_check.py                     # tables for four example designs
    python optics_check.py 150 Circular 35     # Field of View 150 deg, Circular format, 35 mm camera
    python optics_check.py stress              # check that no ray can hit the blackened rim

design() takes the modifier's inputs: fov (Field of View, degrees), fmt (Format:
"Circular", "Full Frame" or "Custom"), custom (Image Circle), distance (Distance),
front_dome (Front Dome) and ior (Refractive Index), plus the camera (focal_mm,
sensor_mm, res). The bowl curvature is solved from them, as the node group does.
Camera half-angles for a 36 mm sensor: 50 mm -> 13.4 (vertical, 16:9), 19.8
(horizontal), 23.4 (diagonal); 35 mm -> 18.3 / 27.2 / 31.7; 24 mm -> 25.7 / 36.9 / 41.9.
"""
import math
import sys

# ----------------------------------------------------------------------------- core

def sag(c, r):
    """Height of a spherical surface with curvature c = 1/R at radial distance r."""
    a = 1.0 - c * c * r * r
    if a < 0.0:
        a = 0.0
    return c * r * r / (1.0 + math.sqrt(a))


def intersect_surface(p, d, z_vertex, R):
    """Return the hit point of ray p + s*d with a spherical (or flat) surface.

    The surface has its vertex at (0, z_vertex). R follows the sign convention
    from the module docstring (R == 0 means a flat surface).
    Returns (hit_point, unit_normal_toward_camera_side) or None.
    """
    px, pz = p
    dx, dz = d
    if R == 0.0:
        if abs(dz) < 1e-12:
            return None
        s = (z_vertex - pz) / dz
        if s <= 1e-9:
            return None
        return (px + s * dx, pz + s * dz), (0.0, 1.0)

    cz = z_vertex + R                      # centre of curvature
    # |p + s d - c|^2 = R^2
    ox, oz = px, pz - cz
    b = 2.0 * (ox * dx + oz * dz)
    cc = ox * ox + oz * oz - R * R
    disc = b * b - 4.0 * cc
    if disc < 0.0:
        return None
    sq = math.sqrt(disc)
    best = None
    for s in ((-b - sq) * 0.5, (-b + sq) * 0.5):
        if s <= 1e-9:
            continue
        hz = pz + s * dz
        # keep only the hemisphere that contains the vertex
        if (hz - cz) * R < 0.0:
            if best is None or s < best:
                best = s
    if best is None:
        return None
    hx, hz = px + best * dx, pz + best * dz
    # unit normal from the hit point toward the centre of curvature (0, cz) ...
    nx, nz = -hx, cz - hz
    ln = math.hypot(nx, nz)
    nx, nz = nx / ln, nz / ln
    if R < 0.0:                            # ... flipped so it always faces the camera side (+z)
        nx, nz = -nx, -nz
    return (hx, hz), (nx, nz)


def refract(d, n, n1, n2):
    """Snell's law. d is the incoming direction, n the surface normal facing the
    incoming side. Returns the new direction or None on total internal reflection."""
    dx, dz = d
    nx, nz = n
    cos_i = -(dx * nx + dz * nz)
    if cos_i < 0.0:                        # normal was facing away, flip it
        nx, nz = -nx, -nz
        cos_i = -cos_i
    eta = n1 / n2
    k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
    if k < 0.0:
        return None
    f = eta * cos_i - math.sqrt(k)
    return (eta * dx + f * nx, eta * dz + f * nz)


# ----------------------------------------------------------------------------- design
# Fixed proportions baked into the node group (all relative to the bowl radius a):
THICKNESS_RATIO = 1.0     # glass thickness at the bowl rim  = a
OUTER_RATIO = 2.0         # outer semi-diameter of the puck  = 2 a
MIN_GLASS_RATIO = 0.05    # minimum glass left behind any surface
HEMISPHERE_LIMIT = 0.985  # curvature * semi-diameter never exceeds this


def camera_frame(focal_mm=50.0, sensor_mm=36.0, res=(1280, 720)):
    """Half-extents of the camera frame in tan-space (Blender AUTO sensor fit)."""
    w, h = res
    long_side = max(w, h)
    tan_long = sensor_mm / (2.0 * focal_mm)
    tx = tan_long * (w / long_side)
    ty = tan_long * (h / long_side)
    return tx, ty


def circle_radius(fmt, tx, ty, custom=1.5):
    """Image-circle radius in tan-space for a format."""
    if fmt == "Circular":
        return min(tx, ty)
    if fmt == "Full Frame":
        return math.hypot(tx, ty)
    return min(tx, ty) * custom


def geometry(distance, radius_tan, cb, front_dome=0.0, ior=1.5):
    """Everything the node group derives from (distance, image circle, bowl curvature)."""
    d = distance
    a = d * radius_tan
    h = OUTER_RATIO * a
    cf = front_dome * HEMISPHERE_LIMIT / h
    sag_ba = sag(cb, a)
    sag_fh = sag(cf, h)
    t_min = MIN_GLASS_RATIO * a
    T = max(THICKNESS_RATIO * a, sag_ba + t_min, sag_fh + t_min)
    return dict(a=a, h=h, d=d, cb=cb, cf=cf, sag_ba=sag_ba, sag_fh=sag_fh, T=T, ior=ior,
                z_bowl_vertex=-d - sag_ba, z_front_vertex=-d - T,
                Rb=(1.0 / cb) if cb else 0.0, Rf=(1.0 / cf) if cf else 0.0)


def trace_geometry(theta_deg, g):
    """Trace one camera ray through a resolved geometry. Returns (status, world_deg)."""
    n = g["ior"]
    th = math.radians(theta_deg)
    p = (0.0, 0.0)
    dvec = (math.sin(th), -math.cos(th))
    hit = intersect_surface(p, dvec, g["z_bowl_vertex"], g["Rb"])
    if hit is None or abs(hit[0][0]) > g["a"]:
        return "barrel", None
    p, nrm = hit
    dvec = refract(dvec, nrm, 1.0, n)
    if dvec is None:
        return "tir-bowl", None
    hit = intersect_surface(p, dvec, g["z_front_vertex"], g["Rf"])
    if hit is None or abs(hit[0][0]) > g["h"]:
        return "rim", None
    p, nrm = hit
    dvec = refract(dvec, nrm, n, 1.0)
    if dvec is None:
        return "tir-front", None
    return "ok", math.degrees(math.atan2(dvec[0], -dvec[1]))


def edge_angle(distance, radius_tan, cb, front_dome, ior):
    """World half-angle of the ray through the rim of the bowl (pi/2+ when it TIRs)."""
    g = geometry(distance, radius_tan, cb, front_dome, ior)
    status, w = trace_geometry(math.degrees(math.atan(radius_tan)) * 0.999999, g)
    return math.radians(w) if status == "ok" else math.pi


def solve_curvature(fov_deg, distance, radius_tan, front_dome=0.0, ior=1.5, iterations=40):
    """Bisection for the bowl curvature that maps the rim of the image circle to fov/2.
    Exactly what the repeat zone in the node group does."""
    target = math.radians(fov_deg) * 0.5
    a = distance * radius_tan
    lo, hi = 0.0, HEMISPHERE_LIMIT / a
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if edge_angle(distance, radius_tan, mid, front_dome, ior) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def design(fov=180.0, fmt="Full Frame", custom=1.5, distance=0.10, front_dome=0.0, ior=1.5,
           focal_mm=50.0, sensor_mm=36.0, res=(1280, 720), verbose=True):
    tx, ty = camera_frame(focal_mm, sensor_mm, res)
    r_tan = circle_radius(fmt, tx, ty, custom)
    cb = solve_curvature(fov, distance, r_tan, front_dome, ior)
    g = geometry(distance, r_tan, cb, front_dome, ior)
    theta_edge = math.degrees(math.atan(r_tan))
    achieved = 2.0 * math.degrees(edge_angle(distance, r_tan, cb, front_dome, ior))
    if verbose:
        print("-" * 78)
        print("Field of View %.0f deg, %s, %d mm camera, %dx%d" % (fov, fmt, focal_mm, res[0], res[1]))
        print("  image circle: %.1f deg half-angle on the camera (tan %.3f)" % (theta_edge, r_tan))
        print("  solved bowl curvature %.2f 1/m  (radius %.1f mm, depth %.1f mm, %.0f%% of a hemisphere)"
              % (cb, 1000 * g["Rb"] if cb else float("inf"), 1000 * g["sag_ba"], 100 * cb * g["a"] / HEMISPHERE_LIMIT))
        print("  achieved FOV %.1f deg%s" % (achieved, "" if abs(achieved - fov) < 0.5 else "   <-- CLAMPED"))
        print("  puck: bowl dia %.0f mm, outer dia %.0f mm, thickness %.0f mm; closest glass %.3f m"
              % (2000 * g["a"], 2000 * g["h"], 1000 * g["T"], math.hypot(g["a"], g["d"])))
        print("  %8s %10s %8s" % ("cam deg", "world deg", "gain"))
        steps = 8
        for i in range(steps + 1):
            th = theta_edge * i / steps
            status, w = trace_geometry(min(th, theta_edge * 0.99999), g)
            print("  %8.1f %10s" % (th, ("%10.1f %8.2f" % (w, (w / th) if th > 0 else 1.0)) if status == "ok" else status))
    return g, achieved


def stress_test():
    """Make sure no ray can hit the blackened rim for any FOV/format/camera."""
    worst = 0.0
    bad = []
    for fov in (60, 90, 120, 150, 170, 180, 200):
        for fmt in ("Circular", "Full Frame"):
            for focal in (14, 24, 35, 50, 85):
                for dome in (0.0, 0.5, 1.0):
                    tx, ty = camera_frame(focal)
                    r = circle_radius(fmt, tx, ty)
                    cb = solve_curvature(fov, 0.1, r, dome)
                    g = geometry(0.1, r, cb, dome)
                    te = math.degrees(math.atan(r))
                    for i in range(1, 200):
                        st, w = trace_geometry(te * i / 200.0, g)
                        if st == "rim":
                            bad.append((fov, fmt, focal, dome, te * i / 200.0))
                            break
                        if st == "ok":
                            worst = max(worst, 0.0)
    print("rim hits:", bad if bad else "none")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stress":
        stress_test()
        sys.exit(0)
    fov = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
    fmt = sys.argv[2] if len(sys.argv) > 2 else "Full Frame"
    focal = float(sys.argv[3]) if len(sys.argv) > 3 else 50.0
    design(fov, fmt, focal_mm=focal)
    if len(sys.argv) == 1:
        design(180.0, "Circular", focal_mm=35.0)
        design(110.0, "Full Frame", focal_mm=50.0)
        design(50.0, "Full Frame", focal_mm=50.0)   # below the camera's own diagonal -> clamped flat
