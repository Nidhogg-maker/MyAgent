"""模型可选择的有限工具；业务执行仍由受控 Skill 完成。"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .semantic import Query
from .tasks import Task
from .skills import Pair, SkillExecutor
from .multi_fact import MultiFactQuery
from .multi_plan import Proposals, PlanSelection, StepRequest
from .retrieval_service import get_retrieval_service
from .semantic_context import SemanticContextResolver


class SearchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=6, ge=1, le=10)
    partition: str | None = Field(default=None,max_length=80)


class RelationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    node_id: str = Field(min_length=1,max_length=200)
    direction: Literal['dependencies','impact'] = 'dependencies'
    max_depth: int = Field(default=3,ge=1,le=6)
    max_nodes: int = Field(default=80,ge=1,le=200)


class MetricInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric_id: str = Field(min_length=1)


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric_ids: tuple[str, ...] = Field(min_length=1, max_length=6)
    requested_dimensions: tuple[str, ...] = Field(default=(), max_length=4)
    value_dimensions: tuple[str, ...] = Field(default=(), max_length=2)
    expected_asset_version: str | None = None


class AgentToolRouter:
    """模型动作适配器：公布工具 schema、验证参数并路由到业务服务/Skill。

    不负责保存数据 release 或执行任意 SQL。tools 通常为带预算的 RuntimeTools，
    其内层 QueryService 才是可信查询服务。两个边界不能因旧名称相同而混淆。
    """
    inputs = {'search_business': SearchInput, 'describe_metric': MetricInput,
              'get_context': MetricInput, 'run_query': Query,
              'run_comparison': Pair, 'run_diagnosis': Task, 'run_multi_fact': MultiFactQuery,
              'propose_plans': Proposals, 'select_plan': PlanSelection, 'run_plan_step': StepRequest,
              'resolve_semantics': ResolveInput,'query_relations':RelationInput}
    descriptions = {
        'search_business': '检索业务知识、指标候选和分析参考；不能覆盖权威公式。',
        'describe_metric': '读取指标权威定义、grain 和合法维度。',
        'get_context': '读取授权指标的元数据、质量和血缘。',
        'run_query': '执行已明确口径、UTC闭开日期和筛选的只读查询。',
        'run_comparison': '执行同口径、等长且不重叠的窗口比较。',
        'run_diagnosis': '执行有界诊断 Workflow；统计贡献不代表因果。',
        'run_multi_fact': '注册共同维度下先分别聚合不同事实，再按明确union/intersection关联；不是任意Join。',
        'propose_plans': '提出2到3个同目标、不同步骤的候选方案，校验后返回服务端plan_id；最多3轮重规划。',
        'select_plan': '选择当前候选计划；禁止偷偷切换目标或已选方案。',
        'run_plan_step': '仅执行所选计划的下一步；观察结果后可重新提出候选计划。',
        'resolve_semantics': '按需从当前注册中心解析多个指标、组件、共同维度与关系；只对明确请求的维度加载枚举。',
        'query_relations':'查询授权语义节点的依赖或影响范围；node_id如metric:average_order_value@1、field:commerce.fct_orders:booked_order_amount。路径可达不能授权Join。'}

    def __init__(self, tools):
        self.tools = tools
        self.executor = SkillExecutor(tools)
        self.planner = None
        self.retrieval = get_retrieval_service(tools)
        self.resolver = SemanticContextResolver(tools)

    def specifications(self):
        return [{'name': name, 'description': self.descriptions[name],
                 'parameters': model.model_json_schema()} for name, model in self.inputs.items()]

    def validate(self, name, arguments):
        if name not in self.inputs:
            raise ValueError('Unknown agent tool')
        return self.inputs[name].model_validate(arguments)

    def call(self, name, arguments):
        self.tools.check_execution()
        self.tools.access.role()
        data = self.validate(name, arguments)
        if name in ('propose_plans', 'select_plan', 'run_plan_step'):
            if self.planner is None:
                raise ValueError('Multi-plan manager is not initialized')
            return {'propose_plans': self.planner.propose, 'select_plan': self.planner.select,
                    'run_plan_step': self.planner.execute_step}[name](data)
        if name == 'search_business':
            return self.retrieval.retrieve(data.question, data.limit,data.partition)
        if name == 'query_relations':
            from .structure import GraphService
            return GraphService(self.tools).query(**data.model_dump())
        if name == 'resolve_semantics':
            return self.resolver.resolve(**data.model_dump())
        if name == 'describe_metric':
            return self.tools.describe(data.metric_id)
        if name == 'get_context':
            return {**self.tools.context(data.metric_id),
                    'semantic_context': self.resolver.resolve([data.metric_id])}
        if name == 'run_multi_fact':
            plan = self.tools.plan(data)
            return self.tools.execute(plan['plan_id'], plan['approval_hash'])
        if name == 'run_diagnosis' and data.kind != 'diagnose':
            raise ValueError('Diagnosis tool requires diagnose task')
        skill = {'run_query': 'metric-query', 'run_comparison': 'comparison',
                 'run_diagnosis': 'anomaly-analysis'}[name]
        return self.executor.run(skill, data.model_dump(mode='json'))['result']


# 兼容早期导入，确保历史演示无需同步迁移；新代码使用 AgentToolRouter。
AgentTools = AgentToolRouter
