"""Stable source paragraphs; offsets are computed from the untouched Candidate."""
import re


def source_paragraphs(prose: str) -> list[dict]:
    return [
        {'id': f'p{index}', 'text': match.group(),
         'startScalar': match.start(), 'endScalar': match.end()}
        for index, match in enumerate(re.finditer(r'\S[\s\S]*?(?=\r?\n\s*\r?\n|\Z)', prose), 1)
    ]
