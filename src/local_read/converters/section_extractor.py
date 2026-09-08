"""Extract sections/headings from markdown content."""

from typing import Any, Dict, List


def extract_sections_from_markdown(content: str) -> List[Dict[str, Any]]:
    """Extract sections from markdown text based on headings.

    Args:
        content: Markdown content

    Returns:
        List of section dictionaries with heading, level, content, etc.
    """
    sections = []
    lines = content.split('\n')
    current_section = None
    section_content = []

    # Pre-calculate line start positions for O(n) performance
    line_start_positions = [0] * len(lines)
    current_pos = 0
    for i, line in enumerate(lines):
        line_start_positions[i] = current_pos
        current_pos += len(line) + 1  # +1 for newline
    total_chars = current_pos - 1 if lines else 0

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped.startswith('#'):
            # Save previous section if exists
            if current_section is not None:
                sections.append({
                    "heading": current_section['heading'],
                    "level": current_section['level'],
                    "content": '\n'.join(section_content).strip(),
                    "start_line": current_section['start_line'],
                    "end_line": i - 1,
                    "char_start": current_section['char_start'],
                    "char_end": line_start_positions[i] - 1 if i > 0 else 0
                })

            # Start new section
            heading_text = line.lstrip('#').strip()
            level = len(line) - len(line.lstrip('#'))
            current_section = {
                'heading': heading_text,
                'level': level,
                'start_line': i,
                'char_start': line_start_positions[i]
            }
            section_content = []
        elif current_section is not None:
            section_content.append(line)

    # Add the last section if exists
    if current_section is not None:
        sections.append({
            "heading": current_section['heading'],
            "level": current_section['level'],
            "content": '\n'.join(section_content).strip(),
            "start_line": current_section['start_line'],
            "end_line": len(lines) - 1,
            "char_start": current_section['char_start'],
            "char_end": total_chars
        })

    return sections
