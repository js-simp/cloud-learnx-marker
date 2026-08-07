EXAMPLE QUESTION FILES (study these for style and structure):

--- EXAMPLE: Geometry with tikz diagram (q1.tex style) ---
\begin{question}
\noindent The diagram shows two right-angled triangles, $ABD$ and $CDE$.
$ADC$ and $BDE$ are straight lines intersecting at point $D$.

\begin{center}
\begin{tikzpicture}[scale=0.6]
    \draw[thick] (-6, 0) node[below]{$A$} -- (8.5, 0) node[below]{$C$};
    \draw[thick] (-6, 8) node[above]{$B$} -- (3, -4) node[below]{$E$};
    \draw[thick] (-6, 0) -- (-6, 8);
    \draw[thick] (3, -4) -- (8.33, 0);
    \draw (-5.6, 0) -- (-5.6, 0.4) -- (-6, 0.4);
    \draw (2.76, -3.68) -- (3.08, -3.44) -- (3.32, -3.76);
    \node at (0.3, 0.4) {$D$};
    \node at (-6.5, 4) {$8$ cm};
    \node at (-3, -0.5) {$6$ cm};
    \node at (5, 0.5) {$12.5$ cm};
\end{tikzpicture}
\end{center}

\noindent $AB = 8$ cm, $AD = 6$ cm, $CD = 12.5$ cm.
Work out the length of $CE$.

\vspace{4.5cm}
\begin{flushright}
    \answerunit{cm}{3}
\end{flushright}
\end{question}

--- EXAMPLE: Transformations (q2.tex style) ---
\begin{question}
\noindent Triangle $P$ is rotated to give triangle $Q$, as shown on the grid.
\begin{center}

\scalebox{0.75}{%
\begin{tikzpicture}

    % Define axis scale
    \def\axisLimit{7}
    \definecolor{borderColour}{HTML}{000000}
    \definecolor{fillColourP}{HTML}{BFD8FF}
    \definecolor{fillColourQ}{HTML}{FFD8B0}
    
    % Draw grid
    \draw[step=1cm,gray,very thin] (-\axisLimit,-\axisLimit) grid (\axisLimit,\axisLimit);
    
    % Draw axes
    \draw[thick,->] (-\axisLimit-0.5,0) -- (\axisLimit+0.5,0) node[anchor=north] {$x$};
    \draw[thick,->] (0,-\axisLimit-0.5) -- (0,\axisLimit+0.5) node[anchor=east] {$y$};
    
    % Label x-axis and y-axis
    \foreach \x in {-\axisLimit,...,\axisLimit}
        \draw (\x cm,1pt) -- (\x cm,-1pt) node[anchor=north] {$\x$};
    \foreach \y in {-\axisLimit,...,\axisLimit}
        \draw (1pt,\y cm) -- (-1pt,\y cm) node[anchor=east] {$\y$};
        
    % Triangle P: A(1,2), B(1,5), C(3,2)
    \coordinate (A) at (1,2);
    \coordinate (B) at (1,5);
    \coordinate (C) at (3,2);
    \filldraw[fill=fillColourP, draw=borderColour, line width=1pt] (A) -- (B) -- (C) -- cycle;
    
    \node at (1.6,3) {$P$};
    % Centre of rotation at (1,-1)
    \coordinate (centre) at (1,-1);
  
    % Triangle Q: rotate P by 180 degrees about (1,-1)
    \coordinate (Ap) at ([rotate around={180:(centre)}]A);
    \coordinate (Bp) at ([rotate around={180:(centre)}]B);
    \coordinate (Cp) at ([rotate around={180:(centre)}]C);
    \filldraw[fill=fillColourQ, draw=borderColour, line width=1pt] (Ap) -- (Bp) -- (Cp) -- cycle;
    \node at (0.3,-5.3) {$Q$};
\end{tikzpicture}%
}
\end{center}
\noindent Find the transformation that maps triangle $P$ onto triangle $Q$.\\
You must give \textbf{full details} of the transformation.

\answerlines{3}{3}
\end{question}

--- EXAMPLE: Transformations (q3.tex style) ---
\begin{question}
\noindent Triangle $T$ is enlarged to give triangle $T'$, as shown on the grid below.

\begin{center}
\begin{tikzpicture}[scale=0.75, transform shape]
    \definecolor{borderColour}{HTML}{000000}
    \definecolor{fillColourT}{HTML}{ADD8E6}
    \definecolor{fillColourTprime}{HTML}{D8D8D8}

    \def\axisLimit{6}

    % Draw grid
    \draw[step=1cm,gray,very thin] (-\axisLimit,-\axisLimit) grid (\axisLimit,\axisLimit);

    % Draw axes
    \draw[thick,->] (-\axisLimit-0.5,0) -- (\axisLimit+0.5,0) node[anchor=north] {$x$};
    \draw[thick,->] (0,-\axisLimit-0.5) -- (0,\axisLimit+0.5) node[anchor=east] {$y$};

    % Label x-axis and y-axis
    \foreach \x in {-\axisLimit,...,-1,1,2,...,\axisLimit}
        \draw (\x cm,1pt) -- (\x cm,-1pt) node[anchor=north] {$\x$};
    \foreach \y in {-\axisLimit,...,-1,1,2,...,\axisLimit}
        \draw (1pt,\y cm) -- (-1pt,\y cm) node[anchor=east] {$\y$};

    % Define vertices of T
    \coordinate (A) at (1,1);
    \coordinate (B) at (1,2);
    \coordinate (C) at (2,1);

    % Draw T
    \draw[fill=fillColourT, draw=borderColour, line width=1pt] (A) -- (B) -- (C) -- cycle;
    \node at (1.6,1.35) {$T$};

    % Define vertices of T' (enlargement by scale factor -2 from centre (0,-1))
    \coordinate (Ap) at (-2,-5);
    \coordinate (Bp) at (-2,-7);
    \coordinate (Cp) at (-4,-5);

    % Draw T'
    \draw[fill=fillColourTprime, draw=borderColour, line width=1pt] (Ap) -- (Bp) -- (Cp) -- cycle;
    \node at (-3,-5.6) {$T'$};

\end{tikzpicture}
\end{center}

\noindent Find the scale factor of the enlargement and the coordinates of the centre of enlargement.

\vspace{5cm}

\begin{flushright}
    \answerplain{3}
\end{flushright}
\end{question}

--- EXAMPLE: Circle Theorems (q4.tex style) ---
\begin{question}
\noindent A satellite dish engineer models the cross-section of a circular antenna dish as a circle with centre $O$. Points $A$, $B$ and $C$ lie on the circumference, where $AC$ is a diameter of the circle. A support strut $CD$ is attached so that it is tangent to the circle at point $C$.

\begin{center}
\begin{tikzpicture}[scale=2.2]

    \coordinate (O) at (0,0);
    % Circle centre O at origin, radius 1
    \draw[name path=circ] (O) circle (1);
    
    \coordinate (A) at (180:1);
    \coordinate (C) at (0:1);
    \coordinate (B) at (130:1);

    \fill[black] (O) circle (0.8pt);

    % Diameter AC
    \draw[thick] (A) -- (C);

    % Chords AB and BC
    \draw[thick] (A) -- (B);
    \draw[thick] (B) -- (C);

    % Tangent at C, perpendicular to AC (i.e. vertical line)
    \draw[thick] (C) -- ++(90:1) coordinate (Dtop);
    \draw[thick] (C) -- ++(-90:1) coordinate (Dbot);

    % Labels
    \node[left] at (A) {$A$};
    \node[above left] at (B) {$B$};
    \node[right] at (C) {$C$};
    \node at (O) [below] {$O$};
    \node[above right] at (Dtop) {$D$};

    % angle BAC = 35 degrees marked at A using C--A--B to sweep the angle in anticlockwise direction
    \pic [draw, angle eccentricity=1.5, angle radius=0.7cm, "$35^\circ$"] {angle = C--A--B};

\end{tikzpicture}
\end{center}

\noindent Angle $BAC = 35^\circ$.

\begin{enumerate}
    \item[(a)] Show that angle $ABC = 90^\circ$, giving a reason for your answer.

    \vspace{3cm}
    \answermarks{2}

    \item[(b)] Work out the size of angle $BCD$.\\
    Give a reason for each stage of your working.

    \vspace{4cm}
    \answerequnit{BCD}{$^\circ$}{2}
\end{enumerate}
\end{question}

--- EXAMPLE: Circle Theorems (q5.tex style) ---
\begin{question}
\noindent A space agency tracks four satellites, $P$, $Q$, $R$ and $S$, which orbit at a fixed distance from a control station $O$, so all four satellites lie on a circle with centre $O$. Points $P$, $Q$, $R$ and $S$ lie on the circumference, in that order around the circle.

Angle $PQR = 142^\circ$ and angle $QPS = 95^\circ$. Angle $SRO = 34^\circ$, where $O$ is the centre of the circle.

\begin{center}
\begin{tikzpicture}[scale=2.2]
    \coordinate (O) at (0,0);
    \draw[name path=circ] (0,0) circle (1);
    \fill[black] (O) circle (1pt);
    \node at (0.08,-0.1) {$O$};

    \coordinate (P) at (160:1);
    %consider angle PQR as 140 for ease while preserving visual accuracy, angle POR (at center) becomes (360-280)=80. Hence angle of OR to horizontal will be 160-80 = 80
    \coordinate (R) at (80:1);
    %considering QPS to be 90 for ease, then QRO is 90-34=56. Then we have OPQ = 74, i.e QOP angle is 32. then angle OQ makes with horizontal is 160-32=128
    \coordinate (Q) at (128:1);
    %consider angle SRO as 30 for ease while preserving visual accuracy, then angle at center, SOR, is 120. Therefore angle of OS to the horizontal is 80-120 = -40 
    \coordinate (S) at (-60:1);

    \node[left] at (P) {$P$};
    \node[above] at (Q) {$Q$};
    \node[right] at (R) {$R$};
    \node[below] at (S) {$S$};

    \draw (P) -- (Q) -- (R) -- (S) -- cycle;
    \draw (R) -- (O);
    \draw (R) -- (S);
    \draw (P) -- (O);

    \pic [draw, "$142^\circ$", angle eccentricity=1.4, angle radius=0.35cm] {angle = P--Q--R};
    \pic [draw, "$95^\circ$", angle eccentricity=1.4, angle radius=0.6cm] {angle = S--P--Q};
    \pic [draw, "$34^\circ$", angle eccentricity=1.4, angle radius=0.65cm] {angle = O--R--S};
\end{tikzpicture}
\end{center}

\begin{enumerate}
    \item[(a)] Work out the size of angle $POR$ (the reflex angle at the centre corresponding to arc $PQR$), giving a reason for your answer.

    \vspace{3cm}
    \answerequnit{POR}{$^\circ$}{2}

    \item[(b)] Work out the size of angle $PSR$, giving a reason.

    \vspace{3cm}
    \answerequnit{PSR}{$^\circ$}{2}

    \item[(c)] Hence work out the size of angle $ORS$... 

    (Use your answer to part (b) together with angle $SRO = 34^\circ$ to find angle $PRS$.)

    \vspace{3cm}
    \answerequnit{PRS}{$^\circ$}{2}
\end{enumerate}
\end{question}


