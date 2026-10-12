"""轻量目录式Skill资源：按实际引用加载，不增加企业配置目录。"""
import hashlib
import re
from .semantic import ROOT

PACKAGES={'metric-query':'warehouse-metric-query','comparison':'warehouse-window-comparison',
          'drilldown':'warehouse-dimension-drilldown','quality-check':'warehouse-quality-check',
          'anomaly-analysis':'warehouse-anomaly-attribution','evidence-report':'warehouse-evidence-report',
          'profile-query':'warehouse-profile-query'}

def entry(identifier):
    return ROOT/'skills'/PACKAGES[identifier]/'SKILL.md'

def resources(identifier,references=False):
    path=entry(identifier)
    text=path.read_text(encoding='utf-8')
    result={'entry':path.relative_to(ROOT).as_posix(),'instructions':text,'references':{}}
    if references:
        for relative in re.findall(r'\]\(([^)]+\.md)\)',text):
            resolved=(path.parent/relative).resolve()
            if not resolved.is_relative_to((ROOT/'skills').resolve()): raise ValueError('Skill resource path escapes project')
            if 'references' in resolved.parts:
                result['references'][resolved.relative_to(ROOT).as_posix()]=resolved.read_text(encoding='utf-8')
    result['sha256']=hashlib.sha256(str(result).encode()).hexdigest()
    return result

def report_template():
    return (ROOT/'skills/warehouse-anomaly-attribution/assets/report-template.md').read_text(encoding='utf-8')
