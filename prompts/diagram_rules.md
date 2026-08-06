TIKZ DIAGRAM RULES — MANDATORY. Violations cause wrong answers or student confusion.

CRITICAL HARD RULES:
1. NEVER write raw '°' symbols. Always write '$58^\circ$' or '$x^\circ$'.
2. NEVER calculate raw arcs manually using \draw (...) arc (...).
   ALWAYS use the `angles` and `quotes` libraries:
   \pic [draw, angle radius=6mm, "$x$"] {angle = A--B--C};
3. NEVER rely on implicit `intersection-2` or ambiguous intersection arrays.
   Always explicitly define named intersections or single-point outputs:
   name intersections={of=lineA and circleB, by={P1}}

═══════════════════════════════════════════════════════
RULE 1 — ANGLE ARC DIRECTION (CRITICAL)
═══════════════════════════════════════════════════════
The tikz `angles` library draws \pic{angle = A--V--B} COUNTER-CLOCKWISE from A to B around vertex V.
- If going from A to B counter-clockwise goes around the EXTERIOR, it will draw a 300°+ reflex arc!
- If your generated arc draws a reflex angle (>180°), you MUST swap A and B (e.g. change {angle = A--V--B} to {angle = B--V--A}).

To mark an acute or obtuse angle correctly:
  - Identify which direction from V gives the interior/minor angle.
  - Order the points so the arc sweeps that direction COUNTER-CLOCKWISE.

To avoid such errors in direction keep track of the angle to the horizontal of the points drawn. (e.g. To mark the minor angle
between AB and BC. Let's assume A is at an angle 150 degrees anticlockwise from horizontal and B is -40 degrees (i.e 40 degrees to the horizontal) )

═══════════════════════════════════════════════════════
RULE 2 — DIAGRAM COORDINATES MUST MATCH STATED DIMENSIONS
═══════════════════════════════════════════════════════
If a right triangle has legs stated as 3 cm and 4 cm, the tikz coordinates must reflect
that ratio: e.g. (0,0), (4,0), (0,3) — NOT (0,0), (5,0), (0,3).

NEVER assign tikz coordinates arbitrarily and then write different numbers in the text.
ALWAYS compute coordinates proportionally from the given measurements.

For triangles: place one vertex at origin, one along x-axis at the correct relative
distance, compute the third using the actual given lengths/angles.

═══════════════════════════════════════════════════════
RULE 3 — GRID/TRANSFORMATION QUESTIONS: ALL SHAPES MUST STAY WITHIN THE GRID
═══════════════════════════════════════════════════════
When drawing transformations (rotations, reflections, enlargements) on a coordinate grid:
  1. Wrap the whole tikzpicture in \scalebox{suitable scale}{...} before performing any transformation on grid.
  2. Use commands like scale around (for enlargements) and rotate around (for rotations) without explicitly calculating coordinates.
  3. Check EVERY image vertex is strictly inside the grid boundaries.
  3. If any vertex falls outside, CHANGE the original shape's position/size,
     or change the transformation parameters, until ALL vertices fit.

═══════════════════════════════════════════════════════
RULE 4 — PROPORTIONAL VISUAL ACCURACY
═══════════════════════════════════════════════════════
The visual size of sides in the diagram must be proportional to the stated measurements.
A side labelled 15.6 m MUST appear longer than a side labelled 7.2 m in the diagram.

═══════════════════════════════════════════════════════
RULE 5 — FLOATING LABELS AND ALIGNMENT
═══════════════════════════════════════════════════════
Node labels must be positioned relative to their anchor point:
  - Vertex labels: use [above left], [below right], etc. anchored to the vertex coordinate.
  - Side labels: use node[midway, above] or node[midway, left] on the draw command.
  - NEVER place labels at arbitrary coordinates disconnected from their referent geometry.