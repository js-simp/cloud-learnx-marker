# Q22 — Review Notes

## Error classes identified
- SCAFFOLDING AND/OR LEADING INFORMATION
- OFF-GRID / CLIPPED SHAPES
- PROPORTIONAL MISMATCH / VISUAL ACCURACY
- MATH CONTENT ERROR

## Explanation of errors and fixes
1) Centre of rotation marked and labelled on grid is unecessary scaffolding and leading, as identifying the COR is part of the problem solving. Fixed by removing it.
2) Vspace is not required in questions with answerlines. Fixed by removing vspace
3) Transformation image had an offset error because of canvas has been scaled. Fix: don't let TikZ's scale touch the coordinate system at all. Do the scaling after TikZ has rendered everything, using \scalebox
