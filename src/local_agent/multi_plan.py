"""候选方案 -> 静态校验 -> 模型选择 -> 单步执行 -> 观察后重规划。"""
import uuid
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .integrity import fingerprint


class PlanStep(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    tool: Literal['describe_metric', 'get_context', 'run_query', 'run_comparison',
                  'run_diagnosis', 'run_multi_fact']
    arguments: dict


class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    label: str = Field(min_length=1, max_length=120)
    approach: str = Field(min_length=1, max_length=600)
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=6)


class Proposals(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidates: tuple[Candidate, ...] = Field(min_length=2, max_length=3)


class PlanSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str


class StepRequest(PlanSelection):
    step_index: int = Field(ge=0, le=5)


class MultiPlanManager:
    """仅保存当前 turn 的逻辑方案；SQL 计划仍由服务端即时生成与校验。"""
    costs = {'describe_metric': 0, 'get_context': 0, 'run_query': 1,
             'run_multi_fact': 1, 'run_comparison': 2, 'run_diagnosis': 16}

    def __init__(self, adapter, guard):
        self.adapter, self.guard = adapter, guard
        self.candidates, self.history = {}, []
        self.selected = None
        self.objective = None
        self.revision = 0

    def propose(self, proposals):
        if self.revision >= 3:
            raise RuntimeError('Plan revision budget exhausted')
        prepared = []
        release = self.adapter.tools.release()
        from .semantic_context import SemanticContextResolver
        semantic_resolver = SemanticContextResolver(self.adapter.tools)
        def validate_query(query):
            effective, role = self.adapter.tools.enforce_request(query)
            self.adapter.tools.compiler.compile(effective, role['minimum_group_size'])
            semantic_resolver.resolve_request(effective)
        for candidate in proposals.candidates:
            signatures, canonical = [], []
            for step in candidate.steps:
                try:
                    data = self.adapter.validate(step.tool, step.arguments)
                    self.guard(step.tool, data)
                    from .temporal import check_window
                    if step.tool in ('run_query', 'run_multi_fact'):
                        check_window(data, release.get('temporal', {}))
                    elif step.tool in ('run_comparison', 'run_diagnosis'):
                        check_window(data.current if step.tool == 'run_comparison' else data.query, release.get('temporal', {}))
                        check_window(data.baseline, release.get('temporal', {}))
                    # 静态预检口径/维度，不执行数据库查询，不生成可替换的模型 SQL。
                    if step.tool == 'run_query':
                        validate_query(data)
                    elif step.tool == 'run_multi_fact':
                        validate_query(data)
                    elif step.tool in ('describe_metric', 'get_context'):
                        self.adapter.tools.describe(data.metric_id)
                    elif step.tool == 'run_comparison':
                        # 实际 compare 会再次验证；候选阶段先阻止不同口径/窗口。
                        b, c = data.baseline, data.current
                        if (b.metric_id, b.filters, b.group_by) != (c.metric_id, c.filters, c.group_by) or b.end-b.start != c.end-c.start or not (b.end <= c.start or c.end <= b.start):
                            raise ValueError('Comparison semantics differ or overlap')
                        for q in (b, c):
                            validate_query(q)
                    elif step.tool == 'run_diagnosis':
                        if data.kind != 'diagnose':
                            raise ValueError('Diagnosis task required')
                        for q in (data.query, data.baseline):
                            validate_query(q)
                    body = data.model_dump(mode='json')
                    canonical.append({'tool': step.tool, 'arguments': body})
                    if self.costs[step.tool]:
                        signatures.append(fingerprint({'tool': step.tool, 'arguments': body}))
                except Exception as error:
                    from .access import AccessDenied
                    if isinstance(error, AccessDenied):
                        raise
                    raise ValueError('Invalid candidate plan: ' + str(error)) from None
            if not signatures:
                raise ValueError('Invalid candidate plan: requires an executable evidence step')
            prepared.append((candidate, canonical, sorted(set(signatures))))
        # 候选可以改变先查上下文还是直接查数，但不能以“优化”为名改变业务问题。
        objective = prepared[0][2]
        if any(s != objective for _, _, s in prepared) or (self.objective is not None and self.objective != objective):
            raise ValueError('Invalid candidate plan: alternatives/revisions must preserve the same objective')
        if len({fingerprint(steps) for _, steps, _ in prepared}) != len(prepared):
            raise ValueError('Invalid candidate plan: alternatives must be distinct')
        if self.selected:
            self.history.append(self.candidates[self.selected].copy())
        self.revision += 1
        self.objective = objective
        self.selected = None
        self.candidates = {}
        for candidate, steps, _ in prepared:
            identifier = 'p-' + uuid.uuid4().hex[:12]
            self.candidates[identifier] = {'plan_id': identifier, 'revision': self.revision,
                'label': candidate.label, 'approach': candidate.approach, 'steps': steps,
                'next_step': 0, 'status': 'VALIDATED',
                'query_attempt_upper_bound': sum(self.costs[s['tool']] for s in steps),
                'cost_scope': 'logical calls before transient retries; not latency/financial estimate'}
        return self.snapshot()

    def select(self, request):
        if request.plan_id not in self.candidates:
            raise ValueError('Invalid plan selection: unknown current candidate')
        if self.selected:
            raise ValueError('Invalid plan selection: re-propose before switching an active plan')
        self.selected = request.plan_id
        plan = self.candidates[self.selected]
        plan['status'] = 'SELECTED'
        return plan.copy()

    def execute_step(self, request):
        if self.selected != request.plan_id:
            raise ValueError('Invalid plan step: plan is not selected')
        plan = self.candidates[request.plan_id]
        if request.step_index != plan['next_step'] or request.step_index >= len(plan['steps']):
            raise ValueError('Invalid plan step: out-of-order or already executed')
        step = plan['steps'][request.step_index]
        data = self.adapter.validate(step['tool'], step['arguments'])
        self.guard(step['tool'], data)  # 执行前重验用户条件，不只信候选阶段。
        result = self.adapter.call(step['tool'], step['arguments'])
        plan['next_step'] += 1
        plan['status'] = 'COMPLETE' if plan['next_step'] == len(plan['steps']) else 'RUNNING'
        return {'plan_id': request.plan_id, 'step_index': request.step_index,
                'tool': step['tool'], 'result': result, 'plan_status': plan['status']}

    def snapshot(self):
        # 历史观察不能因下一轮状态变化而被原地改写。
        return json.loads(json.dumps({'revision': self.revision, 'selected_plan_id': self.selected,
                'candidates': list(self.candidates.values()), 'superseded': self.history}))
