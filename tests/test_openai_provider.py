"""官方响应协议的模拟测试；不将它标记为真实模型验收。"""
import json
import httpx
import pytest
from local_agent.openai_provider import request_task, task_schema


def configured(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','mock-secret')
    monkeypatch.setenv('OPENAI_MODEL','test-model')


def test_official_request_and_conversion(monkeypatch):
    configured(monkeypatch)
    task={'kind':'query','query':{'metric_id':'order_count@1','start':'2026-09-01',
          'end':'2026-10-01','group_by':[],'filters':[{'dimension':'country','value':'US'}],
          'limit':100},'baseline':None,'expected_direction':'unknown','diagnosis_dimensions':[]}
    def handler(request):
        body=json.loads(request.content)
        assert str(request.url)=='https://api.openai.com/v1/responses'
        assert body['store'] is False
        assert body['text']['format']['strict'] is True
        return httpx.Response(200,json={'status':'completed','id':'resp-test','model':'test-model',
            'usage':{'total_tokens':100},'output':[{'type':'message','content':[
                {'type':'output_text','text':json.dumps({'clarify':None,'task':task})}]}]})
    result,evidence=request_task('问题',{},httpx.MockTransport(handler))
    assert result['query']['filters']=={'country':'US'}
    assert evidence['live'] is False and 'mock-secret' not in json.dumps(evidence)


@pytest.mark.parametrize('payload,message',[
    ({'status':'incomplete'},'MODEL_INCOMPLETE'),
    ({'status':'completed','output':[{'type':'message','content':[{'type':'refusal'}]}]},'MODEL_REFUSAL'),
    ({'status':'completed','output':[]},'MODEL_INVALID_OUTPUT')])
def test_stop_on_unusable_output(monkeypatch,payload,message):
    configured(monkeypatch)
    with pytest.raises(ValueError,match=message):
        request_task('问题',{},httpx.MockTransport(lambda _:httpx.Response(200,json=payload)))


def test_error_body_not_exposed(monkeypatch):
    configured(monkeypatch)
    with pytest.raises(ValueError) as error:
        request_task('问题',{},httpx.MockTransport(lambda _:httpx.Response(401,text='mock-secret')))
    assert 'mock-secret' not in str(error.value)


def test_schema_all_object_properties_required():
    def check(value):
        if isinstance(value,dict):
            if value.get('type')=='object':
                assert value['additionalProperties'] is False
                assert set(value['required'])==set(value['properties'])
            for child in value.values(): check(child)
        elif isinstance(value,list):
            for child in value: check(child)
    check(task_schema())
