AVAILABLE LATEX MACROS (use ONLY these for answer boxes):

QUESTION STRUCTURE:
  \begin{question} ... \end{question}     — wraps each question, auto-numbers, auto-totals marks
  \partq{a}  \partq{b}  etc.             — sub-part labels inside a question

ANSWER MACROS (always place at end of each part, right-aligned):
  \answerplain{marks}                    — dotted line only         e.g. \answerplain{3}
  \answerunit{unit}{marks}               — dotted line + unit       e.g. \answerunit{cm}{2}
  \answerprefix{prefix}{marks}           — prefix + dotted line     e.g. \answerprefix{\$}{2}
  \answereq{variable}{marks}             — x = dotted line          e.g. \answereq{x}{2}
  \answerequnit{variable}{unit}{marks}   — x = dotted line + unit   e.g. \answerequnit{v}{\text{m/s}}{3}
  \answerlines{num_lines}{marks}         — ruled lines for written explanation
  \answercoord{marks}                    — coordinate pair ( . , . )
  \answermarks{marks}                    — marks only, no answer line (use for show-that questions)
  \answermcq{A}{B}{C}{D}{marks}          — 4-option MCQ with tickboxes

CRITICAL MACRO RULE FOR UNITS:
  The {unit} argument in \answerunit and \answerequnit is evaluated in TEXT MODE.
  If your unit contains math symbols, superscripts, or subscripts (e.g. degrees, cm^2, m/s^2),
  you MUST wrap the math elements inside $...$ delimiters.
  - WRONG: \answerequnit{x}{^\circ}{3}   --> FAILS WITH COMPILATION ERROR!
  - WRONG: \answerunit{cm^2}{2}          --> FAILS WITH COMPILATION ERROR!
  - RIGHT: \answerequnit{x}{$^\circ$}{3}
  - RIGHT: \answerunit{$\text{cm}^2$}{2}

COLOR RULES FOR TIKZ:
  Use ONLY standard xcolor names: red, blue, green, black, gray, lightgray, darkgray, cyan, magenta, yellow.
  DO NOT use 'primaryGreen', 'lightYellow', or invent custom color names.

TIKZ & PACKAGE RULES:
1. DO NOT include \usetikzlibrary{...} or \usepackage{...} in your question code. All libraries are already pre-loaded in the document header.
2. For tick marks or line decorations, use ONLY valid TikZ library syntax:
   - Use 'decorations.markings' or 'decorations.pathreplacing' (NEVER 'decorations.pathmarking').
   - For right angle arcs, use the standard 'angles' and 'quotes' libraries.
3. For parallel lines or equal side tick marks:
   - Use simple TikZ drawings like: \draw[thick] (A) -- (B); or standard TikZ markings.

SPACING:
  \vspace{Xcm}    — vertical space for working. Use generously (4cm minimum per part).

MATHS:
  Inline:  $...$   e.g. $x^2 + 3x - 2 = 0$
  Display: \[ ... \]  for standalone equations

TIKZ DIAGRAMS:
  Pre-loaded libraries (do NOT \usetikzlibrary these yourself): angles, quotes, shapes.misc, calc, decorations.pathreplacing, decorations.markings, patterns, intersections. Also available: tikz-3dplot (3D diagrams), tkz-euclide (compass/straightedge-style geometric constructions).
  Always wrap diagrams in \begin{center}...\end{center}.
  Use [scale=0.8] or similar to ensure diagrams fit the page width.

DO NOT invent new macros. DO NOT use \begin{exam} or similar — it does not exist.