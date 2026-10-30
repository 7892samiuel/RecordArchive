"""Import only user-forwarded WeChat ZIPs, entirely offline."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import unicodedata
from urllib.parse import unquote
import uuid
import zipfile

LIMIT = 1024 ** 3
TEXT_LIMIT = 16 * 1024 ** 2
HEADER = re.compile(r'^·([^\n]+)\n(\d{4})年(\d{1,2})月(\d{1,2})日 (\d{2}):(\d{2})\n', re.M)
REFERENCE = re.compile(r'^\[(图片|动画表情|表情|视频|文件|语音)\][ \t]+([^\n]+)$')
KINDS = {'图片':'image','动画表情':'image','表情':'image','视频':'video','文件':'file','语音':'audio'}

def configure_storage():
    # AppData can be file-virtualized when launched by another packaged app.
    # A private, per-user profile directory has the same path for both clients.
    import os
    import runtime_paths
    import build_identity
    from build_identity import DATA_DIRECTORY
    if os.environ.get('RECORD_ARCHIVE_SHARE_AVAILABLE')=='0':
        build_identity.SHARE_ENABLED=False
    data=(Path(os.environ.get('USERPROFILE',str(Path.home())))/'.record-archive'/DATA_DIRECTORY).resolve()
    runtime_paths.DATA=data
    runtime_paths.SETTINGS=data/'settings.json'
    runtime_paths.MODELS=data/'models'
    runtime_paths.TemporaryChats.__init__.__defaults__=(data,)
    # The core is an internal component; registration still owns the ZIP root.
    import share_registration
    configuration=share_registration.configuration
    app_root=Path(__file__).resolve().parent.parent
    def root_configuration(app=None):
        return configuration(app_root if app is None else app)
    share_registration.configuration=root_configuration
    return data

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def pending_batch_id():
    from runtime_paths import DATA
    try:
        root=DATA/'incoming'
        if root.is_symlink() or not root.is_dir():return None
        batches=sorted((p for p in root.iterdir() if re.fullmatch('[a-f0-9]{32}',p.name)
                        and p.is_dir() and not p.is_symlink()),key=lambda p:p.stat().st_mtime)
        return batches[0].name if batches else None
    except OSError:return None

def startup_registration(application):
    import os
    from support_diagnostics import record
    root=Path(__file__).resolve().parent.parent
    initialized=os.environ.get('RECORD_ARCHIVE_INITIALIZED_ROOT','')
    # Registration belongs to the outer launcher; do not repeat it in the UI.
    registered=bool(initialized and Path(initialized).resolve()==root and
                    os.environ.get('RECORD_ARCHIVE_SHARE_AVAILABLE')=='1')
    record('ui_ready',stage='launcher_registration_complete' if registered else 'share_receiver_waiting')
    failure=os.environ.get('RECORD_ARCHIVE_SHARE_SETUP_FAILURE')
    if failure:record('share_setup_unavailable',error_type=failure)
    # Existing received batches remain usable after an initialization failure.
    if not getattr(application,'share_timer',None):
        application.share_timer=application.root.after(500,application.poll_share)
    if not application.data.get('messages'):
        application.status.set('分享入口暂未启用，请重新打开工具完成初始化后再转发。' if failure else
                               '在微信“其他应用”中转发给“记录归档”，收到后自动预览。')

def parse_messages(text):
    from datetime import datetime
    text = text.replace('\r\n', '\n').lstrip('\ufeff')
    headers = list(HEADER.finditer(text))
    if not headers or text[:headers[0].start()].strip() or len(headers) > 20000:
        raise ValueError('尚不支持这份微信分享的文字格式。')
    messages = []
    for index, header in enumerate(headers):
        end = headers[index+1].start() if index+1 < len(headers) else len(text)
        body = text[header.end():end].strip()
        kind = 'text'
        match = REFERENCE.fullmatch(body)
        if match: kind = KINDS[match[1]]
        elif body in {'[图片]','[动画表情]','[表情]'}: kind = 'image'
        elif re.fullmatch(r'\[语音\]\s*\d+["”秒]?', body): kind = 'audio'
        elif body == '[视频]': kind = 'video'
        elif body.startswith('[文件]'): kind = 'file'
        messages.append({'sender':header[1], 'time':datetime(*map(int,header.groups()[1:])).strftime('%Y-%m-%d %H:%M'),
                         'text':body, 'raw_text':body, 'kind':kind, 'children':[]})
    return messages

def index_entries(archive):
    entries={}; aliases={}; total=0
    infos=archive.infolist()
    if not 0 < len(infos) <= 20000: raise ValueError('分享包文件数量无效。')
    for item in infos:
        name=item.filename.rstrip('/'); parts=name.split('/')
        if not name or '\\' in name or ':' in name or any(p in {'','..','.'} for p in parts) or any(unicodedata.category(c)=='Cc' for c in name):
            raise ValueError('分享包包含无效路径。')
        mode=stat.S_IFMT(item.external_attr >> 16)
        if mode not in {0, stat.S_IFDIR if item.is_dir() else stat.S_IFREG}: raise ValueError('分享包不能包含链接。')
        for i in range(1,len(parts)+1):
            prefix='/'.join(parts[:i]); key=unicodedata.normalize('NFC',prefix).casefold()
            if key in aliases and aliases[key]!=prefix: raise ValueError('分享包附件路径冲突。')
            aliases[key]=prefix
        if item.flag_bits & 1 or item.compress_type not in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED}: raise ValueError('不支持加密分享包。')
        total+=item.file_size
        if total>LIMIT: raise ValueError('分享包展开大小超过 1 GB。')
        if not item.is_dir():
            if name in entries: raise ValueError('分享包含重复附件路径。')
            entries[name]=item
    return entries

def resolve_reference(text, entries):
    match=REFERENCE.fullmatch(text.strip())
    if not match: return None
    value=match[2].strip().removeprefix('./')
    for candidate in dict.fromkeys((value,unquote(value))):
        if candidate in entries: return candidate
        if '/' not in candidate and '\\' not in candidate:
            choices=[name for name in entries if PurePosixPath(name).name==candidate]
            if len(choices)==1: return choices[0]
            if len(choices)>1: return None
    return None

def parse_archive(source, destination):
    source=Path(source); destination=Path(destination)
    if source.stat().st_size>LIMIT: raise ValueError('分享包超过 1 GB。')
    destination.mkdir(parents=True,exist_ok=False)
    original=destination/'original.zip';shutil.copyfile(source,original)
    with zipfile.ZipFile(original) as archive:
        entries=index_entries(archive)
        transcripts=[name for name in entries if PurePosixPath(name).name=='聊天记录.txt']
        if len(transcripts)!=1: raise ValueError('微信分享包中未找到唯一的聊天记录正文。')
        transcript=transcripts[0]
        if entries[transcript].file_size>TEXT_LIMIT: raise ValueError('聊天正文超过 16 MB。')
        messages=parse_messages(archive.read(entries[transcript]).decode('utf-8-sig'))
        paths={}
        for index,(name,entry) in enumerate(entries.items()):
            if name==transcript: continue
            suffix=PurePosixPath(name).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,10}',suffix): suffix='.bin'
            target=destination/('attachment-%05d%s'%(index,suffix))
            with archive.open(entry) as incoming, target.open('xb') as outgoing:
                copied=0
                while chunk:=incoming.read(128*1024):
                    copied+=len(chunk)
                    if copied>entry.file_size: raise ValueError('分享附件大小无效。')
                    outgoing.write(chunk)
                if copied!=entry.file_size: raise ValueError('分享附件不完整。')
            paths[name]=target
        used=set()
        for message in messages:
            name=resolve_reference(message['text'],entries)
            if name not in paths: continue
            target=paths[name]
            if message['kind']=='image':
                from PIL import Image
                with Image.open(target) as image:
                    for frame in range(getattr(image,'n_frames',1)):
                        image.seek(frame);image.load()
            message.update(path=str(target),text='',media_quality='shared_original')
            used.add(name)
    missing=sum(m['kind']!='text' and not m.get('path') for m in messages)
    unused=len(paths.keys()-used)
    warnings=[]
    if missing and not paths: warnings.append('微信分享包只有聊天文字，未包含媒体原文件。')
    elif missing: warnings.append('有 %d 条媒体尚未与分享包内的原文件关联。'%missing)
    if unused: warnings.append('%d 个附件未能与消息明确关联，原件保留在本次归档中。'%unused)
    return {'title':'聊天记录','messages':messages,'source':'微信原生分享', 'archive_original':str(original),
            'media_root':str(destination),'capture_warnings':warnings,
            'capture_info':{'method':'Windows user-shared ZIP','scope':'shared_archive','missing_media':missing,'unassociated_files':unused,
                            'attachment_entry_count':len(paths),
                            'attachment_extensions':sorted(PurePosixPath(name).suffix.lower() for name in paths),
                            'message_kinds':[m['kind'] for m in messages]}}

def read_pending():
    from support_diagnostics import record
    from runtime_paths import DATA, temporary_chats
    root=DATA/'incoming'
    if not root.is_dir(): return None
    if root.is_symlink(): raise ValueError('分享接收目录被重定向。')
    batches=sorted((p for p in root.iterdir() if re.fullmatch('[a-f0-9]{32}',p.name) and p.is_dir() and not p.is_symlink()),key=lambda p:p.stat().st_mtime)
    if not batches: return None
    batch=batches[0]
    record('import_started',stage='validate_shared_zip')
    metadata=batch/'batch.json';source=batch/'original.zip'
    if metadata.is_symlink() or source.is_symlink() or metadata.stat().st_size>65536: raise ValueError('分享批次无效。')
    state=json.loads(metadata.read_text(encoding='utf-8-sig'))
    if state.get('schema')!=1 or state.get('id')!=batch.name or source.stat().st_size!=state.get('bytes') or digest(source)!=state.get('sha256'):
        raise ValueError('分享包校验失败，未读取内容。')
    result=parse_archive(source,temporary_chats()/('shared-'+uuid.uuid4().hex))
    record('import_parsed',messages=len(result['messages']))
    helper=Path(__file__).parent/'RecordOcrHelper.exe'
    if helper.is_file() and any(m['kind']=='image' and not m.get('path') for m in result['messages']):
        import importlib.util
        module_path=Path(__file__).with_name('rendered_media.py')
        spec=importlib.util.spec_from_file_location('record_rendered_media',module_path)
        renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
        renderer.supplement(result,helper)
    from exporter import normalize
    media_root=result['media_root']
    result=normalize(result)
    result['media_root']=media_root
    try:
        diagnostic=DATA/'diagnostics';diagnostic.mkdir(exist_ok=True)
        (diagnostic/'last-shared-import.json').write_text(json.dumps({
            'ok':True,'batch_id':batch.name,'messages':len(result['messages']),
            'media_files':sum(bool(m.get('path')) for m in result['messages']),
            'missing_media':result.get('capture_info',{}).get('missing_media'),
            'attachments_received':result.get('capture_info',{}).get('attachment_entry_count'),
            'unassociated_files':result.get('capture_info',{}).get('unassociated_files'),
            'attachment_extensions':result.get('capture_info',{}).get('attachment_extensions'),
            'message_kinds':result.get('capture_info',{}).get('message_kinds'),
            'original_archive_path':result.get('archive_original'),
            'rendered_page_status':result.get('capture_info',{}).get('rendered_page_status'),
            'rendered_static_images':result.get('capture_info',{}).get('rendered_static_images',0),
            'rendered_gif_images':result.get('capture_info',{}).get('rendered_gif_images',0),
            'rendered_animation_status':result.get('capture_info',{}).get('rendered_animation_status'),
            'rendered_capture_frames':result.get('capture_info',{}).get('rendered_capture_frames',0),
            'rendered_capture_seconds':result.get('capture_info',{}).get('rendered_capture_seconds',0),
            'source':'user-shared ZIP','accessibility_required':False
        }),encoding='utf-8')
    except OSError: pass
    # The application's temporary-chat cleanup now owns the copied content.
    source.unlink();metadata.unlink()
    if not any(batch.iterdir()): batch.rmdir()
    record('import_completed',messages=len(result['messages']))
    return result

def install():
    import ui_theme
    from support_diagnostics import attach_callback_reporter
    configure=ui_theme.configure
    def configured(root):
        result=configure(root)
        attach_callback_reporter(root)
        return result
    ui_theme.configure=configured

def self_test(report,source,render=False):
    import sys
    from runtime_paths import temporary_chats, cleanup_temporary
    from exporter import normalize, export_archive
    folder=temporary_chats()/('native-test-'+uuid.uuid4().hex)
    raw=parse_archive(source,folder)
    if render:
        import importlib.util
        spec=importlib.util.spec_from_file_location('record_rendered_media_test',Path(__file__).with_name('rendered_media.py'))
        renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
        renderer.supplement(raw,Path(__file__).with_name('RecordOcrHelper.exe'))
    original_gifs=[digest(m['path']) for m in raw['messages'] if m.get('path') and Path(m['path']).suffix.lower()=='.gif']
    data=normalize(raw)
    data['media_root']=raw['media_root']
    output=folder/'export'
    export_archive(data,output,media_root=data['media_root'])
    from PIL import Image
    asset_images=[];asset_digests=[]
    for asset in (output/'assets').iterdir():
        if not asset.is_file():continue
        asset_digests.append(digest(asset))
        try:
            with Image.open(asset) as image:
                asset_images.append({'extension':asset.suffix.lower(),'format':image.format,
                                     'frames':getattr(image,'n_frames',1)})
        except OSError:pass
    result={'ok':True,'messages':len(data['messages']),'media_files':sum(bool(m.get('path')) for m in data['messages']),
            'missing_media':data.get('capture_info',{}).get('missing_media'),
            'attachments_received':data.get('capture_info',{}).get('attachment_entry_count'),
            'unassociated_files':data.get('capture_info',{}).get('unassociated_files'), 'output_files':sorted(p.name for p in output.iterdir()),
            'database_used':False,'accessibility_required':False,'asset_images':asset_images,
            'gif_bytes_preserved':all(value in asset_digests for value in original_gifs) if original_gifs else None,
            'rendered_gif_images':raw.get('capture_info',{}).get('rendered_gif_images',0),
            'rendered_page_status':raw.get('capture_info',{}).get('rendered_page_status'),
            'rendered_animation_status':raw.get('capture_info',{}).get('rendered_animation_status'),
            'verification_revision':json.loads(Path(__file__).with_name('build-info.json').read_text(encoding='utf-8-sig')).get('hotfix'),
            'core_sha256':digest(sys.executable),'backend_sha256':digest(__file__),
            'renderer_sha256':digest(Path(__file__).with_name('rendered_media.py'))}
    Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    cleanup_temporary()

def shutdown_self_test(report):
    import tkinter as tk
    from app import App
    from runtime_paths import DATA, temporary_chats
    temporary=temporary_chats()
    canonical_parent_matches=temporary.resolve().parent==temporary.parent.resolve()
    root=tk.Tk();root.withdraw()
    application=App(root)
    application.close()
    try: destroyed=not bool(root.winfo_exists())
    except tk.TclError: destroyed=True
    result={'ok':destroyed and not temporary.exists() and canonical_parent_matches,
            'window_destroyed':destroyed,'temporary_data_removed':not temporary.exists(),
            'canonical_parent_matches':canonical_parent_matches,'data_directory':str(DATA)}
    Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if not result['ok']:raise ValueError('Close self-test failed')

def interaction_self_test(report):
    """Exercise the real forwarding-only UI without reading a WeChat window."""
    import tkinter as tk
    from tkinter import messagebox
    from types import SimpleNamespace
    from app import App
    from runtime_paths import cleanup_temporary
    root=tk.Tk();root.withdraw()
    app=App(root,activation=SimpleNamespace(take=lambda:False,close=lambda:None))
    if app.share_timer:root.after_cancel(app.share_timer);app.share_timer=None
    showerror=messagebox.showerror;dialogs=[]
    shared_reader=read_pending;shared_batch=pending_batch_id
    result={'ok':False,'page_entry_removed':not hasattr(app,'read_page') and str(app.import_btn['text'])=='重新接收'}
    messagebox.showerror=lambda *args,**kwargs:dialogs.append(args)
    def payload(title):return {'title':title,'messages':[
        {'kind':'text','sender':'测试','time':'','text':'分享接收回调测试','children':[]}]}
    def widgets(parent):
        for widget in parent.winfo_children():yield widget;yield from widgets(widget)
    def fail(message):result['error']=message;root.destroy()
    def finished_error():
        if app.busy:root.after(20,finished_error);return
        result['receive_error_dialog_visible']=bool(dialogs) and '测试接收失败' in app.status.get()
        result['controls_reenabled']=str(app.import_btn['state'])=='normal'
        app.show_help()
        helps=[widget for widget in widgets(root) if isinstance(widget,tk.Toplevel)]
        for dialog in helps:dialog.withdraw()
        result['copy_diagnostics_action_present']=any(
            str(widget.cget('text'))=='复制诊断信息' for dialog in helps for widget in widgets(dialog)
            if 'text' in widget.keys())
        for dialog in helps:dialog.destroy()
        result['ok']=all(result.get(key) for key in ('page_entry_removed','retry_received_share',
            'automatic_share_received','receive_error_dialog_visible','controls_reenabled','copy_diagnostics_action_present'))
        app.close()
    def finished_share():
        if app.busy:root.after(20,finished_share);return
        result['automatic_share_received']=app.data['title']=='自动分享测试'
        if app.share_timer:root.after_cancel(app.share_timer);app.share_timer=None
        if not result['automatic_share_received']:fail('Automatic share was not received');return
        def unreadable():raise ValueError('测试接收失败')
        globals()['read_pending']=unreadable
        app.import_btn.invoke();root.after(20,finished_error)
    def finished_retry():
        if app.busy:root.after(20,finished_retry);return
        result['retry_received_share']=app.data['title']=='分享接收测试'
        if not result['retry_received_share']:fail('Retry did not receive the share');return
        globals()['read_pending']=lambda:payload('自动分享测试')
        app.poll_share();root.after(20,finished_share)
    try:
        globals()['pending_batch_id']=lambda:'f'*32
        globals()['read_pending']=lambda:payload('分享接收测试')
        root.after(0,app.import_btn.invoke);root.after(20,finished_retry)
        root.after(7000,lambda:fail('Interaction verification timed out'))
        root.mainloop()
    finally:
        messagebox.showerror=showerror
        globals()['read_pending']=shared_reader;globals()['pending_batch_id']=shared_batch
        cleanup_temporary()
    Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if not result['ok']:raise ValueError('Forwarding-only interaction self-test failed')
