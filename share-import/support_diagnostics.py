"""Local, bounded support information: no chat text, filenames or credentials."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading

_lock=threading.Lock()

def diagnostic_root():
    from runtime_paths import DATA
    folder=DATA/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
    return folder

def record(event,**fields):
    allowed={'operation','error_type','winerror','hresult','callback','line','messages','busy','stage'}
    item={'utc':datetime.now(timezone.utc).isoformat(),'event':event}
    item.update({key:value for key,value in fields.items() if key in allowed and isinstance(value,(str,int,bool))})
    try:
        with _lock:
            path=diagnostic_root()/'ui-events.json'
            try:
                events=json.loads(path.read_text(encoding='utf-8')) if path.stat().st_size<65536 else []
                if not isinstance(events,list):events=[]
            except (OSError,ValueError):events=[]
            events.append(item)
            temporary=path.with_suffix('.writing')
            temporary.write_text(json.dumps(events[-32:],ensure_ascii=False),encoding='utf-8')
            temporary.replace(path)
    except OSError:pass

def record_error(operation,error):
    details={'operation':operation,'error_type':type(error).__name__}
    for key in ('winerror','hresult'):
        value=getattr(error,key,None)
        if isinstance(value,int):details[key]=value
    trace=error.__traceback__
    if trace:
        while trace.tb_next:trace=trace.tb_next
        details.update(callback=Path(trace.tb_frame.f_code.co_filename).name+':'+trace.tb_frame.f_code.co_name,
                       line=trace.tb_lineno)
    record('operation_error',**details)

def attach_callback_reporter(root):
    from tkinter import messagebox
    def report(error_type,error,trace):
        record_error('ui_callback',error)
        messagebox.showerror('操作未完成',
            '刚才的操作发生异常（'+error_type.__name__+'）。\n请在“使用方法”中点击“复制诊断信息”。',parent=root)
    root.report_callback_exception=report

def _read_fields(path,allowed):
    try:
        if path.stat().st_size>65536:return {'status':'report_too_large'}
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        return {key:data[key] for key in allowed if key in data and isinstance(data[key],(str,int,float,bool,type(None)))}
    except (OSError,ValueError,TypeError):return {'status':'not_recorded'}

def build_report():
    from runtime_paths import RESOURCES
    info=json.loads((RESOURCES/'build-info.json').read_text(encoding='utf-8-sig'))
    report={'app_version':info.get('version'),'revision':info.get('hotfix'),
            'windows_release':platform.release(),'process_architecture':platform.machine()}
    share_available=os.environ.get('RECORD_ARCHIVE_SHARE_AVAILABLE')
    if share_available in {'0','1'}:report['share_receiver_enabled']=share_available=='1'
    transfer_available=os.environ.get('RECORD_ARCHIVE_TRANSFER_TARGET_AVAILABLE')
    if transfer_available in {'0','1'}:report['transfer_target_api_present']=transfer_available=='1'
    failure=os.environ.get('RECORD_ARCHIVE_SHARE_SETUP_FAILURE')
    if failure:report['share_setup_failure']=failure
    folder=diagnostic_root()
    try:
        path=folder/'ui-events.json'
        events=json.loads(path.read_text(encoding='utf-8')) if path.stat().st_size<65536 else []
        # Reapply the whitelist instead of copying an arbitrary JSON file.
        keys={'utc','event','operation','error_type','winerror','hresult','callback','line','messages','busy','stage'}
        report['ui_events']=[{k:v for k,v in item.items() if k in keys and isinstance(v,(str,int,bool))}
                             for item in events[-16:] if isinstance(item,dict)]
    except (OSError,ValueError,TypeError):report['ui_events']=[]
    report['receiver']=_read_fields(folder/'receiver-state.json',
        {'utc','stage','error_type','hresult','share_activation','storage_items','bytes','accepted'})
    report['last_import']=_read_fields(folder/'last-shared-import.json',
        {'ok','messages','media_files','missing_media','attachments_received','rendered_page_status',
         'rendered_static_images','rendered_gif_images','rendered_animation_status'})
    powershell=Path(__import__('os').environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    script=RESOURCES/'share_diagnostics.ps1'
    quote=lambda value:"'"+str(value).replace("'","''")+"'"
    command="& ([ScriptBlock]::Create([IO.File]::ReadAllText("+quote(script)+"))) -AppRoot "+quote(RESOURCES.parent)
    try:
        result=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-Command',command],
                              capture_output=True,encoding='utf-8',errors='replace',timeout=20,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:report['system_probe']={'status':'failed','exit_code':result.returncode}
        else:report['system_probe']=json.loads(result.stdout.lstrip('\ufeff'))
    except (OSError,ValueError,subprocess.TimeoutExpired) as error:
        report['system_probe']={'status':'failed','error_type':type(error).__name__}
    return '记录归档诊断信息（不含聊天内容）\n'+json.dumps(report,ensure_ascii=False,indent=2)
