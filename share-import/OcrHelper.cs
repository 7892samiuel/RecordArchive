// Uses the Windows built-in offline OCR engine. No downloads or networking.
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Windows.Foundation;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage;

internal static class OcrHelper {
    static Task<T> Wait<T>(IAsyncOperation<T> operation) {
        var ready=new TaskCompletionSource<T>();
        operation.Completed=(result,status)=>{
            try {
                if(status==AsyncStatus.Canceled) ready.SetCanceled();
                else if(status==AsyncStatus.Error) ready.SetException(result.ErrorCode);
                else ready.SetResult(result.GetResults());
            } catch(Exception error){ready.TrySetException(error);}
            finally{result.Close();}
        };
        return ready.Task;
    }
    static async Task Read(string imagePath,string outputPath) {
        var engine=OcrEngine.TryCreateFromUserProfileLanguages();
        if(engine==null) throw new InvalidOperationException("Windows 当前没有可用的离线文字识别组件。");
        var file=await Wait(StorageFile.GetFileFromPathAsync(Path.GetFullPath(imagePath)));
        using(var stream=await Wait(file.OpenReadAsync())) {
            var decoder=await Wait(BitmapDecoder.CreateAsync(stream));
            using(var bitmap=await Wait(decoder.GetSoftwareBitmapAsync(BitmapPixelFormat.Bgra8,BitmapAlphaMode.Premultiplied))) {
                if(bitmap.PixelWidth>OcrEngine.MaxImageDimension || bitmap.PixelHeight>OcrEngine.MaxImageDimension)
                    throw new InvalidDataException("记录画面超出 Windows 文字识别尺寸。");
                var result=await Wait(engine.RecognizeAsync(bitmap));
                var lines=new List<object>();
                foreach(var line in result.Lines) {
                    var words=new List<object>();
                    foreach(var word in line.Words) {
                        var rect=word.BoundingRect;
                        words.Add(new {text=word.Text,x=rect.X,y=rect.Y,width=rect.Width,height=rect.Height});
                    }
                    lines.Add(new {text=line.Text,words=words});
                }
                File.WriteAllText(outputPath,new JavaScriptSerializer().Serialize(new {ok=true,language=engine.RecognizerLanguage.LanguageTag,lines=lines}));
            }
        }
    }
    [STAThread] static int Main(string[] args) {
        if(args.Length!=2) return 2;
        int exitCode=0;
        using(var control=new Control()) {
            var handle=control.Handle;
            SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
            var context=new ApplicationContext();
            Read(args[0],args[1]).ContinueWith(task=>control.BeginInvoke(new Action(()=>{
                if(task.IsFaulted) {
                    exitCode=1;
                    File.WriteAllText(args[1],new JavaScriptSerializer().Serialize(new {ok=false,error=task.Exception.GetBaseException().Message}));
                }
                context.ExitThread();
            })));
            Application.Run(context);
        }
        return exitCode;
    }
}
