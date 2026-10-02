"""A small hand-written library of common prerequisite concepts.

It backs three things: the built-in sample course, the offline engine (keyword mapping and
question packs when Gemini is unavailable), and the catalog of free resources Gemini picks from.

Every resource URL here was confirmed to exist via web search. Run
scripts/check_links.py from a machine with normal internet access before a demo to re-check them.
Questions list the correct answer first; it is moved to a varied position when loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..textutil import normalize_name


@dataclass(frozen=True)
class LibResource:
    id: str
    title: str
    url: str
    detail: str
    subjects: tuple[str, ...]


RESOURCES: list[LibResource] = [
    LibResource("os-stats-desc", "Introductory Statistics 2e (OpenStax, via LibreTexts)",
                "https://stats.libretexts.org/Bookshelves/Introductory_Statistics/Introductory_Statistics_2e_(OpenStax)/02%3A_Descriptive_Statistics",
                "Ch. 2: Descriptive Statistics", ("statistics",)),
    LibResource("os-stats-prob", "Introductory Statistics (OpenStax)",
                "https://openstax.org/books/introductory-statistics/pages/3-introduction",
                "Ch. 3: Probability Topics", ("statistics", "probability")),
    LibResource("os-stats-reg", "Introductory Statistics (OpenStax)",
                "https://openstax.org/books/introductory-statistics/pages/12-3-the-regression-equation",
                "§12.3: The Regression Equation", ("statistics", "regression")),
    LibResource("lt-stats-reg", "Introductory Statistics 2e (OpenStax, via LibreTexts)",
                "https://stats.libretexts.org/Bookshelves/Introductory_Statistics/Introductory_Statistics_2e_(OpenStax)/13%3A_Linear_Regression_and_Correlation",
                "Ch. 13: Linear Regression and Correlation", ("statistics", "regression")),
    LibResource("os-bstats", "Introductory Business Statistics 2e (OpenStax)",
                "https://openstax.org/books/introductory-business-statistics-2e/pages/index",
                "Ch. 13: Linear Regression and Correlation (includes multiple regression)", ("statistics", "regression", "business")),
    LibResource("os-calc1-chain", "Calculus Volume 1 (OpenStax)",
                "https://openstax.org/books/calculus-volume-1/pages/3-6-the-chain-rule",
                "§3.6: The Chain Rule", ("calculus",)),
    LibResource("lt-calc1-chain", "Calculus (OpenStax, via LibreTexts)",
                "https://math.libretexts.org/Bookshelves/Calculus/Calculus_(OpenStax)/03:_Derivatives/3.06:_The_Chain_Rule",
                "3.6: The Chain Rule", ("calculus",)),
    LibResource("os-calc1", "Calculus Volume 1 (OpenStax)",
                "https://openstax.org/books/calculus-volume-1/pages/index",
                "Ch. 5: Integration (§5.3: The Fundamental Theorem of Calculus)", ("calculus",)),
    LibResource("os-calc3-dot", "Calculus Volume 3 (OpenStax)",
                "https://openstax.org/books/calculus-volume-3/pages/2-3-the-dot-product",
                "§2.3: The Dot Product", ("linear algebra", "vectors")),
    LibResource("lt-alg-matrix", "Algebra and Trigonometry (OpenStax, via LibreTexts)",
                "https://math.libretexts.org/Bookshelves/Algebra/Algebra_and_Trigonometry_1e_(OpenStax)/11%3A_Systems_of_Equations_and_Inequalities/11.05%3A_Matrices_and_Matrix_Operations",
                "11.5: Matrices and Matrix Operations", ("linear algebra", "matrices")),
    LibResource("lt-alg-log", "Algebra and Trigonometry (OpenStax, via LibreTexts)",
                "https://math.libretexts.org/Bookshelves/Algebra/Algebra_and_Trigonometry_1e_(OpenStax)/06%3A_Exponential_and_Logarithmic_Functions/6.03%3A_Logarithmic_Functions",
                "6.3: Logarithmic Functions", ("algebra", "logarithms")),
    LibResource("py4e", "Python for Everybody (Charles Severance)",
                "https://www.py4e.com",
                "Free book and videos: variables, loops, functions, lists", ("programming", "python")),
    LibResource("progit", "Pro Git (Chacon & Straub)",
                "https://git-scm.com/book/en/v2",
                "Ch. 2: Git Basics; Ch. 3: Git Branching", ("programming", "git")),
    LibResource("dbdesign", "Database Design, 2nd Edition (Watt & Eng)",
                "https://opentextbc.ca/dbdesign01/",
                "Keys, relationships, normalization and SQL", ("databases", "sql")),
]
RESOURCES_BY_ID = {r.id: r for r in RESOURCES}


@dataclass(frozen=True)
class LibQuestion:
    prompt: str
    choices: tuple[str, str, str, str]  # correct answer first
    explanation: str


@dataclass(frozen=True)
class LibConcept:
    key: str
    name: str
    summary: str
    keywords: tuple[str, ...]
    depth: str
    refresh_minutes: int
    learn_minutes: int
    refresher: str
    learn_outline: str
    resources: tuple[str, ...]
    questions: tuple[LibQuestion, ...] = field(default_factory=tuple)


# Standard prerequisite relations between library concepts (src key -> keys it builds on).
BUILDS_ON: dict[str, tuple[str, ...]] = {
    "slr": ("desc-stats",),
    "mlr": ("slr",),
    "matmul": ("dot-product",),
    "integration": ("chain-rule",),
    "probability": (),
}


CONCEPTS: list[LibConcept] = [
    LibConcept(
        "desc-stats", "Descriptive Statistics",
        "Summarizing data with measures of center (mean, median) and spread (variance, standard deviation).",
        ("statistics refresher", "descriptive statistic", "standard deviation", "variance", "summary statistic", "median"),
        "compute and interpret mean, median and standard deviation", 15, 120,
        "The **mean** is the average; the **median** is the middle value and resists outliers. "
        "**Standard deviation** measures how far values typically sit from the mean.\n\n"
        "Example: for 2, 4, 4, 10 the mean is $20/4 = 5$ while the median is $4$: "
        "the single large value pulls the mean up but not the median.",
        "1. Read *Descriptive Statistics* (measures of center and spread).\n"
        "2. Compute mean, median and standard deviation by hand for a 5-number dataset.\n"
        "3. Explain why the median is preferred for skewed data like incomes.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("os-stats-desc",),
        (
            LibQuestion("For the data 2, 4, 4, 10, what is the mean?", ("5", "4", "8", "20"),
                        "Add the values (20) and divide by the count (4): the mean is 5. The median is 4."),
            LibQuestion("Which measure is least affected by one extreme outlier?", ("The median", "The mean", "The range", "The standard deviation"),
                        "The median depends only on the middle position, so one extreme value barely moves it."),
            LibQuestion("Two classes have the same mean exam score, but class A has a much larger standard deviation. What does that tell you?",
                        ("Class A's scores are more spread out around the mean", "Class A scored higher on average",
                         "Class A has more students", "Class A's scores are all below the mean"),
                        "Standard deviation measures spread, not the center: same average, wider spread."),
        ),
    ),
    LibConcept(
        "probability", "Basic Probability",
        "Probabilities of events, complements, independence and conditional probability.",
        ("probability", "uncertainty", "bayes", "bayesian", "conditional probability", "naive bayes", "independence"),
        "compute simple, joint and conditional probabilities", 20, 180,
        "$P(A) \\in [0,1]$; the complement is $P(\\text{not }A) = 1 - P(A)$.\n\n"
        "If $A$ and $B$ are **independent**, $P(A \\text{ and } B) = P(A)\\,P(B)$.\n\n"
        "**Conditional probability:** $P(A \\mid B) = \\dfrac{P(A \\text{ and } B)}{P(B)}$, the probability of $A$ once you know $B$ happened.",
        "1. Read *Probability Topics*: terminology, independent events, the two basic rules.\n"
        "2. Practice with dice and cards until $P(A \\text{ and } B)$ and $P(A \\mid B)$ feel routine.\n"
        "3. Work one contingency-table example.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("os-stats-prob",),
        (
            LibQuestion("You roll a fair six-sided die. What is the probability of an even number?", ("1/2", "1/3", "1/6", "2/3"),
                        "Three of the six equally likely faces (2, 4, 6) are even: 3/6 = 1/2."),
            LibQuestion("P(A) = 0.3 and P(B) = 0.5, and A and B are independent. What is P(A and B)?", ("0.15", "0.8", "0.2", "0.35"),
                        "For independent events, multiply: 0.3 × 0.5 = 0.15. Adding (0.8) would be the wrong rule."),
            LibQuestion("P(A and B) = 0.12 and P(B) = 0.4. What is P(A | B)?", ("0.3", "0.048", "0.52", "0.12"),
                        "P(A | B) = P(A and B) / P(B) = 0.12 / 0.4 = 0.3."),
        ),
    ),
    LibConcept(
        "slr", "Simple Linear Regression",
        "Fitting a straight line ŷ = a + bx to predict a response from one explanatory variable.",
        ("simple linear regression", "linear regression", "regression", "least squares", "linear model", "linear modeling", "line of best fit", "correlation"),
        "interpret slope, intercept and R²; make a prediction", 20, 240,
        "Least squares fits $\\hat{y} = a + bx$. The **slope** $b$ is the average change in $y$ for a one-unit increase in $x$; "
        "the **intercept** $a$ is the prediction at $x = 0$.\n\n"
        "$R^2$ is the share of the variation in $y$ explained by the line.\n\n"
        "Example: $\\hat{y} = 20 + 3x$ (score vs. hours studied) predicts $20 + 3(10) = 50$ for 10 hours. "
        "Regression shows association, not causation.",
        "1. Read *The Regression Equation* (scatter plots, the least-squares line).\n"
        "2. Fit a line to a 6-point dataset by hand or in a spreadsheet, then check it with software.\n"
        "3. Practice interpreting slope, intercept and $R^2$ in words, with units.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("os-stats-reg", "lt-stats-reg"),
        (
            LibQuestion("A model predicts exam score from hours studied: ŷ = 20 + 3x. What does the 3 mean?",
                        ("Each additional hour studied is associated with about 3 more points, on average",
                         "A student who does not study scores 3 points", "Studying causes a 20-point increase",
                         "The correlation between hours and score is 3"),
                        "The slope is the average change in the predicted score per one-unit change in x. The intercept (20) is the prediction at x = 0."),
            LibQuestion("Using ŷ = 20 + 3x, what is the predicted score for 10 hours of study?", ("50", "23", "30", "203"),
                        "Substitute x = 10: 20 + 3 × 10 = 50."),
            LibQuestion("A simple regression has R² = 0.64. Which statement is correct?",
                        ("64% of the variation in y is explained by the linear relationship with x", "The slope of the line is 0.64",
                         "64% of the predictions are exactly right", "The correlation coefficient is 0.64"),
                        "R² is the explained share of variation. The correlation here would be ±0.8, since 0.8² = 0.64."),
        ),
    ),
    LibConcept(
        "mlr", "Multiple Linear Regression",
        "Regression with several explanatory variables, where each coefficient holds the others fixed.",
        ("multiple regression", "multiple linear regression", "explanatory variable", "regression coefficient", "multiple predictors"),
        "interpret coefficients holding other variables fixed; know R² behavior", 25, 240,
        "$\\hat{y} = b_0 + b_1x_1 + b_2x_2 + \\dots$ Each $b_j$ is the average change in $y$ for a one-unit change in $x_j$ "
        "**holding the other variables fixed**.\n\n"
        "Adding variables never lowers $R^2$ on the training data, which is why adjusted $R^2$ and test data matter. "
        "Strongly correlated predictors (multicollinearity) make individual coefficients unstable.",
        "1. Make sure simple linear regression is solid first.\n"
        "2. Read the multiple regression part of *Linear Regression and Correlation*.\n"
        "3. Fit a two-predictor model in software and interpret each coefficient in a sentence.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("os-bstats", "lt-stats-reg"),
        (
            LibQuestion("A housing model is price = 50 + 2·(size in 100 sq ft) + 10·bedrooms (price in $1000s). What does the 10 mean?",
                        ("Holding size fixed, each extra bedroom is associated with about $10,000 higher price, on average",
                         "A house with 10 bedrooms costs $50,000", "Bedrooms explain 10% of the variation in price",
                         "Price rises $10,000 for each additional 100 sq ft"),
                        "In multiple regression a coefficient is the association with that variable while the others are held constant."),
            LibQuestion("You add more explanatory variables to a regression fitted on the same training data. What happens to R²?",
                        ("It never decreases", "It always decreases", "It stays exactly the same", "It can become negative"),
                        "Extra variables can only explain as much variation or more on the training data, so R² cannot go down. That is why it can mislead."),
            LibQuestion("Two explanatory variables in a regression are very highly correlated with each other. What is this called?",
                        ("Multicollinearity", "Heteroscedasticity", "Autocorrelation", "Overfitting"),
                        "Multicollinearity inflates the uncertainty of individual coefficients even when predictions stay fine."),
        ),
    ),
    LibConcept(
        "chain-rule", "Derivatives and the Chain Rule",
        "The derivative as a rate of change, and the rule for differentiating a composition of functions.",
        ("derivative", "chain rule", "backprop", "backpropagation", "gradient", "calculus", "rate of change", "differentiation"),
        "differentiate polynomials and compositions; read dy/dx notation", 25, 300,
        "The derivative $f'(x)$ is the instantaneous rate of change. Power rule: $\\frac{d}{dx}x^n = n x^{n-1}$.\n\n"
        "**Chain rule:** if $y = f(u)$ and $u = g(x)$, then $\\dfrac{dy}{dx} = \\dfrac{dy}{du}\\cdot\\dfrac{du}{dx}$.\n\n"
        "Example: $\\frac{d}{dx}(2x+1)^5 = 5(2x+1)^4 \\cdot 2 = 10(2x+1)^4$. Backpropagation is the chain rule applied layer by layer.",
        "1. Read the derivative rules and *The Chain Rule*.\n"
        "2. Differentiate 10 compositions by hand, writing the inner and outer functions each time.\n"
        "3. Draw a two-step computation graph and push one derivative backwards through it.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("os-calc1-chain", "lt-calc1-chain"),
        (
            LibQuestion("What is the derivative of f(x) = x³?", ("3x²", "x²", "3x³", "x⁴/4"),
                        "Power rule: bring down the exponent and subtract one, so 3x²."),
            LibQuestion("What is the derivative of h(x) = (2x + 1)⁵?", ("10(2x + 1)⁴", "5(2x + 1)⁴", "10(2x + 1)⁵", "5(2x)⁴"),
                        "Outer derivative 5(2x + 1)⁴ times the inner derivative 2 gives 10(2x + 1)⁴. Forgetting the inner factor gives 5(2x + 1)⁴."),
            LibQuestion("If y = f(u) and u = g(x), what is dy/dx?", ("(dy/du) · (du/dx)", "dy/du + du/dx", "(dy/du) / (du/dx)", "dy/du"),
                        "The chain rule multiplies the rates of change along the chain of functions."),
        ),
    ),
    LibConcept(
        "dot-product", "Vectors and the Dot Product",
        "Vectors as lists of numbers, and the dot product as a measure of alignment between two vectors.",
        ("vector", "dot product", "similarity", "embedding", "attention", "cosine"),
        "compute a dot product; interpret it as similarity", 15, 120,
        "For $a, b \\in \\mathbb{R}^n$: $a \\cdot b = \\sum_i a_i b_i = \\lVert a\\rVert\\,\\lVert b\\rVert \\cos\\theta$.\n\n"
        "Large and positive when the vectors point the same way, zero when they are perpendicular, negative when opposed. "
        "That is why it works as a similarity score.\n\n"
        "Example: $[1,2,3]\\cdot[4,0,-1] = 4 + 0 - 3 = 1$.",
        "1. Read *The Dot Product*: the definition and the angle formula.\n"
        "2. Compute five dot products by hand, including one pair of perpendicular vectors.\n"
        "3. In Python, compute the cosine similarity of two short word-count vectors.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("os-calc3-dot",),
        (
            LibQuestion("What is [1, 2, 3] · [4, 0, −1]?", ("1", "[4, 0, −3]", "7", "0"),
                        "Multiply matching entries and add: 1·4 + 2·0 + 3·(−1) = 1. The dot product is a single number, not a vector."),
            LibQuestion("The dot product of two nonzero vectors is 0. What does that tell you?",
                        ("They are perpendicular (orthogonal)", "They point in the same direction", "They have the same length", "One of them must be negative"),
                        "a · b = |a||b|cos θ, and with nonzero lengths that is 0 only when cos θ = 0, i.e. a right angle."),
            LibQuestion("Why is the dot product used as a similarity score between embedding vectors?",
                        ("It is larger when the vectors point in similar directions", "It counts how many entries are equal",
                         "It is always between 0 and 1", "It measures the distance between the vectors' endpoints"),
                        "Through |a||b|cos θ it grows with alignment. Normalizing the vectors turns it into cosine similarity."),
        ),
    ),
    LibConcept(
        "matmul", "Matrix Multiplication",
        "Multiplying matrices row-by-column, including the shape rules that decide whether a product exists.",
        ("matrix multiplication", "matrices", "matmul", "linear algebra", "tensor", "linear layer"),
        "check shapes; multiply small matrices; know AB ≠ BA", 20, 180,
        "An $m\\times n$ matrix times an $n\\times p$ matrix gives an $m\\times p$ matrix: the inner sizes must match. "
        "Entry $(i,j)$ is the dot product of row $i$ of $A$ with column $j$ of $B$.\n\n"
        "In general $AB \\neq BA$. A neural network layer computes $Wx + b$: one matrix multiplication.",
        "1. Read *Matrices and Matrix Operations* (dimensions, multiplication).\n"
        "2. Multiply three pairs of small matrices by hand and check the shapes first each time.\n"
        "3. Reproduce your answers with NumPy's `@` operator.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("lt-alg-matrix",),
        (
            LibQuestion("A is 2×3 and B is 3×4. What is the shape of AB?", ("2×4", "3×3", "4×2", "AB is undefined"),
                        "Inner dimensions (3 and 3) match, and the result takes the outer ones: 2×4."),
            LibQuestion("What is [[1, 2], [3, 4]] times the column vector [1, 1]?", ("[3, 7]", "[4, 6]", "[1, 3]", "[2, 6]"),
                        "Each row dotted with [1, 1]: 1 + 2 = 3 and 3 + 4 = 7. [4, 6] would be the column sums."),
            LibQuestion("For two square matrices A and B, which is true in general?",
                        ("AB and BA can be different", "AB always equals BA", "BA is always the transpose of AB", "AB is undefined unless A = B"),
                        "Matrix multiplication is not commutative; order matters."),
        ),
    ),
    LibConcept(
        "python", "Python Fundamentals",
        "Variables, lists, loops and functions in Python, enough to read and modify a notebook.",
        ("python", "notebook", "jupyter", "pandas", "numpy", "dataframe", "colab"),
        "read and modify short Python: lists, loops, functions", 30, 600,
        "Lists are zero-indexed: `nums[0]` is the first item. `for i in range(4)` runs with `i = 0, 1, 2, 3`.\n\n"
        "```python\ndef double(x):\n    return x * 2\n\nprint(double(3))     # 6\nprint(double('ab'))  # 'abab': * repeats strings\n```",
        "1. Work through the first chapters of *Python for Everybody* (variables, conditionals, functions, loops).\n"
        "2. Do the same exercises in a Jupyter or Colab notebook so the tools are familiar too.\n"
        "3. Write a 10-line function that averages a list of numbers.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("py4e",),
        (
            LibQuestion("What does this print?\n\n```python\nnums = [3, 5, 7]\nprint(nums[1])\n```", ("5", "3", "7", "An error"),
                        "Python lists are zero-indexed, so index 1 is the second item, 5."),
            LibQuestion("What does this print?\n\n```python\ndef f(x):\n    return x * 2\n\nprint(f('ab'))\n```", ("abab", "An error", "ab2", "4"),
                        "Multiplying a string by an integer repeats it, so 'ab' * 2 is 'abab'."),
            LibQuestion("What does this print?\n\n```python\ntotal = 0\nfor i in range(4):\n    total += i\nprint(total)\n```", ("6", "10", "4", "3"),
                        "range(4) is 0, 1, 2, 3, and 0 + 1 + 2 + 3 = 6. Summing 1 to 4 (10) is the off-by-one mistake."),
        ),
    ),
    LibConcept(
        "git", "Version Control with Git",
        "Tracking changes with commits and branches, and collaborating through a shared remote repository.",
        ("git", "github", "version control", "repository", "commit", "branch", "merge"),
        "commit, branch, pull, push; resolve a merge conflict", 20, 180,
        "`git add` stages changes, `git commit` records them locally, `git push` uploads commits, and `git pull` fetches and merges others' work.\n\n"
        "When two branches change the same lines, merging stops with a **conflict** that you resolve by editing the file, then committing.",
        "1. Read *Git Basics* and *Git Branching* in Pro Git.\n"
        "2. In a practice repository, make a branch, commit on both branches, and merge them.\n"
        "3. Create a deliberate conflict and resolve it.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("progit",),
        (
            LibQuestion("Which command records your staged changes in the local repository?", ("git commit", "git push", "git add", "git clone"),
                        "git add stages, git commit records the snapshot locally, and git push uploads commits to a remote."),
            LibQuestion("Two teammates change the same lines of a file on different branches. What happens when the branches are merged?",
                        ("Git reports a merge conflict that someone resolves by hand", "Git keeps the newer edit automatically",
                         "The merge is permanently rejected", "Git deletes both edits"),
                        "Git cannot choose between competing edits to the same lines, so it marks a conflict for a person to resolve."),
            LibQuestion("What does git pull do?", ("Fetches commits from the remote and merges them into your current branch",
                                                   "Uploads your commits to the remote", "Creates a new branch", "Discards your local changes"),
                        "git pull is git fetch followed by a merge (or rebase) into the current branch."),
        ),
    ),
    LibConcept(
        "sql", "Relational Databases and SQL",
        "Tables, primary and foreign keys, and basic SQL queries.",
        ("database", "sql", "schema", "relational", "query", "backend", "entity relationship"),
        "design simple tables with keys; read SELECT queries", 25, 300,
        "A **primary key** uniquely identifies each row. A **foreign key** stores another table's primary key to link rows "
        "(each order row stores its `customer_id`).\n\n"
        "```sql\nSELECT name FROM students WHERE gpa > 3.5;\n```\nreturns the names of students whose GPA is above 3.5.",
        "1. Read the chapters on keys, relationships and SQL in *Database Design*.\n"
        "2. Sketch tables for a small app (users, posts, comments) with primary and foreign keys.\n"
        "3. Write five SELECT queries against it, including one JOIN.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("dbdesign",),
        (
            LibQuestion("What is a primary key?", ("A column (or set of columns) that uniquely identifies each row", "The first column of every table",
                                                   "A column that must hold text", "A column that points to a row in another table"),
                        "Primary keys are unique per row. A column pointing to another table's key is a foreign key."),
            LibQuestion("What does `SELECT name FROM students WHERE gpa > 3.5;` return?",
                        ("The names of students whose GPA is above 3.5", "Every column for students with GPA above 3.5",
                         "The number of students with GPA above 3.5", "The names of all students, sorted by GPA"),
                        "SELECT name picks the column, and WHERE filters the rows."),
            LibQuestion("Each customer can place many orders. How do you link an order to its customer?",
                        ("Store the customer's id in each order row as a foreign key", "Store a list of order ids in a single customer column",
                         "Copy the customer's name into the orders table as the primary key", "Create one table per customer"),
                        "In a one-to-many relationship the 'many' side holds a foreign key to the 'one' side."),
        ),
    ),
    LibConcept(
        "integration", "Integration and Area Under a Curve",
        "Definite integrals as accumulated area, evaluated with antiderivatives via the Fundamental Theorem of Calculus.",
        ("integral", "definite integral", "integration by part", "continuous random variable", "probability density", "area under", "cumulative distribution"),
        "evaluate simple definite integrals; read probabilities as areas", 25, 300,
        "If $F' = f$, then $\\int_a^b f(x)\\,dx = F(b) - F(a)$ (Fundamental Theorem of Calculus).\n\n"
        "Example: $\\int_0^2 3x^2\\,dx = [x^3]_0^2 = 8$.\n\n"
        "For a continuous random variable with density $f$: $P(a \\le X \\le b) = \\int_a^b f(x)\\,dx$.",
        "1. Review antiderivatives of polynomials and $e^x$.\n"
        "2. Read the Fundamental Theorem of Calculus section and evaluate 8 definite integrals.\n"
        "3. Compute a probability for a uniform and an exponential density.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("os-calc1",),
        (
            LibQuestion("What is ∫₀² 3x² dx?", ("8", "12", "6", "4"),
                        "An antiderivative of 3x² is x³, and 2³ − 0³ = 8."),
            LibQuestion("X is a continuous random variable with density f. What is P(a ≤ X ≤ b)?",
                        ("∫ from a to b of f(x) dx", "f(b) − f(a)", "f(b) · (b − a)", "f(a) + f(b)"),
                        "For continuous variables, probability is area under the density curve."),
            LibQuestion("If F′(x) = f(x), what is ∫ₐᵇ f(x) dx?", ("F(b) − F(a)", "F(a) − F(b)", "f(b) − f(a)", "F(b) + F(a)"),
                        "That is the Fundamental Theorem of Calculus: evaluate the antiderivative at the bounds and subtract."),
        ),
    ),
    LibConcept(
        "logs", "Logarithms and Exponentials",
        "Logarithms as inverses of exponentials, and the identities that turn products into sums.",
        ("logarithm", "logarithms", "exponential", "logistic", "softmax", "cross entropy", "log odds", "log likelihood"),
        "use log identities; read logistic and softmax formulas", 15, 120,
        "$\\log_b x = y$ means $b^y = x$. Identities: $\\ln(ab) = \\ln a + \\ln b$, $\\ln(a^k) = k\\ln a$, $e^{\\ln x} = x$.\n\n"
        "The logistic function $\\sigma(z) = \\dfrac{1}{1+e^{-z}}$ squashes any number into $(0,1)$; logistic regression models the log-odds as a line.",
        "1. Read *Logarithmic Functions*.\n"
        "2. Rewrite 10 equations between exponential and log form.\n"
        "3. Evaluate the logistic function at z = −2, 0, 2 and sketch it.\n"
        "4. Answer the practice questions here until two in a row are right.",
        ("lt-alg-log",),
        (
            LibQuestion("What is log₂ 8?", ("3", "4", "16", "6"),
                        "2³ = 8, so log₂ 8 = 3."),
            LibQuestion("Which identity is true for positive a and b?", ("ln(ab) = ln a + ln b", "ln(ab) = ln a · ln b", "ln(a + b) = ln a + ln b", "ln(ab) = ln a / ln b"),
                        "Logs turn products into sums. That is why models add log-probabilities instead of multiplying probabilities."),
            LibQuestion("What is e^(ln 5)?", ("5", "e⁵", "ln 5", "1"),
                        "e^x and ln x are inverse functions, so they undo each other."),
        ),
    ),
]

BY_KEY = {c.key: c for c in CONCEPTS}
_BY_NAME = {normalize_name(c.name): c for c in CONCEPTS}


def find(name: str) -> LibConcept | None:
    return _BY_NAME.get(normalize_name(name))


def placed_choices(q: LibQuestion, salt: str) -> tuple[list[str], int]:
    """Move the correct answer (stored first) to a deterministic, varied position."""
    pos = sum(map(ord, salt + q.prompt)) % 4
    rest = list(q.choices[1:])
    choices = rest[:pos] + [q.choices[0]] + rest[pos:]
    return choices, pos
