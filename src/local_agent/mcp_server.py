"""本地 stdio MCP 适配只暴露受控工具，业务逻辑全部在自己的 AgentTools。"""
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .semantic import ROOT, Query
from .service import QueryService

server = FastMCP('own-commerce-agent')
tools = QueryService(Path(os.getenv('OWN_AGENT_HOME', str(ROOT / 'data/own-agent'))),token=os.getenv('OWN_AGENT_TOKEN'))

@server.tool()
def describe_metric(metric_id: str) -> dict:
    """返回版本化口径和合法维度，禁止猜测销售额定义。"""
    return tools.describe(metric_id)

@server.tool()
def get_context(metric_id: str) -> dict:
    """读取本地实体/字段/Owner/质量/血缘证据。"""
    tools.release()
    return tools.context(metric_id)

@server.tool()
def get_lineage(table: str, column: str | None = None) -> dict:
    """遍历本地关系表，字段解析范围与截断会明确返回。"""
    tools.release()
    return tools.lineage(table,column)

@server.tool()
def plan_query(query: dict) -> dict:
    """结构化查询→自建编译器→服务端计划，调用方没有自由SQL入口。"""
    return tools.plan(Query.model_validate(query))

@server.tool()
def execute_query(plan_id: str, approval_hash: str) -> dict:
    """只能执行本会话生成并通过校验的计划。"""
    return tools.execute(plan_id, approval_hash)

@server.tool()
def compare_windows(baseline: dict, current: dict) -> dict:
    """比较同口径等时长窗口；证据不足时失败，不编造原因。"""
    return tools.compare(Query.model_validate(baseline), Query.model_validate(current))

@server.tool()
def search_business(question: str) -> dict:
    """授权后检索业务词/指标/案例，返回可核验引用，不返回原始用户明细。"""
    from .retrieval_service import get_retrieval_service
    tools.access.role()
    return get_retrieval_service(tools).retrieve(question)

@server.tool()
def run_diagnosis(task: dict) -> dict:
    """运行有界异常诊断Skill；不支持的假设和因果证据缺口会明确返回。"""
    from .tasks import Task
    from .diagnosis import DiagnosisEngine
    return DiagnosisEngine(tools).run(Task.model_validate(task))

def _feature(data):
    from .feature_agent import FeatureRequest, FeatureTools
    return FeatureTools(tools).read_profile(FeatureRequest.model_validate(data))

@server.tool()
def get_user_profile(user_id: int, as_of: str) -> dict:
    """按明确UTC截止日期读取用户画像和质量血缘。"""
    return _feature({'data_product':'user_profile','user_id':user_id,'as_of':as_of})

@server.tool()
def get_product_profile(product_id: int, as_of: str) -> dict:
    """按指定日期成功发布版本读取商品画像。"""
    return _feature({'data_product':'product_profile','product_id':product_id,'as_of':as_of})

@server.tool()
def get_user_product_features(user_id: int, product_id: int, as_of: str) -> dict:
    """只读取已有交互对，不把不存在记录伪装成负例。"""
    return _feature({'data_product':'user_product','user_id':user_id,'product_id':product_id,'as_of':as_of})

@server.tool()
def get_session_profile(session_id: str, as_of: str) -> dict:
    """读取会话观察结果，不推断支付、订单归属或负标签。"""
    return _feature({'data_product':'session','session_id':session_id,'as_of':as_of})

@server.tool()
def describe_data_product(data_product: str, as_of: str) -> dict:
    """返回指定发布的数据产品契约、粒度和技术血缘。"""
    return _feature({'kind':'describe','data_product':data_product,'as_of':as_of})

def main():
    server.run(transport='stdio')

if __name__ == '__main__':
    main()
