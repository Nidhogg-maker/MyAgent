"""共享内容摘要：业务服务、语义上下文和运行账本使用同一序列化规则。

这是完整性校验工具，不负责身份认证，也不作为指标口径来源。
保持历史序列化规则，避免整理模块时使已有计划摘要发生无意义变化。
"""
import hashlib
import json


def fingerprint(value):
    """对稳定排序的 JSON 计算 SHA256；日期等对象沿用历史 str 转换。"""
    payload = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()
