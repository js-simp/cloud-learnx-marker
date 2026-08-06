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

--- EXAMPLE: Multi-part algebra (q3.tex style) ---
\begin{question}
$y$ is inversely proportional to $x^n$, where $n$ is an integer.

The table shows some values of $x$ and $y$.

\begin{center}
\begin{tabular}{c|ccc}
$x$ & 3 & 6 & $q$ \\
\hline
$y$ & 40 & 5 & 0.625 \\
\end{tabular}
\end{center}

\begin{enumerate}
    \item[(a)] Find the value of $n$.

    \vspace{4cm}
    \answereq{n}{2}

    \item[(b)] Find a formula for $y$ in terms of $x$.

    \vspace{2cm}
    \answereq{y}{2}

    \item[(c)] Find the value of $q$.

    \vspace{1.5cm}
    \answereq{q}{2}
\end{enumerate}
\end{question}

--- EXAMPLE: Word problem (q4.tex style) ---
\begin{question}
A farmer buys 749 sheep for a total cost of $C$.\\
He sells 700 of the sheep for $C$.\\
The farmer then sells the remaining 49 sheep at the same price per sheep.\\
Work out the percentage profit that the farmer makes.

\vspace{4cm}
\answerplain{2}
\end{question}