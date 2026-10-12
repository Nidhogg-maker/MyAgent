"""可执行 Skill 注册表：契约、权限前置、预算与业务实现分别管理。"""
import time
from pydantic import BaseModel, ConfigDict, Field
from .semantic import Query, ROOT
from .tasks import Task

class SkillSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str
    entrypoint: str
    version: str = '1'
    description: str
    input_schema: dict
    output_schema: dict
    tools: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    max_queries: int = Field(ge=0, le=16)
    timeout_seconds: int = Field(default=60, ge=1, le=120)
    permission_scope: str = 'server-authorized metric/dimension/row scope'
    preconditions: str = 'trusted identity, current release and validated input'
    postconditions: str = 'structured evidence; no causal claim'
    retry_policy: str = 'bounded transient-only retry with shared circuit breaker'
    idempotency: str = 'read-only; runtime reuses authorized release-bound receipts'

class Pair(BaseModel):
    model_config = ConfigDict(extra='forbid')
    baseline: Query
    current: Query

class QualityInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric_id: str
    current: Query | None = None
    baseline: Query | None = None

class ReportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str
    evidence: dict
    task: dict | None = None

class EvidenceOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skill_id: str
    version: str
    result: dict
    elapsed_seconds: float

class SkillRegistry:
    def __init__(self):
        self.specs, self.inputs = {}, {}
        from .feature_agent import FeatureRequest
        for identifier, description, model, tools, dependencies, budget in [
            ('metric-query','执行受控指标查询',Query,('plan','execute'),(),1),
            ('comparison','校验可比窗口并比较',Pair,('plan','execute'),('metric-query',),2),
            ('drilldown','执行合法维度分组查询',Query,('plan','execute'),('metric-query',),1),
            ('quality-check','检查目录质量与时间覆盖',QualityInput,('context','release'),(),0),
            ('anomaly-analysis','有界异常分析工作流',Task,('plan','execute','context'),('comparison','drilldown','quality-check'),16),
            ('evidence-report','返回证据与未解决项',ReportInput,(),(),0),
            ('profile-query','读取版本化画像及会话数据产品',FeatureRequest,('read_profile',),(),1)]:
            self.inputs[identifier] = model
            from .skill_resources import entry
            self.specs[identifier] = SkillSpec(id=identifier,description=description,
                entrypoint=str(entry(identifier).relative_to(ROOT)),
                input_schema=model.model_json_schema(),output_schema=EvidenceOutput.model_json_schema(),
                tools=tools,dependencies=dependencies,max_queries=budget)
            if identifier=='profile-query':
                self.specs[identifier]=self.specs[identifier].model_copy(update={
                    'permission_scope':'local administrative identity; aggregate-only credentials denied',
                    'retry_policy':'no automatic retries; fixed read-only worker timeout',
                    'postconditions':'versioned profile evidence; no payment or negative-label claim'})
        self.validate()

    def validate(self):
        """启动时验证依赖完整、无环；不是让模型任意拼接函数名。"""
        def visit(identifier, path):
            if identifier in path: raise ValueError('Skill dependency cycle')
            if identifier not in self.specs: raise ValueError('Unknown skill dependency')
            if len(path) >= 4: raise ValueError('Skill maximum depth exceeded')
            for child in self.specs[identifier].dependencies: visit(child, path+(identifier,))
        for identifier in self.specs: visit(identifier, ())

class SkillExecutor:
    def __init__(self, tools, registry=None):
        self.tools, self.registry = tools, registry or SkillRegistry()
        self.stack = []

    def run(self, identifier, payload):
        from .skill_resources import resources
        loaded=resources(identifier,references=identifier in ('anomaly-analysis','profile-query'))
        spec = self.registry.specs[identifier]
        if identifier in self.stack or len(self.stack) >= 4:
            raise ValueError('Skill recursion/depth denied')
        self.tools.access.role()
        data = self.registry.inputs[identifier].model_validate(payload)
        started = time.monotonic()
        self.stack.append(identifier)
        if hasattr(self.tools,'emit'): self.tools.emit('skill-start',{'skill':identifier,'version':spec.version,'entrypoint':loaded['entry'],'resource_sha256':loaded['sha256'],'references':list(loaded['references'])})
        try:
            if identifier == 'profile-query':
                from .feature_agent import FeatureTools
                target = self.tools if isinstance(self.tools,FeatureTools) else FeatureTools(self.tools)
                result = target.read_profile(data)
            elif identifier in ('metric-query','drilldown'):
                if identifier == 'drilldown' and not data.group_by:
                    raise ValueError('Drilldown requires a dimension')
                from .dimensions import DimensionResolver
                resolver=getattr(self.tools,'dimension_resolver',None)
                if resolver is None:
                    resolver=DimensionResolver(self.tools)
                    self.tools.dimension_resolver=resolver
                data=resolver.query(data)
                plan = self.tools.plan(data)
                result = self.tools.execute(plan['plan_id'],plan['approval_hash'],timeout_seconds=spec.timeout_seconds)
            elif identifier == 'comparison':
                # Task复用严格的同口径、等时长、不重叠验证。
                Task(kind='diagnose',query=data.current,baseline=data.baseline)
                evidence = [self.run('metric-query',q.model_dump(mode='json'))['result'] for q in (data.baseline,data.current)]
                if any(e['result_may_be_truncated'] for e in evidence): raise ValueError('Truncated comparison')
                values=[e['rows'][0][-1] if len(e['rows'])==1 else None for e in evidence]
                old,new=values
                result = {'evidence':evidence,'causal_claim':False,'baseline':old,'current':new,
                          'delta':float(new)-float(old) if old is not None and new is not None else None}
            elif identifier == 'quality-check':
                context = self.tools.context(data.metric_id)
                release = self.tools.release()
                result = {'quality':context['metadata']['quality'],'temporal':release['temporal'],
                    'release_id':release['release_id'],'causal_claim':False}
                import datetime as dt
                metric=self.tools.describe(data.metric_id)
                observed=dt.datetime.fromisoformat(release['temporal']['observed_at']).date()
                cohorts={}
                for name,window in (('current',data.current),('baseline',data.baseline)):
                    if window:
                        if window.metric_id!=data.metric_id: raise ValueError('Quality window metric mismatch')
                        cohorts[name]={'youngest_order_age_days':(observed-(window.end-dt.timedelta(days=1))).days,
                            'oldest_order_age_days':(observed-window.start).days}
                result['semantic_version']=self.tools.registry.version
                result['cohort_observation']={'age_ranges':cohorts,'historical_status_verified':False,
                    'maturity_required':bool(metric.get('time_semantics')),
                    'maturity_verified':False,'note':'订单年龄是快照观察条件；没有历史状态/成熟度标准，不据此确认业务原因'}
            elif identifier == 'anomaly-analysis':
                from .diagnosis import DiagnosisEngine
                described=self.tools.describe(data.query.metric_id)
                if not set(data.diagnosis_dimensions)<=set(described['fact']['dimensions'])|{'day'}:
                    raise ValueError('CLARIFY: 诊断维度不符合指标grain或当前本地范围')
                result = DiagnosisEngine(self.tools,max_queries=spec.max_queries,deadline_seconds=spec.timeout_seconds,executor=self).run(data)
            else:
                from .reporting import render_report
                result = {'kind':data.kind,'causal_claim':False,'evidence':data.evidence,
                    'summary':data.evidence.get('conclusion','已执行指定口径；数值与限制见证据'),
                    'markdown':render_report(data.kind,data.evidence,data.task)}
            elapsed = time.monotonic()-started
            if elapsed > spec.timeout_seconds: raise TimeoutError('Skill deadline exceeded')
            return EvidenceOutput(skill_id=identifier,version=spec.version,result=result,elapsed_seconds=elapsed).model_dump()
        finally:
            self.stack.pop()
            if hasattr(self.tools,'emit'): self.tools.emit('skill-end',{'skill':identifier,'elapsed_seconds':time.monotonic()-started})
