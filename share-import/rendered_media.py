"""Save rendered images/animations after matching the whole visible record.

Uses Windows Graphics Capture and Windows offline OCR. No database, cache,
process-memory changes, Narrator, downloads, or guesses by nearby filenames.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess

from PIL import Image, ImageChops

DATE=re.compile(r'(20\d{2})年(\d{1,2})月(\d{1,2})[日曰](\d{1,2})[:：](\d{2})')
CAPTURE_SECONDS=6
CAPTURE_FPS=12
MAX_SAMPLE_PIXELS=24_000_000

def compact(text):
    return re.sub(r'\s+','',text)

def date_headers(ocr, scale, image_width):
    headers=[]
    for line in ocr.get('lines',[]):
        text=compact(line.get('text',''))
        date=DATE.search(text)
        words=line.get('words',[])
        if not date or not words:continue
        left=min(word['x'] for word in words)/scale
        if left<image_width*.4:continue
        try: stamp=datetime(*map(int,date.groups())).strftime('%Y-%m-%d %H:%M')
        except ValueError:continue
        headers.append({'time':stamp,'top':min(w['y'] for w in words)/scale,
                        'bottom':max(w['y']+w['height'] for w in words)/scale,
                        'font_height':statistics.median(w['height'] for w in words)/scale})
    return sorted(headers,key=lambda value:value['top'])

def validate_record(messages,headers,title):
    senders={compact(m.get('sender','')) for m in messages}
    if len(senders)!=1 or not next(iter(senders),None):return False
    if compact(title)!=next(iter(senders))+'的聊天记录':return False
    return len(messages)==len(headers) and [m.get('time') for m in messages]==[h['time'] for h in headers]

def body_area(image, headers, index):
    header=headers[index];font=header['font_height']
    left=max(0,round(font*7));right=round(image.width*.95)
    top=round(header['bottom']+max(3,font*.25))
    bottom=round(headers[index+1]['top']-font*.7) if index+1<len(headers) else round(image.height-font*3)
    if right<=left or bottom<=top:return None
    return (left,top,right,bottom)

def content_bounds(tile):
    # The right edge of a record body is its plain background, beyond media.
    edge=tile.crop((max(0,tile.width-8),0,tile.width,tile.height)).resize((1,1))
    background=edge.getpixel((0,0))
    difference=ImageChops.difference(tile,Image.new('RGB',tile.size,background))
    red,green,blue=difference.split()
    mask=ImageChops.lighter(ImageChops.lighter(red,green),blue).point(lambda value:255 if value>35 else 0)
    box=mask.getbbox()
    if not box or box[2]-box[0]<36 or box[3]-box[1]<36:return None
    if (box[2]-box[0])*(box[3]-box[1])<2500:return None
    return box

def body_crop(image, headers, index):
    area=body_area(image,headers,index)
    if area is None:return None
    tile=image.convert('RGB').crop(area)
    box=content_bounds(tile)
    return tile.crop(box) if box else None

def stable_headers(reference,image,headers):
    """Reject scrolling, resizing or record switches during animation capture."""
    if image.size!=reference.size:return False
    for header in headers:
        box=(round(header['font_height']*7),max(0,round(header['top'])-2),
             round(image.width*.95),min(image.height,round(header['bottom'])+2))
        difference=ImageChops.difference(reference.crop(box).convert('RGB'),image.crop(box).convert('RGB'))
        if any(channel.point(lambda value:255 if value>12 else 0).getbbox() for channel in difference.split()):
            return False
    return True

def collect_animation(handle,reference,bounds,headers,indices,capture):
    areas={index:body_area(reference,headers,index) for index in indices}
    areas={index:area for index,area in areas.items() if area is not None}
    samples={index:[] for index in areas};digests={};pixels=0;elapsed=0;observed=0;limited=False
    def consume(image,current_bounds,at):
        nonlocal pixels,elapsed,observed,limited
        if current_bounds!=bounds or not stable_headers(reference,image,headers):
            raise ValueError('record_changed_during_animation')
        pending=[]
        for index,area in areas.items():
            tile=image.crop(area).convert('RGB')
            digest=hashlib.sha256(tile.tobytes()).digest()
            if digest!=digests.get(index):pending.append((index,tile,digest))
        additional=sum(tile.width*tile.height for _,tile,_ in pending)
        if pixels+additional>MAX_SAMPLE_PIXELS:
            limited=True
            return True
        for index,tile,digest in pending:
            samples[index].append((at,tile));digests[index]=digest
        pixels+=additional;elapsed=at;observed+=1
        return observed>=CAPTURE_SECONDS*CAPTURE_FPS+2
    try:
        capture(handle,consume,duration=CAPTURE_SECONDS,timeout=6,fps=CAPTURE_FPS)
        return samples,max(elapsed,1/CAPTURE_FPS),{
            'status':'sample_limit' if limited else ('captured' if observed else 'no_frames'),'frames_observed':observed,
            'seconds':round(elapsed,2)}
    except Exception as error:
        # Discard the sequence rather than mix a newly opened record into a GIF.
        return {},0,{'status':'capture_failed_'+type(error).__name__,'frames_observed':observed,'seconds':0}

def save_rendered_samples(samples,duration,root,index):
    """A changing sequence becomes a real GIF; a still image stays a PNG."""
    if not samples:return None
    boxes=[box for _,tile in samples if (box:=content_bounds(tile)) is not None]
    if not boxes:return None
    box=(min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
    frames=[];starts=[];previous=None
    for at,tile in samples:
        frame=tile.crop(box).convert('RGB');digest=hashlib.sha256(frame.tobytes()).digest()
        if digest!=previous:
            frames.append(frame);starts.append(at);previous=digest
    if len(frames)>1:
        durations=[max(20,round(((starts[i+1] if i+1<len(starts) else max(duration,at+1/CAPTURE_FPS))-at)*100)*10)
                   for i,at in enumerate(starts)]
        path=Path(root)/('rendered-animation-%05d.gif'%index)
        frames[0].save(path,format='GIF',save_all=True,append_images=frames[1:],
                       duration=durations,loop=0,disposal=2,optimize=False)
        with Image.open(path) as gif:
            count=getattr(gif,'n_frames',1)
            if count>1:return path,count
        path.unlink()  # Quantization can merge changes too small to survive GIF.
    path=Path(root)/('rendered-static-%05d.png'%index);frames[0].save(path,format='PNG')
    return path,1

def run_ocr(image,helper,scratch,label):
    source=scratch/(label+'.png');report=scratch/(label+'.json')
    image.save(source)
    try:
        process=subprocess.run([str(helper),str(source),str(report)],timeout=12,
                               creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True)
        value=json.loads(report.read_text(encoding='utf-8-sig'))
        if process.returncode or not value.get('ok'):raise ValueError('offline_ocr_unavailable')
        return value
    finally:
        source.unlink(missing_ok=True);report.unlink(missing_ok=True)

def analyze_frame(image,messages,title,helper,scratch,caption_height=100):
    senders={compact(message.get('sender','')) for message in messages}
    if len(senders)!=1 or not next(iter(senders),None):return None,'record_identity_not_unique'
    expected=next(iter(senders))+'的聊天记录'
    if compact(title)!=expected:
        # Read only the title strip until the selected merged record is proved.
        banner=image.crop((0,0,image.width,min(image.height,caption_height)))
        ratio=min(2.0,2400/max(banner.size))
        banner=banner.resize((round(banner.width*ratio),round(banner.height*ratio)),Image.Resampling.LANCZOS)
        result=run_ocr(banner,helper,scratch,'record-title')
        if not any(compact(line.get('text',''))==expected for line in result.get('lines',[])):
            return None,'record_identity_mismatch'
        title=expected
    scale=min(2.0,2400/max(image.size))
    enhanced=image.convert('L').point(lambda value:0 if value<215 else 255)
    enhanced=enhanced.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.LANCZOS)
    headers=date_headers(run_ocr(enhanced,helper,scratch,'timestamps'),scale,image.width)
    if len(headers)!=len(messages):return None,'visible_message_count_mismatch'
    if not validate_record(messages,headers,title):return None,'record_identity_mismatch'
    return headers,'matched'

def supplement(data,helper):
    needed=[index for index,m in enumerate(data['messages']) if m['kind']=='image' and not m.get('path')]
    if not needed:return 0
    from wechat_reader import list_windows
    from page_capture import window_frame,capture_window
    root=Path(data['media_root']);scratch=root/'page-probe';scratch.mkdir()
    status='record_window_not_found';matches=[]
    try:
        windows=list_windows()
        preferred=[w for w in windows if compact(w.get('title','')).endswith('聊天记录')]
        if preferred:windows=preferred
        if len(windows)>4:
            data['capture_info']['rendered_page_status']='multiple_record_windows'
            return 0
        for window in windows:
            try:
                image,bounds=window_frame(window['handle'],timeout=6)
                if image.width<240 or image.height<240:continue
                import ctypes
                user=ctypes.WinDLL('user32')
                user.GetDpiForWindow.argtypes=[ctypes.c_void_p];user.GetDpiForWindow.restype=ctypes.c_uint
                dpi=user.GetDpiForWindow(window['handle']) or 96
                headers,status=analyze_frame(image,data['messages'],window.get('title',''),helper,scratch,round(90*dpi/96))
                if headers is not None:matches.append((image,headers,bounds,window['handle']))
            except Exception as error:
                status='capture_failed_'+type(error).__name__
        if len(matches)!=1:
            data['capture_info']['rendered_page_status']='ambiguous_record_identity' if len(matches)>1 else status
            return 0
        image,headers,bounds,handle=matches[0];saved=0;animated=0
        samples,duration,animation=collect_animation(handle,image,bounds,headers,needed,capture_window)
        data['capture_info'].update(rendered_animation_status=animation['status'],
                                    rendered_capture_frames=animation['frames_observed'],
                                    rendered_capture_seconds=animation['seconds'])
        for index in needed:
            row_samples=samples.get(index,[])
            if not row_samples:
                area=body_area(image,headers,index)
                row_samples=[(0,image.crop(area).convert('RGB'))] if area else []
            result=save_rendered_samples(row_samples,duration,root,index)
            if result is None:continue
            path,count=result
            moving=count>1
            data['messages'][index].update(path=str(path),text='',
                media_quality='rendered_page_animation' if moving else 'rendered_page_static',media_hint='emoji')
            if moving:animated+=1
            elif data['messages'][index].get('raw_text','').startswith('[动画表情]'):
                notice='动态表情在本次采集期间未取得连续动画，已保存静态图。'
                if notice not in data['capture_warnings']:data['capture_warnings'].append(notice)
            saved+=1
        data['capture_info']['rendered_page_status']='animated_images_saved' if animated else ('static_images_saved' if saved else 'no_image_region')
        data['capture_info']['rendered_static_images']=saved-animated
        data['capture_info']['rendered_gif_images']=animated
        remaining=sum(m['kind']!='text' and not m.get('path') for m in data['messages'])
        data['capture_info']['missing_media']=remaining
        if not remaining:
            data['capture_warnings']=[value for value in data['capture_warnings']
                                      if not value.startswith('微信分享包只有聊天文字') and '条媒体尚未与分享包内' not in value]
        return saved
    except Exception as error:
        data['capture_info']['rendered_page_status']='capture_failed_'+type(error).__name__
        return 0
    finally:
        if scratch.exists() and not any(scratch.iterdir()):scratch.rmdir()
