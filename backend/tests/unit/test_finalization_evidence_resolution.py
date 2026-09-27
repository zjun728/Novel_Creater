from hashlib import sha256

import pytest

from backend.gateways.finalization_provider import _hydrate_evidence


def test_quote_resolves_unicode_scalars_instead_of_model_offsets():
    prose = '前文😀。右耳忽然嗡了一声。后文。'
    quote = '右耳忽然嗡了一声。'
    result = _hydrate_evidence({'quote': quote, 'confidence': 0.9, 'rationale': '耳鸣'}, prose)
    assert result == {'startScalar': 4, 'endScalar': 13,
                      'excerptHash': sha256(quote.encode()).hexdigest(),
                      'confidence': 0.9, 'rationale': '耳鸣'}


@pytest.mark.parametrize('quote', ['', '不存在', '重复', ' 重复'])
def test_missing_empty_or_ambiguous_quote_is_rejected(quote):
    with pytest.raises(ValueError):
        _hydrate_evidence({'quote': quote, 'confidence': 0.9, 'rationale': '依据'}, '重复。重复。')


def test_offset_only_model_evidence_is_no_longer_accepted():
    with pytest.raises(ValueError):
        _hydrate_evidence({'startScalar': 0, 'endScalar': 1, 'confidence': 0.9, 'rationale': '错误位置'}, '正文')


def test_numbered_original_paragraphs_resolve_repeated_quotes_without_offsets():
    prose = '重复😀。\n\n右耳耳鸣。\n\n重复😀。'
    result = _hydrate_evidence({'paragraphIds': ['p2', 'p3'], 'confidence': 0.9, 'rationale': '后文'}, prose)
    quote = '右耳耳鸣。\n\n重复😀。'
    assert result['startScalar'] == 6
    assert result['endScalar'] == len(prose)
    assert result['excerptHash'] == sha256(quote.encode()).hexdigest()


@pytest.mark.parametrize('ids', [[], ['p9'], ['p1', 'p3'], ['p2', 'p1'], ['p1', 'p1'], 'p1'])
def test_paragraph_selection_must_be_known_unique_contiguous_and_ordered(ids):
    with pytest.raises(ValueError):
        _hydrate_evidence({'paragraphIds': ids, 'confidence': 0.9, 'rationale': '依据'}, '第一段\n\n第二段\n\n第三段')


@pytest.mark.parametrize('selected,expected', [
    ({'start': 'p2', 'end': 'p2'}, '中间😀段。'),
    ({'start': 'p1', 'end': 'p3'}, '首段。\r\n\r\n中间😀段。\r\n\r\n末段𠮷。'),
])
def test_paragraph_range_hydrates_complete_original_unicode_crlf_interval(selected, expected):
    prose = '首段。\r\n\r\n中间😀段。\r\n\r\n末段𠮷。'
    result = _hydrate_evidence({'paragraphRange': selected, 'confidence': 0.9, 'rationale': '依据'}, prose)
    assert result == {
        'startScalar': prose.index(expected), 'endScalar': prose.index(expected) + len(expected),
        'excerptHash': sha256(expected.encode('utf-8')).hexdigest(),
        'confidence': 0.9, 'rationale': '依据',
    }
    assert set(result) == {'startScalar', 'endScalar', 'excerptHash', 'confidence', 'rationale'}


@pytest.mark.parametrize('selected', [
    None, [], 'p1', {}, {'start': 'p1'}, {'end': 'p1'},
    {'start': 'p9', 'end': 'p2'}, {'start': 'p1', 'end': 'p9'},
    {'start': 'p2', 'end': 'p1'}, {'start': 'p1', 'end': 'p2', 'extra': 'p1'},
    {'start': 1, 'end': 'p2'}, {'start': 'p1', 'end': 2},
    {'start': True, 'end': 'p2'}, {'start': 'p1', 'end': None},
])
def test_invalid_paragraph_range_is_rejected_without_fallback(selected):
    with pytest.raises(ValueError):
        _hydrate_evidence({'paragraphRange': selected, 'confidence': 0.9, 'rationale': '依据'}, '第一段\n\n第二段')


@pytest.mark.parametrize('extra', [
    {'paragraphIds': ['p1']}, {'quote': '第一段'}, {'startScalar': 0},
])
def test_paragraph_range_cannot_mix_with_legacy_evidence_fields(extra):
    with pytest.raises(ValueError):
        _hydrate_evidence({'paragraphRange': {'start': 'p1', 'end': 'p1'},
                           'confidence': 0.9, 'rationale': '依据', **extra}, '第一段')
