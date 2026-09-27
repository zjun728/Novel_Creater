from copy import deepcopy
import json

import httpx
import pytest

from backend.gateways.finalization_provider import _parse_extraction
from backend.gateways.openai_json_transport import OpenAIJSONTransport
from backend.tests.unit.test_finalization_gateway import _extraction_payload, _provider


def _event(identity, **overrides):
    return {'id':identity,'entityId':None,'factKind':'dynamic_event','fieldPath':'event.record',
            'value':'记录账目','effectiveStartChapter':1,'effectiveEndChapter':None,
            'assertionOperator':'equals','valueCardinality':'single',
            'evidence':{'paragraphRange':{'start':'p1','end':'p1'},'confidence':0.8,'rationale':'当场记账'},**overrides}


def test_identical_facts_same_evidence_are_coalesced_without_touching_input():
    payload=_extraction_payload();payload['planningSuggestions']=[]
    payload['canonEvents']=[_event('one'),_event('two')]
    payload['canonEvents'][1]['evidence']['rationale']='同一次记账'
    payload['canonEvents'][1]['evidence']['confidence']=0.9
    before=deepcopy(payload)
    result=_parse_extraction(payload,'甲记下账目。')
    assert result is not None
    assert [item.id for item in result.canon_events]==['one']
    assert payload==before


@pytest.mark.parametrize('override',[
    {'value':'账目已交出'}, {'factKind':'claim'}, {'effectiveStartChapter':2},
    {'evidence':{'paragraphRange':{'start':'p2','end':'p2'},'confidence':0.8,'rationale':'另一次记账'}},
])
def test_distinct_facts_or_evidence_are_not_coalesced(override):
    payload=_extraction_payload();payload['planningSuggestions']=[]
    payload['canonEvents']=[_event('one'),_event('two',**override)]
    assert len(_parse_extraction(payload,'甲记下账目。\n\n乙记下账目。').canon_events)==2


def test_duplicate_ids_are_rejected_before_coalescing():
    payload=_extraction_payload();payload['planningSuggestions']=[]
    payload['canonEvents']=[_event('one'),_event('one')]
    assert _parse_extraction(payload,'甲记下账目。') is None


def test_structured_fact_values_survive_coalescing():
    payload = _extraction_payload()
    payload['planningSuggestions'] = []
    value = {'counts': [11, 11], 'total': 22}
    payload['canonEvents'] = [
        _event('one', value=value), _event('two', value=deepcopy(value)),
        _event('three', value={'counts': [11, 11], 'total': 18}),
    ]
    result = _parse_extraction(payload, '甲记下账目。')
    assert result is not None
    assert [event.id for event in result.canon_events] == ['one', 'three']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,stage',[
    ('http','http_status'),('envelope','envelope_json'),('content','content_json'),('timeout','timeout'),
])
async def test_json_failures_log_only_closed_diagnostics(mode,stage,caplog):
    secret='PRIVATE_REMOTE_BODY_AND_URL'
    def handler(request):
        if mode=='timeout':raise httpx.ReadTimeout(secret,request=request)
        if mode=='http':return httpx.Response(429,text=secret)
        if mode=='envelope':return httpx.Response(200,text=secret)
        return httpx.Response(200,json={'choices':[{'message':{'content':secret}}]})
    resource=OpenAIJSONTransport(transport=httpx.MockTransport(handler),timeout_seconds=1,response_byte_limit=16384)
    await resource.start()
    try:
        with caplog.at_level('WARNING'):
            result=await resource.request(provider=_provider(),model_name='test',messages=[{'role':'user','content':'审查'}])
        assert not result.succeeded
        assert f'stage={stage}' in caplog.text
        assert 'request_id=' in caplog.text
        for private in (secret,_provider()['api_key'],_provider()['base_url']):assert private not in caplog.text
    finally:await resource.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,stage', [('partial', 'sse_termination'), ('malformed', 'sse_frame'), ('http', 'http_status'), ('timeout', 'timeout')])
async def test_stream_failures_keep_partial_output_failed_and_log_safe_stage(mode, stage, caplog):
    from backend.gateways.chapter_draft_provider import ChapterDraftProviderGateway, ChapterDraftProviderError
    from backend.tests.unit.test_chapter_draft_provider_gateway import StaticStream, _stream

    secret = 'PRIVATE_REMOTE_BODY_AND_URL'
    def handler(request):
        if mode == 'timeout':
            raise httpx.ReadTimeout(secret, request=request)
        if mode == 'http':
            return httpx.Response(429, text=secret)
        content = b'data: {"choices":[{"index":0,"delta":{"content":"partial"}}]}\n\n'
        if mode == 'malformed':
            content += ('data: ' + secret + '\n\n').encode()
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=StaticStream(content))
    gateway = ChapterDraftProviderGateway(transport=httpx.MockTransport(handler))
    with caplog.at_level('WARNING'), pytest.raises(ChapterDraftProviderError):
        await _stream(gateway)
    assert f'stage={stage}' in caplog.text
    assert 'request_id=' in caplog.text
    assert 'received_bytes=' in caplog.text
    for private in (secret, 'PRIVATE_PROVIDER_KEY', 'https://provider.invalid/v1'):
        assert private not in caplog.text
