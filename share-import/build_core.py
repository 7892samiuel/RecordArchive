"""Build a reviewable bootstrap around the retained frozen application.

This hotfix still depends on the existing binary runtime. It is not a complete
source build and must not be submitted as one to an open-source signing service.
"""
import hashlib
import marshal
from pathlib import Path
import struct
import sys
import types
import zlib

source=Path(sys.argv[1]);output=Path(sys.argv[2])
data=source.read_bytes()
assert hashlib.sha256(data).hexdigest()=='f5624f8bbd29c1ddfb5af54ce5708555be7e6eb81453e2eb59569245001b2819','Expected the retained pre-hotfix core baseline'
cookie_at=data.rfind(b'MEI\x0c\x0b\x0a\x0b\x0e')
magic,size,toc_offset,toc_size,version,library=struct.unpack('!8sIIII64s',data[cookie_at:cookie_at+88])
assert magic==b'MEI\x0c\x0b\x0a\x0b\x0e' and version==312
base=cookie_at+88-size;toc=data[base+toc_offset:base+toc_offset+toc_size]
entries=[];offset=0
while offset<len(toc):
    length,pos,compressed,raw_size,flag,kind=struct.unpack('!IIIIBc',toc[offset:offset+18])
    name=toc[offset+18:offset+length].rstrip(b'\0')
    chunk=data[base+pos:base+pos+compressed]
    entries.append([name,chunk,raw_size,flag,kind])
    offset+=length
# The executable now lives beside its dependencies inside _internal.
contents=next(value for value in entries if value[0]==b'pyi-contents-directory _internal')
contents[0]=b'pyi-contents-directory .'
# Replace the reviewed lifecycle/feedback callbacks, preserving other modules.
shutdown_module=compile(Path(__file__).with_name('app_shutdown.py').read_text(encoding='utf-8'),'app_shutdown.py','exec')
shutdown=next(value for value in shutdown_module.co_consts if isinstance(value,types.CodeType) and value.co_name=='close')
feedback_module=compile(Path(__file__).with_name('ui_feedback.py').read_text(encoding='utf-8'),'ui_feedback.py','exec')
callbacks={('App.read_page' if value.co_name=='receive_share' else 'App.'+value.co_name):value for value in feedback_module.co_consts
           if isinstance(value,types.CodeType) and value.co_name!='register_share'}
callbacks['register_share']=next(value for value in feedback_module.co_consts if isinstance(value,types.CodeType) and value.co_name=='register_share')
callbacks['App.close']=shutdown
replacements={name:0 for name in callbacks}
instructions={
    '读取微信记录':'重新接收',
    '打开微信合并记录，预览并导出 PDF':'接收微信合并转发，预览并导出 PDF',
    '请先打开微信合并记录，再点击“读取微信记录”。':'请从微信「其他应用」转发给「记录归档」。',
    '在微信打开合并聊天记录详情页\n点击上方「读取微信记录」':'微信合并转发 → 其他应用 → 记录归档\n收到后自动显示预览',
    '在微信打开合并聊天记录详情页\n点击上方“读取微信记录”':'微信合并转发 → 其他应用 → 记录归档\n收到后自动显示预览',
}
def patch_app(code):
    if code.co_qualname in callbacks:
        replacements[code.co_qualname]+=1
        replacement=callbacks[code.co_qualname]
        return replacement.replace(co_qualname='App.receive_share' if code.co_qualname=='App.read_page' else code.co_qualname)
    return code.replace(co_consts=tuple(patch_app(value) if isinstance(value,types.CodeType)
                      else instructions.get(value,value) if isinstance(value,str) else value for value in code.co_consts),
                      co_names=tuple('receive_share' if name=='read_page' else name for name in code.co_names))
pyz_entry=next(value for value in entries if value[0].endswith(b'.pyz'))
pyz=zlib.decompress(pyz_entry[1]) if pyz_entry[3] else pyz_entry[1]
assert pyz[:4]==b'PYZ\0'
old_toc=marshal.loads(pyz[struct.unpack('!i',pyz[8:12])[0]:])
items=list(old_toc.items()) if isinstance(old_toc,dict) else list(old_toc)
new_pyz=bytearray(pyz[:12]);pyz_toc=[]
for name,(kind,position,length) in items:
    chunk=pyz[position:position+length]
    if name in {'app','media_preview'}:chunk=zlib.compress(marshal.dumps(patch_app(marshal.loads(zlib.decompress(chunk)))),9)
    pyz_toc.append((name,(kind,len(new_pyz),len(chunk))));new_pyz.extend(chunk)
assert all(count==1 for count in replacements.values()),replacements
struct.pack_into('!i',new_pyz,8,len(new_pyz))
new_pyz.extend(marshal.dumps(dict(pyz_toc) if isinstance(old_toc,dict) else pyz_toc))
pyz_entry[1]=zlib.compress(bytes(new_pyz),9) if pyz_entry[3] else bytes(new_pyz)
pyz_entry[2]=len(new_pyz)
entry=next(v for v in entries if v[0]==b'package_entry')
original=zlib.decompress(entry[1]) if entry[3] else entry[1]
bootstrap='''import importlib.util, marshal, pathlib, sys
sys.dont_write_bytecode=True
_path=pathlib.Path(sys._MEIPASS)/"shared_record_backend.py"
sys.path.insert(0,str(_path.parent))
_spec=importlib.util.spec_from_file_location("shared_record_backend",_path)
_backend=importlib.util.module_from_spec(_spec)
sys.modules[_spec.name]=_backend
_spec.loader.exec_module(_backend)
_backend.configure_storage()
if len(sys.argv)==3 and sys.argv[1]=="--interaction-self-test":
    _backend.install()
    _backend.interaction_self_test(sys.argv[2])
    raise SystemExit(0)
if len(sys.argv)==3 and sys.argv[1]=="--support-report":
    from support_diagnostics import build_report
    pathlib.Path(sys.argv[2]).write_text(build_report(),encoding="utf-8")
    raise SystemExit(0)
if len(sys.argv)==3 and sys.argv[1]=="--shutdown-self-test":
    import json,traceback
    try:
        _backend.shutdown_self_test(sys.argv[2])
    except Exception as error:
        pathlib.Path(sys.argv[2]).write_text(json.dumps({"ok":False,"error":str(error),"traceback":traceback.format_exc()},ensure_ascii=False),encoding="utf-8")
        raise SystemExit(1)
    raise SystemExit(0)
if len(sys.argv)==4 and sys.argv[1] in {"--native-self-test","--native-page-self-test"}:
    import json,traceback
    try:
        _backend.self_test(sys.argv[2],sys.argv[3],render=sys.argv[1]=="--native-page-self-test")
    except Exception as error:
        pathlib.Path(sys.argv[2]).write_text(json.dumps({"ok":False,"error":str(error),"traceback":traceback.format_exc()},ensure_ascii=False),encoding="utf-8")
        raise SystemExit(1)
    raise SystemExit(0)
if len(sys.argv)==1:
    _backend.install()
exec(marshal.loads(ORIGINAL_ENTRY),globals())
'''.replace('ORIGINAL_ENTRY',repr(original))
new_code=compile(bootstrap,'package_entry.py','exec')
raw=marshal.dumps(new_code)
entry[1]=zlib.compress(raw,9);entry[2]=len(raw);entry[3]=1
payload=bytearray();new_toc=bytearray()
for name,chunk,raw_size,flag,kind in entries:
    pos=len(payload);payload.extend(chunk)
    length=(18+len(name)+1+15)&~15
    new_toc.extend(struct.pack('!IIIIBc',length,pos,len(chunk),raw_size,flag,kind))
    new_toc.extend(name+b'\0'*(length-18-len(name)))
new_cookie=struct.pack('!8sIIII64s',magic,len(payload)+len(new_toc)+88,len(payload),len(new_toc),version,library)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_bytes(data[:base]+payload+new_toc+new_cookie)
(output.parent/'core-baseline.sha256').write_text(hashlib.sha256(data).hexdigest(),encoding='ascii')
print(output)
