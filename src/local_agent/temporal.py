"""时间边界与完整性证据；max(event_time)绝不能自动升级为完整性水位。"""
import datetime as dt
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .semantic import Query

class CoverageReceipt(BaseModel):
    """可信本地管道可提交绑定数据库hash的水位；模型和MCP调用者无写入入口。"""
    model_config = ConfigDict(extra='forbid')
    database_sha256: str
    complete_through: dt.datetime
    observed_at: dt.datetime
    attested_by: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode='after')
    def aware(self):
        if any(value.tzinfo is None for value in (self.complete_through, self.observed_at)):
            raise ValueError('Coverage timestamps require timezone')
        if self.complete_through > self.observed_at:
            raise ValueError('Coverage cannot extend beyond observation')
        return self

def coverage(database_hash, source_manifest: Path | None, receipt: Path | None = None):
    """默认仅记录快照观测时间；有真实管道收据才声明完整性。"""
    now = dt.datetime.now(dt.timezone.utc)
    if receipt:
        value = CoverageReceipt.model_validate_json(receipt.read_text(encoding='utf-8'))
        if value.database_sha256 != database_hash or value.observed_at > now:
            raise ValueError('Coverage receipt hash/time mismatch')
        return {'mode': 'local-pipeline-attestation', **value.model_dump(mode='json'), 'verified': True}
    source = json.loads(source_manifest.read_text(encoding='utf-8')) if source_manifest and source_manifest.exists() else {}
    observed = source.get('completed_at')
    return {'mode': 'snapshot-observation', 'observed_at': observed, 'complete_through': None,
            'verified': False, 'reason': 'No producer completeness attestation; source maximum timestamp is not a watermark'}

def check_window(query: Query, evidence: dict, now=None):
    """拒绝未结束日和超过快照观测的日期；历史空区间仍可返回零/空值。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if query.end > now.date():
        raise ValueError('CLARIFY: 今天尚未结束；当前只支持完整UTC日，不能与昨天全天直接比较')
    observed = evidence.get('observed_at')
    if observed and query.end > dt.datetime.fromisoformat(observed).astimezone(dt.timezone.utc).date():
        raise ValueError('Requested window exceeds source snapshot observation')
    complete = evidence.get('complete_through')
    if evidence.get('verified') and complete:
        boundary = dt.datetime.combine(query.end, dt.time(), tzinfo=dt.timezone.utc)
        if boundary > dt.datetime.fromisoformat(complete):
            raise ValueError('Requested window exceeds attested completeness watermark')

class DateResolver:
    """本地UTC日历解析；没有猜测业务时区或用模型计算今天/昨天。"""
    def __init__(self, now=None):
        self.now = now or dt.datetime.now(dt.timezone.utc)
        if self.now.tzinfo is None:
            raise ValueError('Reference clock must be timezone-aware')
        self.today = self.now.astimezone(dt.timezone.utc).date()

    def relative(self, term):
        if term in ('今天', '昨天', '前天'):
            offset = {'今天': 0, '昨天': 1, '前天': 2}[term]
            start = self.today - dt.timedelta(days=offset)
            return start, start + dt.timedelta(days=1)
        if term == '上个月':
            end = self.today.replace(day=1)
            start = (end - dt.timedelta(days=1)).replace(day=1)
            return start, end
        if term == '本月':
            raise ValueError('CLARIFY: 本月尚未结束；请指定已结束UTC日期范围')
        raise ValueError('CLARIFY: 请明确UTC日期范围')
