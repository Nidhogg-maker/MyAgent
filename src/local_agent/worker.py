"""工具服务内部的独立执行进程；不对 Agent 暴露自由 SQL 接口。"""
import json
import sys
import duckdb

def main():
    """只读、禁外部访问、限定资源；仅通过 JSON 管道返回结果。"""
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        request = json.load(sys.stdin)
        with duckdb.connect(request['database'], read_only=True,
                config={'enable_external_access': 'false', 'threads': 1, 'memory_limit': '256MB'}) as db:
            cursor = db.execute(request['sql'], request.get('parameters', []))
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchmany(1001)
            if len(rows) > 1000:
                raise ValueError('Result budget exceeded')
            result = {'columns': columns, 'rows': rows}
    except Exception as error:
        result = {'error': type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, default=str))

if __name__ == '__main__':
    main()
