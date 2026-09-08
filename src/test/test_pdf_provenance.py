"""Generated documents verify location claims without model inference."""
import json
from types import SimpleNamespace

import pymupdf

from local_read.backends.simple import SimpleBackend
from local_read.converters.base import DocumentConverterResult
from local_read.index_generator import IndexGenerator
from local_read.markdown_converter import MarkdownConverter
from local_read.orchestrator import (
    merge_chunk_intermediates,
    merge_chunk_markdowns,
    process_and_save,
)


def make_pdf(path):
    with pymupdf.open() as doc:
        for number in range(1, 5):
            page = doc.new_page()
            page.insert_text((72, 90), f'PAGE_{number}_UNIQUE textual evidence')
        doc.save(path)
    return path


def test_simple_pdf_real_locations(tmp_path):
    path = make_pdf(tmp_path / 'generated.pdf')
    result = SimpleBackend().process(path, 'pdf', extract_sections=True)
    blocks = list(result['blocks'].values())
    assert [b['page'] for b in blocks] == [1, 2, 3, 4]
    assert all(b['bbox'][0] == 72 and b['bbox'][1] < 90 < b['bbox'][3] for b in blocks)
    assert all(b['confidence'] is None for b in blocks)
    md = MarkdownConverter(result, include_metadata=False).convert()
    assert all(md.count(f'PAGE_{n}_UNIQUE') == 1 for n in range(1, 5))


def test_sliced_artifacts_and_overlap_have_source_pages(tmp_path):
    path = make_pdf(tmp_path / 'generated.pdf')
    results = []
    for index, (start, end) in enumerate(((1, 2), (2, 3))):
        output = tmp_path / str(index)
        output.mkdir()
        result = process_and_save(
            str(path), SimpleBackend(), 'pdf', output, output / 'images',
            SimpleNamespace(phys_start=start, phys_end=end, title='Chunk'), {},
        )
        saved = json.loads(result['intermediate_path'].read_text())
        assert saved['source']['path'] == str(path)
        assert saved['source']['page_count'] == 4
        assert [b['page'] for b in saved['blocks'].values()] == [start + 1, end + 1]
        index_data = json.loads(result['index_path'].read_text())
        assert [p['page'] for p in index_data['pages']] == [start + 1, end + 1]
        results.append(result)
    merged = merge_chunk_intermediates(str(path), 'pdf', results)
    assert [b['page'] for b in merged['blocks'].values()] == [2, 3, 4]
    md = merge_chunk_markdowns(results)
    assert 'PAGE_1_UNIQUE' not in md
    assert all(md.count(f'PAGE_{n}_UNIQUE') == 1 for n in (2, 3, 4))


def test_unknown_locations_are_not_invented_or_duplicated(monkeypatch, tmp_path):
    path = tmp_path / 'file.pdf'
    path.touch()
    backend = SimpleBackend()
    monkeypatch.setattr(backend, '_get_converter', lambda _: lambda *a, **k: DocumentConverterResult(
        text_content='Heading\nBody', sections=[{'title': 'Heading', 'content': 'Body'}],
        tables=[{'markdown': 'Body'}], metadata={'pdf_page_count': 8},
    ))
    result = backend.process(path, 'pdf')
    block = next(iter(result['blocks'].values()))
    assert block['page'] is None and block['bbox'] is None and block['confidence'] is None
    assert len(result['blocks']) == 1
    index = IndexGenerator(result).generate()
    assert index['sections'][0]['title'] == 'Heading'
    assert index['sections'][0]['page'] is None
    assert index['sections'][0]['block_id'] is None
    assert len(index['tables']) == 1
    assert index['unlocated_block_ids'] == result['reading_order']
    assert all(not p['block_ids'] for p in index['pages'])
    merged = merge_chunk_intermediates(str(path), 'pdf', [
        {'intermediate': result, 'phys_start': 5, 'phys_end': 7}])
    assert next(iter(merged['blocks'].values()))['page'] is None
