"""本地能力令牌与服务侧权限；不是企业SSO，也不接受模型自报身份。"""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from .semantic import ROOT, Query, file_hash

class AccessDenied(ValueError):
    """权限失败必须停止，不能通过换口径或删过滤静默重试。"""

def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')

class AccessController:
    """本地stdio/CLI信任OS用户；可用签名令牌绑定受限主体，每次工具调用重验。"""
    def __init__(self, home: Path, token=None, policy_path=ROOT / 'config/access-policy.json'):
        self.home, self.token, self.policy_path = Path(home), token, Path(policy_path)
        self.policy = json.loads(self.policy_path.read_text(encoding='utf-8'))
        self.policy_hash = file_hash(self.policy_path)
        self.key_path = self.home / 'signing.key'
        if not self.key_path.exists():
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as file:
                    file.write(os.urandom(32))
            except FileExistsError:
                pass
        self.key = self.key_path.read_bytes()
        if len(self.key)!=32:
            raise AccessDenied('Local signing key invalid')
        self.revocations = self.home / 'identity.sqlite'
        with sqlite3.connect(self.revocations) as db:
            db.execute('CREATE TABLE IF NOT EXISTS revoked (jti TEXT PRIMARY KEY)')
        self.subject = self._verify()['sub'] if token else 'local-study-user'

    def issue(self, subject, lifetime=3600):
        """仅可信本地主机管理入口签发；此方法不作为MCP工具暴露。"""
        if not self.role()['publish'] or subject not in self.policy['subjects'] or not 1 <= lifetime <= 3600:
            raise AccessDenied('Token issuance denied')
        payload = {'iss': self.policy['issuer'], 'sub': subject, 'exp': int(time.time()) + lifetime, 'jti': uuid.uuid4().hex}
        body = _encode(json.dumps(payload, sort_keys=True).encode())
        return body + '.' + _encode(hmac.new(self.key, body.encode(), hashlib.sha256).digest())

    def _verify(self):
        """常量时间验签、有效期、issuer和撤销检查；role只从受信策略映射。"""
        try:
            if len(self.token) > 4096:
                raise ValueError()
            body, signature = self.token.split('.')
            expected = _encode(hmac.new(self.key, body.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
            if set(payload) != {'iss', 'sub', 'exp', 'jti'} or type(payload['exp']) is not int:
                raise ValueError()
            if payload['iss'] != self.policy['issuer'] or payload['exp'] <= time.time() or payload['sub'] not in self.policy['subjects']:
                raise ValueError()
            with sqlite3.connect(self.revocations) as db:
                if db.execute('SELECT 1 FROM revoked WHERE jti=?', (payload['jti'],)).fetchone():
                    raise ValueError()
            return payload
        except Exception:
            raise AccessDenied('Invalid, expired or revoked local credential') from None

    def revoke(self, token):
        """管理员撤销令牌；不能由模型选择或生成subject。"""
        if not self.role()['publish']:
            raise AccessDenied('Revocation denied')
        previous = self.token
        try:
            self.token = token
            payload = self._verify()
        finally:
            self.token = previous
        with sqlite3.connect(self.revocations) as db:
            db.execute('INSERT OR IGNORE INTO revoked VALUES (?)', (payload['jti'],))

    def role(self):
        """热变更策略后停止旧会话；令牌过期在执行时也会生效。"""
        if file_hash(self.policy_path) != self.policy_hash:
            raise AccessDenied('Policy changed; restart trusted session')
        subject = self._verify()['sub'] if self.token else self.subject
        if subject!=self.subject:
            raise AccessDenied('Session identity cannot change')
        return self.policy['roles'][self.policy['subjects'][subject]]

    def metric(self, metric_id):
        role = self.role()
        if '*' not in role['metrics'] and metric_id not in role['metrics']:
            raise AccessDenied('Metric access denied')
        return role

    def enforce(self, query: Query):
        """服务器强制行过滤与列维度权限；模型不能移除US限制或查询敏感分组。"""
        role = self.metric(query.metric_id)
        if '*' not in role['dimensions'] and not (set(query.group_by) | set(query.filters)) <= set(role['dimensions']):
            raise AccessDenied('Dimension/column access denied')
        filters = dict(query.filters)
        for field, value in role['row_filters'].items():
            if field in filters and filters[field] != value:
                raise AccessDenied('Requested rows outside authorized scope')
            filters[field] = value
        return Query.model_validate({**query.model_dump(mode='json'), 'filters': filters}), role

    def redact_metadata(self, context):
        """非管理员元数据隐藏敏感字段；数据工具从未暴露原始身份明细。"""
        if '*' in self.role()['dimensions']:
            return context
        sensitive = self.policy['sensitive_fields']
        result = {**context, 'schema':[f for f in context['schema'] if f['name'] not in sensitive], 'metadata_redacted':True}
        if 'field_lineage' in result:
            result['field_lineage'] = {**result['field_lineage'], **{key:[name for name in result['field_lineage'].get(key,[]) if name not in sensitive] for key in ('resolved_fields','unresolved_fields')}}
        if 'control_lineage' in result:
            result['control_lineage'] = {**result['control_lineage'], 'edges':[edge for edge in result['control_lineage']['edges'] if edge['column'] not in sensitive],
                                         'unresolved':[], 'metadata_redacted':True}
        if 'quality' in result:
            checks=result['quality'].get('checks',[])
            result['quality']={**result['quality'],'checks':[check for check in checks if not any(field in check for field in sensitive)],
                               'checks_total':len(checks),'references_redacted':True}
        return result
