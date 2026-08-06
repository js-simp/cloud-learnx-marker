# Geometry Diagram Verification Checklist

Use this before finalizing any TikZ diagram (circle theorems, transformations, triangles, etc.).

## 1. Solve first, draw second
- Identify every geometric constraint stated in the problem (tangent, diameter, collinear points, concyclic points, equal circles, transformation rule, etc.).
- Solve for exact coordinates algebraically — never estimate/eyeball coordinates.
- Only write TikZ once numeric coordinates are confirmed.

## 2. Constraint checks (circle/geometry problems)

| Constraint | Check |
|---|---|
| Tangent at point X | (radius vector at X) · (tangent direction vector) ≈ 0 |
| Point on circle | distance(point, center) ≈ r |
| Collinear points A, B, C | slope(A,B) ≈ slope(A,C), or cross product ≈ 0 |
| Diameter | midpoint of the two endpoints ≈ center |
| Concyclic points | equidistant from a common center, or opposite angles of cyclic quad sum to 180° |
| Intersection point | derive via the actual geometric construction/formula, never a guessed coordinate |

## 3. Angle arcs (`\pic {angle = X--Y--Z}`)
- `angle` picks up the angle by direction (counter-clockwise from ray Y→X to ray Y→Z). Check the point order — a swapped order silently draws the **reflex** angle instead of the intended one.
- After drawing, sanity-check: does the arc visually sit *inside* the marked angle, not sweeping the outside/long way around? If the marked value is under 180° but the arc looks like it's covering more than half the circle, the point order is wrong — fix by swapping X and Z (or add `angle radius`/reflex handling explicitly if a reflex angle is actually intended).

## 4. Coordinate/grid diagrams (transformations, plotted shapes)
- Compute every vertex of every shape (original and image) before drawing.
- Confirm **all** vertices fall within the stated axis range (e.g. if axes run -6 to 6, no vertex may fall outside that box). Check this explicitly — don't assume a shape "looks like it fits."
- For transformations (translation, rotation, reflection, enlargement), verify the image's vertices by applying the stated rule algebraically to the original's vertices — don't place the image by eye.

## 5. Side-length proportionality
- If the diagram has **no** "not accurately drawn" disclaimer, drawn side lengths must be roughly proportional to their labeled values (relative error should be small, not just "same rough size"). A side labeled as more than double another must be drawn visibly longer — check the ratio of drawn lengths against the ratio of labeled lengths before finalizing.
- If the diagram **does** carry a "not accurately drawn" note, exact proportionality isn't required, but avoid drawing a labeled-longer side visibly shorter than a labeled-shorter side — it's misleading even when technically permitted.

## 6. Before shipping
- Re-check every coordinate against Sections 2 and 4.
- Re-check every angle arc against Section 3.
- Re-check every labeled length against Section 5.
- Confirm labels/points match their intended role (e.g. don't swap which point is "beyond" vs "at" a tangent point).