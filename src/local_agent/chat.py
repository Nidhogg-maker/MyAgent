"""统一终端入口：显示简洁结果，完整状态和证据保存在会话库。"""
import json

def display(result):
    print('\n会话：'+result['session_id'])
    print('状态：'+result.get('status','UNKNOWN'))
    if result.get('error'): print(result['error'])
    answer=result.get('answer',{})
    if answer.get('markdown'):
        print(answer['markdown'])
        print('完整事件与结果：/show')
        return
    print(answer.get('summary',''))
    evidence=answer.get('evidence',{})
    if 'rows' in evidence:
        print('结果：'+json.dumps(evidence['rows'],ensure_ascii=False))
        print('口径：'+evidence.get('definition',''))
        for warning in evidence.get('warnings',[]): print('限制：'+warning)
    if 'change' in evidence: print('窗口比较：'+json.dumps(evidence['change'],ensure_ascii=False))
    for decomposition in evidence.get('decompositions',[]):
        print('拆解：'+json.dumps(decomposition,ensure_ascii=False,default=str))
    if 'quality_check' in evidence:
        print('质量：'+json.dumps(evidence['quality_check'],ensure_ascii=False))
    for missing in evidence.get('unresolved',[]): print('证据缺口：'+missing)
    if evidence.get('stopped_reason'): print('停止原因：'+evidence['stopped_reason'])
    print('完整证据：使用 /show 查看当前会话')

def chat_loop(runtime,session=None):
    print('MyAgent：输入问题，/new 新问题，/show 查看证据，/health 熔断状态，/resume 恢复，/cancel 取消，/exit 退出。')
    if session:
        runtime.authorize(session)
        display({'session_id':session,**runtime.store.get(session)['state']})
    while True:
        try: text=input('\n你> ').strip()
        except (EOFError,KeyboardInterrupt):
            print('\n已退出；会话和查询回执已保留。')
            return 0
        if not text: continue
        if text=='/exit': return 0
        if text=='/new': session=None; continue
        if text=='/health':
            from .resilience import CircuitBreaker
            print(json.dumps(CircuitBreaker(runtime.tools.home/'resilience.sqlite').snapshot(),ensure_ascii=False,indent=2))
            continue
        try:
            if text in ('/show','/resume','/cancel'):
                if not session: print('尚无会话'); continue
                if text=='/show': print(json.dumps(runtime.show(session),ensure_ascii=False,indent=2,default=str)); continue
                result=runtime.resume(session) if text=='/resume' else runtime.cancel(session)
            elif session and runtime.store.get(session)['status']=='CLARIFY':
                result=runtime.followup(session,text)
            else: result=runtime.start({'question':text,**({'context_session':session} if session else {})})
            session=result['session_id']
            display(result)
        except Exception as error: print('停止：'+str(error))
