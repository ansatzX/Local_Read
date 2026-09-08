"""Fix common LaTeX formula parsing issues from PDF extraction."""

import re


def fix_latex_formulas(content: str) -> str:
    """Fix common LaTeX formula parsing issues from PDF extraction.

    This function replaces common LaTeX parsing artifacts with proper Unicode characters:
    - CID placeholders (cid:XXX) with corresponding characters
    - LaTeX commands like \\alpha with Greek letters (α)
    - Mathematical symbols like \\times with Unicode (×)
    - Simplifies superscripts and subscripts notation

    Args:
        content: Content string with LaTeX formulas that need fixing

    Returns:
        Content with fixed LaTeX formulas converted to Unicode

    Note:
        This is a best-effort conversion. Some complex LaTeX formulas
        may not be fully converted.
    """
    if not content:
        return content

    # Fix (cid:XXX) placeholders - using simple replace instead of regex
    cid_map = {
        '(cid:16)': '〈',
        '(cid:17)': '〉',
        '(cid:40)': '(',
        '(cid:41)': ')',
        '(cid:91)': '[',
        '(cid:93)': ']',
        '(cid:123)': '{',
        '(cid:125)': '}',
        '(cid:60)': '<',
        '(cid:62)': '>',
        '(cid:34)': '"',
        '(cid:39)': "'",
        '(cid:44)': ',',
        '(cid:46)': '.',
        '(cid:58)': ':',
        '(cid:59)': ';',
        '(cid:61)': '=',
        '(cid:43)': '+',
        '(cid:45)': '-',
        '(cid:42)': '*',
        '(cid:47)': '/',
        '(cid:92)': '\\',
        '(cid:124)': '|',
    }
    for pattern, replacement in cid_map.items():
        content = content.replace(pattern, replacement)

    # Fix Greek letters - use replace instead of re.sub
    greek_map = {
        r'\alpha': 'α',
        r'\beta': 'β',
        r'\gamma': 'γ',
        r'\delta': 'δ',
        r'\epsilon': 'ε',
        r'\zeta': 'ζ',
        r'\eta': 'η',
        r'\theta': 'θ',
        r'\iota': 'ι',
        r'\kappa': 'κ',
        r'\lambda': 'λ',
        r'\mu': 'μ',
        r'\nu': 'ν',
        r'\xi': 'ξ',
        r'\pi': 'π',
        r'\rho': 'ρ',
        r'\sigma': 'σ',
        r'\tau': 'τ',
        r'\upsilon': 'υ',
        r'\phi': 'φ',
        r'\chi': 'χ',
        r'\psi': 'ψ',
        r'\omega': 'ω',
        r'\Alpha': 'Α',
        r'\Beta': 'Β',
        r'\Gamma': 'Γ',
        r'\Delta': 'Δ',
        r'\Epsilon': 'Ε',
        r'\Zeta': 'Ζ',
        r'\Eta': 'Η',
        r'\Theta': 'Θ',
        r'\Iota': 'Ι',
        r'\Kappa': 'Κ',
        r'\Lambda': 'Λ',
        r'\Mu': 'Μ',
        r'\Nu': 'Ν',
        r'\Xi': 'Ξ',
        r'\Pi': 'Π',
        r'\Rho': 'Ρ',
        r'\Sigma': 'Σ',
        r'\Tau': 'Τ',
        r'\Upsilon': 'Υ',
        r'\Phi': 'Φ',
        r'\Chi': 'Χ',
        r'\Psi': 'Ψ',
        r'\Omega': 'Ω',
    }
    for latex_cmd, unicode_char in greek_map.items():
        content = content.replace(latex_cmd, unicode_char)

    # Fix mathematical symbols
    math_map = {
        r'\times': '×',
        r'\div': '÷',
        r'\pm': '±',
        r'\mp': '∓',
        r'\leq': '≤',
        r'\geq': '≥',
        r'\neq': '≠',
        r'\approx': '≈',
        r'\equiv': '≡',
        r'\propto': '∝',
        r'\infty': '∞',
        r'\partial': '∂',
        r'\nabla': '∇',
        r'\cdot': '·',
        r'\cdots': '⋯',
        r'\vdots': '⋮',
        r'\ddots': '⋱',
        r'\int': '∫',
        r'\sum': '∑',
        r'\prod': '∏',
        r'\cup': '∪',
        r'\cap': '∩',
        r'\in': '∈',
        r'\notin': '∉',
        r'\subset': '⊂',
        r'\supset': '⊃',
        r'\subseteq': '⊆',
        r'\supseteq': '⊇',
        r'\emptyset': '∅',
        r'\forall': '∀',
        r'\exists': '∃',
        r'\neg': '¬',
        r'\wedge': '∧',
        r'\vee': '∨',
        r'\rightarrow': '→',
        r'\leftarrow': '←',
        r'\Rightarrow': '⇒',
        r'\Leftarrow': '⇐',
        r'\Leftrightarrow': '⇔',
    }
    for latex_cmd, unicode_char in math_map.items():
        content = content.replace(latex_cmd, unicode_char)

    # Fix superscripts and subscripts
    content = re.sub(r'\^\{(\d+)\}', r'^\1', content)  # ^{2} → ^2
    content = re.sub(r'_\{(\d+)\}', r'_\1', content)  # _{2} → _2
    content = re.sub(r'\^\{([a-zA-Z])\}', r'^\1', content)  # ^{x} → ^x
    content = re.sub(r'_\{([a-zA-Z])\}', r'_\1', content)  # _{x} → _x

    return content
