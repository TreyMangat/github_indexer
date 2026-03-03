from pathlib import Path

from repo_recall.indexer.chunking import chunk_file_text


def test_markdown_chunking_by_heading():
    md = """# Title

Intro.

## Section A

Hello.

## Section B

World.
"""
    chunks = chunk_file_text(Path("README.md"), md, max_chunk_chars=10_000, overlap_lines=0)
    assert len(chunks) >= 2
    assert any("Section A" in c.text for c in chunks)
    assert any("Section B" in c.text for c in chunks)


def test_python_ast_chunking():
    py = """def a():
    return 1

def b(x):
    return x + 1
"""
    chunks = chunk_file_text(Path("x.py"), py, max_chunk_chars=10_000, overlap_lines=0)
    # two top-level defs
    assert len(chunks) == 2
    assert chunks[0].start_line == 1
    assert "def a" in chunks[0].text
    assert "def b" in chunks[1].text
