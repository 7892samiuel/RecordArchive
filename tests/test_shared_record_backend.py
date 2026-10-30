import importlib.util
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

SOURCE=Path(__file__).parents[1]/'share-import/shared_record_backend.py'
TEST_ROOT=Path(__file__).parent/'native-test-work'
TEST_ROOT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('shared_record_backend_test',SOURCE)
backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
render_spec=importlib.util.spec_from_file_location('rendered_media_test',SOURCE.with_name('rendered_media.py'))
rendered=importlib.util.module_from_spec(render_spec);render_spec.loader.exec_module(rendered)

def transcript(body):
    return '·测试者\n2026年10月28日 10:00\n'+body+'\n'

class NativeArchiveTests(unittest.TestCase):
    def test_duplicate_multiline_messages_preserved(self):
        text=transcript('一行\n两行')*2
        messages=backend.parse_messages(text)
        self.assertEqual(len(messages),2)
        self.assertEqual([m['text'] for m in messages],['一行\n两行']*2)

    def test_exact_reference_and_ambiguous_basename(self):
        entries={'a/image.jpg':None,'b/image.jpg':None,'a/image_11.jpg':None}
        self.assertIsNone(backend.resolve_reference('[图片] image.jpg',entries))
        self.assertEqual(backend.resolve_reference('[图片] a/image.jpg',entries),'a/image.jpg')
        self.assertIsNone(backend.resolve_reference('正文 image_11.jpg',entries))
        self.assertIsNone(backend.resolve_reference('[图片] image_1.jpg',entries))

    def test_missing_voice_and_emoji_are_not_fabricated(self):
        messages=backend.parse_messages(transcript('[语音] 2"')+transcript('[动画表情]'))
        self.assertEqual([m['kind'] for m in messages],['audio','image'])
        self.assertTrue(all(not m.get('path') for m in messages))

    def test_gif_bytes_and_full_frames_preserved(self):
        stream=BytesIO()
        Image.new('RGB',(12,12),'red').save(stream,format='GIF',save_all=True,append_images=[Image.new('RGB',(12,12),'blue')],duration=100,loop=0)
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as root:
            root=Path(root);archive=root/'shared.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('聊天记录.txt',transcript('[动画表情] face.gif'))
                z.writestr('聊天记录内的图片、视频和文件/face.gif',stream.getvalue())
            data=backend.parse_archive(archive,root/'parsed')
            image=Path(data['messages'][0]['path'])
            self.assertEqual(image.read_bytes(),stream.getvalue())
            with Image.open(image) as gif:self.assertEqual(gif.n_frames,2)

    def test_reject_zip_traversal_and_alias_conflict(self):
        for names in [('../escape.jpg',),('folder/a.jpg','folder/A.jpg')]:
            stream=BytesIO()
            with zipfile.ZipFile(stream,'w') as z:
                for name in names:z.writestr(name,b'x')
            with zipfile.ZipFile(BytesIO(stream.getvalue())) as z:
                with self.assertRaises(ValueError):backend.index_entries(z)

    def test_reject_ambiguous_transcripts(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as root:
            root=Path(root);archive=root/'shared.zip'
            with zipfile.ZipFile(archive,'w') as z:
                for name in ('a/聊天记录.txt','b/聊天记录.txt'):z.writestr(name,transcript('文字'))
            with self.assertRaises(ValueError):backend.parse_archive(archive,root/'parsed')

    def test_received_but_unassociated_media_is_not_reported_as_absent(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as root:
            root=Path(root);archive=root/'shared.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('聊天记录.txt',transcript('[图片] unknown.jpg'))
                z.writestr('attachments/actual.jpg',b'not matched, must stay in original ZIP')
            data=backend.parse_archive(archive,root/'parsed')
            self.assertEqual(data['capture_info']['attachment_entry_count'],1)
            self.assertEqual(data['capture_info']['unassociated_files'],1)
            self.assertTrue(any('尚未与分享包内' in warning for warning in data['capture_warnings']))
            self.assertFalse(any('未包含' in warning for warning in data['capture_warnings']))

    def test_rendered_record_requires_title_and_full_timestamp_sequence(self):
        messages=[{'sender':'测试者','time':'2026-10-28 10:00'},{'sender':'测试者','time':'2026-10-28 10:01'}]
        headers=[{'time':m['time']} for m in messages]
        self.assertTrue(rendered.validate_record(messages,headers,'测试者的聊天记录'))
        self.assertFalse(rendered.validate_record(messages,headers,'其他人的聊天记录'))
        self.assertFalse(rendered.validate_record(messages,headers[::-1],'测试者的聊天记录'))
        self.assertFalse(rendered.validate_record(messages,headers[:1],'测试者的聊天记录'))

    def test_rendered_crop_excludes_headers_and_rejects_empty_body(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(700,450),(250,250,250))
        headers=[{'top':50,'bottom':65,'font_height':12},{'top':230,'bottom':245,'font_height':12}]
        self.assertIsNone(rendered.body_crop(image,headers,0))
        ImageDraw.Draw(image).rectangle((110,80,230,200),fill='red')
        crop=rendered.body_crop(image,headers,0)
        self.assertEqual(crop.size,(121,121))
        self.assertEqual(crop.getpixel((0,0)),(255,0,0))

    def test_rendered_animation_keeps_motion_canvas_and_frame_timing(self):
        from PIL import ImageDraw
        first=Image.new('RGB',(240,160),(250,250,250))
        last=first.copy()
        ImageDraw.Draw(first).rectangle((20,20,80,100),fill='red')
        ImageDraw.Draw(last).rectangle((100,20,160,100),fill='blue')
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as root:
            path,count=rendered.save_rendered_samples([(0,first),(.1,first.copy()),(.3,last)],.5,root,0)
            self.assertEqual(path.suffix,'.gif')
            self.assertEqual(count,2)
            with Image.open(path) as gif:
                self.assertEqual(gif.size,(141,81))
                self.assertEqual(gif.info['loop'],0)
                self.assertEqual(gif.info['duration'],300)
                gif.seek(1)
                self.assertEqual(gif.info['duration'],200)
                frame=gif.convert('RGB')
                self.assertEqual(frame.getpixel((0,0)),(250,250,250))
                self.assertEqual(frame.getpixel((140,0)),(0,0,255))

    def test_still_samples_stay_png_instead_of_fake_animated_extension(self):
        from PIL import ImageDraw
        frame=Image.new('RGB',(200,140),(250,250,250))
        ImageDraw.Draw(frame).rectangle((20,20,100,100),fill='red')
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as root:
            path,count=rendered.save_rendered_samples([(0,frame),(.2,frame.copy())],.4,root,0)
            self.assertEqual((path.suffix,count),('.png',1))
            self.assertFalse(list(Path(root).glob('*.gif')))

    def test_capture_discards_sequence_when_record_scrolls(self):
        from PIL import ImageDraw
        frame=Image.new('RGB',(700,450),(250,250,250))
        headers=[{'top':50,'bottom':65,'font_height':12}]
        changed=frame.copy()
        ImageDraw.Draw(changed).rectangle((110,51,150,60),fill='black')
        bounds=(0,0,700,450)
        def capture(handle,consume,**kwargs):
            consume(frame,bounds,0)
            consume(changed,bounds,.1)
        samples,seconds,info=rendered.collect_animation(1,frame,bounds,headers,[0],capture)
        self.assertEqual(samples,{})
        self.assertEqual(seconds,0)
        self.assertEqual(info['status'],'capture_failed_ValueError')

    def test_capture_deduplicates_still_frames_before_memory_limit(self):
        from PIL import ImageDraw
        frame=Image.new('RGB',(700,450),(250,250,250))
        ImageDraw.Draw(frame).rectangle((110,80,230,200),fill='red')
        headers=[{'top':50,'bottom':65,'font_height':12}]
        bounds=(0,0,700,450)
        def capture(handle,consume,**kwargs):
            for index in range(30):
                if consume(frame,bounds,index*.1):break
        samples,seconds,info=rendered.collect_animation(1,frame,bounds,headers,[0],capture)
        self.assertEqual(len(samples[0]),1)
        self.assertEqual(info['frames_observed'],30)
        self.assertAlmostEqual(seconds,2.9)

    def test_capture_bounds_retained_animation_memory(self):
        from PIL import ImageDraw
        from unittest.mock import patch
        frame=Image.new('RGB',(700,450),(250,250,250))
        headers=[{'top':50,'bottom':65,'font_height':12}]
        bounds=(0,0,700,450)
        area=rendered.body_area(frame,headers,0)
        pixels=(area[2]-area[0])*(area[3]-area[1])
        def capture(handle,consume,**kwargs):
            for index in range(10):
                image=frame.copy()
                ImageDraw.Draw(image).rectangle((110,80,230,200),fill=(index*20,0,0))
                if consume(image,bounds,index*.1):break
        with patch.object(rendered,'MAX_SAMPLE_PIXELS',pixels*2):
            samples,_,info=rendered.collect_animation(1,frame,bounds,headers,[0],capture)
        self.assertEqual(len(samples[0]),2)
        self.assertEqual(info['status'],'sample_limit')

    def test_supplement_wires_stream_capture_to_real_gif_attachment(self):
        from PIL import ImageDraw
        from types import SimpleNamespace
        from unittest.mock import patch
        frame=Image.new('RGB',(700,450),(250,250,250));changed=frame.copy()
        ImageDraw.Draw(frame).rectangle((110,80,230,200),fill='red')
        ImageDraw.Draw(changed).rectangle((150,80,270,200),fill='blue')
        headers=[{'top':50,'bottom':65,'font_height':12,'time':'2026-10-28 10:00'}]
        bounds=(0,0,700,450)
        def capture(handle,consume,**kwargs):
            consume(frame,bounds,0);consume(changed,bounds,.2);consume(changed,bounds,.4)
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as root:
            data={'media_root':root,'messages':[{'kind':'image','sender':'测试者','time':'2026-10-28 10:00','raw_text':'[动画表情]'}],
                  'capture_info':{'missing_media':1},'capture_warnings':[]}
            reader=SimpleNamespace(list_windows=lambda:[{'title':'测试者的聊天记录','handle':1}])
            capture_module=SimpleNamespace(window_frame=lambda *args,**kwargs:(frame,bounds),capture_window=capture)
            with patch.dict('sys.modules',{'wechat_reader':reader,'page_capture':capture_module}),patch.object(rendered,'analyze_frame',return_value=(headers,'matched')):
                self.assertEqual(rendered.supplement(data,Path(root)/'unused.exe'),1)
            self.assertEqual(data['capture_info']['rendered_gif_images'],1)
            self.assertEqual(data['capture_info']['missing_media'],0)
            self.assertEqual(data['messages'][0]['media_quality'],'rendered_page_animation')
            with Image.open(data['messages'][0]['path']) as gif:
                self.assertEqual((gif.format,gif.n_frames),('GIF',2))

if __name__=='__main__':unittest.main()
