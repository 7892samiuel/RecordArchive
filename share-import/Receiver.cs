// Receive only the ZIP explicitly shared by the user; no WeChat cache access.
// Copy-before-completion follows WeChatBridge / ChatPCBridge (MIT); see notices.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Windows.ApplicationModel;
using Windows.ApplicationModel.Activation;
using Windows.ApplicationModel.DataTransfer;
using Windows.ApplicationModel.DataTransfer.ShareTarget;
using Windows.Storage;
using Windows.Foundation;

internal static class Receiver {
    const string EventName = "Local\\RecordArchive.PortableShare.ReadCurrentPage";
    const string MainMutex = "Local\\RecordArchive.PortableShare.Main";
    const long MaxBytes = 1024L * 1024 * 1024;
    static string Inbox = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".record-archive", "RecordArchive.PortableShare", "incoming");
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern int GetCurrentPackageFullName(ref uint length, StringBuilder value);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern int GetCurrentPackageFamilyName(ref uint length, StringBuilder value);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern int GetCurrentApplicationUserModelId(ref uint length, StringBuilder value);
    delegate int IdentityQuery(ref uint length, StringBuilder value);
    static string Identity(IdentityQuery query, out int error) {
        uint length=0;error=query(ref length,null);
        if (error!=122 || length==0 || length>65536) return "";
        var value=new StringBuilder((int)length);
        error=query(ref length,value);
        return error==0 ? value.ToString() : "";
    }
    static int CapabilityCheck(string report) {
        bool receiverSupported=Windows.Foundation.Metadata.ApiInformation.IsTypePresent(
            "Windows.ApplicationModel.DataTransfer.ShareTarget.ShareOperation") &&
            Windows.Foundation.Metadata.ApiInformation.IsMethodPresent(
            "Windows.ApplicationModel.AppInstance","GetActivatedEventArgs");
        bool supported=Windows.Foundation.Metadata.ApiInformation.IsTypePresent(
            "Windows.ApplicationModel.DataTransfer.TransferTarget") &&
            Windows.Foundation.Metadata.ApiInformation.IsMethodPresent(
            "Windows.ApplicationModel.DataTransfer.TransferTarget","CreateWatcher");
        File.WriteAllText(report,new JavaScriptSerializer().Serialize(new Dictionary<string,object> {
            {"ok",true},{"share_target_supported",receiverSupported},{"transfer_target_supported",supported}
        }));
        return 0;
    }
    static int RegistrationCheck(string report) {
        int packageError,familyError,appError;
        string full=Identity(GetCurrentPackageFullName,out packageError);
        string family=Identity(GetCurrentPackageFamilyName,out familyError);
        string app=Identity(GetCurrentApplicationUserModelId,out appError);
        bool ok=packageError==0 && familyError==0 && appError==0 &&
                full.StartsWith("RecordArchive.PortableShare_",StringComparison.Ordinal) && app==family+"!App";
        var state=new Dictionary<string,object> {
            {"ok",ok},{"package_full_name",full},{"application_id",app},
            {"package_error",packageError},{"family_error",familyError},{"application_error",appError}
        };
        if (ok) {
            try {
                var entries=Package.Current.GetAppListEntries();
                state["app_list_entry_count"]=entries.Count;
                bool found=false;
                foreach (var entry in entries) {
                    if (entry.AppUserModelId==app && entry.DisplayInfo.DisplayName=="记录归档") {
                        found=true;
                        try {
                            state["app_logo_readable"]=Task.Run(async () => {
                                using (var logo=await Wait(entry.DisplayInfo.GetLogo(new Size(44,44)).OpenReadAsync()))
                                    return logo.Size>0;
                            }).GetAwaiter().GetResult();
                        } catch (Exception error) { state["app_logo_error"]=error.HResult; }
                    }
                }
                state["app_list_entry_resolved"]=found;
            } catch (Exception error) { state["enumeration_error"]=error.HResult; }
            try {
                var map=Windows.ApplicationModel.Resources.Core.ResourceManager.Current.MainResourceMap;
                state["app_logo_indexed"]=map.GetValue("Files/Assets/Square44x44Logo.png").ValueAsString.Length>0;
            } catch (Exception error) { state["resource_index_error"]=error.HResult; }
        }
        File.WriteAllText(report,new JavaScriptSerializer().Serialize(state));
        return ok ? 0 : 1;
    }
    static void Trace(string stage, Exception error = null, bool? share = null, bool? accepted = null, long? bytes = null) {
        try {
            string folder = Path.Combine(Path.GetDirectoryName(Inbox), "diagnostics");
            PrivateDirectory(folder);
            var state = new Dictionary<string, object> { {"utc", DateTime.UtcNow.ToString("o")}, {"stage", stage} };
            if (error != null) { state["error_type"] = error.GetType().Name; state["hresult"] = error.HResult; }
            if (share.HasValue) state["share_activation"] = share.Value;
            if (accepted.HasValue) state["accepted"] = accepted.Value;
            if (bytes.HasValue) state["bytes"] = bytes.Value;
            File.WriteAllText(Path.Combine(folder, "receiver-state.json"), new JavaScriptSerializer().Serialize(state));
        } catch { }
    }
    static Task<T> Wait<T>(IAsyncOperation<T> operation) {
        var completion = new TaskCompletionSource<T>();
        operation.Completed = (result, status) => {
            try {
                if (status == AsyncStatus.Canceled) completion.SetCanceled();
                else if (status == AsyncStatus.Error) completion.SetException(result.ErrorCode);
                else completion.SetResult(result.GetResults());
            } catch (Exception error) { completion.TrySetException(error); }
            finally { result.Close(); }
        };
        return Timed(operation, completion.Task);
    }
    static async Task<T> Timed<T>(IAsyncOperation<T> operation, Task<T> completion) {
        if (await Task.WhenAny(completion, Task.Delay(30000)) != completion) {
            try { operation.Cancel(); } catch { }
            throw new TimeoutException("微信交付分享数据超时，请重新打开合并转发菜单后重试。");
        }
        return await completion;
    }
    static void PrivateDirectory(string path) {
        if (Directory.Exists(path) && (File.GetAttributes(path) & System.IO.FileAttributes.ReparsePoint) != 0)
            throw new IOException("接收目录被重定向，未写入记录。");
        Directory.CreateDirectory(path);
        var acl = new DirectorySecurity();
        acl.SetAccessRuleProtection(true, false);
        var owner = WindowsIdentity.GetCurrent().User;
        acl.SetOwner(owner);
        foreach (var sid in new[] { owner, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null) })
            acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        Directory.SetAccessControl(path, acl);
    }
    static async Task SaveFile(StorageFile file) {
        if (!String.Equals(Path.GetExtension(file.Name), ".zip", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("请一次转发一份微信合并聊天记录。");
        var properties = await Wait(file.GetBasicPropertiesAsync());
        if (properties.Size == 0 || properties.Size > (ulong)MaxBytes)
            throw new InvalidDataException("分享文件为空或超过 1 GB。");
        PrivateDirectory(Inbox);
        string id = Guid.NewGuid().ToString("N");
        string stage = Path.Combine(Inbox, id + ".receiving");
        PrivateDirectory(stage);
        try {
            var folder = await Wait(StorageFolder.GetFolderFromPathAsync(stage));
            await Wait(file.CopyAsync(folder, "original.zip", NameCollisionOption.FailIfExists));
            string original = Path.Combine(stage, "original.zip");
            long size = new FileInfo(original).Length;
            if (size != (long)properties.Size) throw new IOException("分享文件未完整复制。");
            string digest;
            using (var input = File.OpenRead(original))
            using (var sha = SHA256.Create()) digest = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
            var metadata = new Dictionary<string, object> {
                {"schema", 1}, {"id", id}, {"name", file.Name}, {"bytes", size},
                {"sha256", digest}, {"received_utc", DateTime.UtcNow.ToString("o")}
            };
            File.WriteAllText(Path.Combine(stage, "batch.json"), new JavaScriptSerializer().Serialize(metadata));
            Directory.Move(stage, Path.Combine(Inbox, id));
            Trace("zip_saved", bytes: size);
        } catch {
            // Only fixed files in this newly generated private stage are owned.
            foreach (string name in new[] { "original.zip", "batch.json" }) {
                string owned = Path.Combine(stage, name);
                if (File.Exists(owned) && (File.GetAttributes(owned) & System.IO.FileAttributes.ReparsePoint) == 0) File.Delete(owned);
            }
            if (Directory.Exists(stage) && Directory.GetFileSystemEntries(stage).Length == 0) Directory.Delete(stage);
            throw;
        }
    }
    static void StartMain() {
        try { using (Mutex.OpenExisting(MainMutex)) return; }
        catch (WaitHandleCannotBeOpenedException) { }
        string exe = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "WeChatRecordExporter.exe"));
        if (!File.Exists(exe)) throw new FileNotFoundException("找不到归档主程序，请保留完整应用目录。");
        Process.Start(new ProcessStartInfo(exe) { UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(exe) });
    }
    static bool Activate(string name, bool launch) {
        using (var request = new EventWaitHandle(false, EventResetMode.ManualReset, name))
        using (var accepted = new EventWaitHandle(false, EventResetMode.AutoReset, name + ".Accepted")) {
            accepted.Reset(); request.Set();
            try { if (launch) StartMain(); return accepted.WaitOne(15000); }
            finally { request.Reset(); }
        }
    }
    static async Task Receive(ShareOperation operation) {
        Trace("share_started", share: true);
        operation.ReportStarted();
        if (!operation.Data.Contains(StandardDataFormats.StorageItems))
            throw new InvalidDataException("请从微信合并记录选择“转发到其他应用 → 记录归档”。");
        var items = await Wait(operation.Data.GetStorageItemsAsync());
        if (items.Count != 1 || !(items[0] is StorageFile))
            throw new InvalidDataException("请一次转发一份微信合并聊天记录。");
        await SaveFile((StorageFile)items[0]);
        operation.ReportDataRetrieved();
        // The user-selected content is now safely copied, before the OS reclaims it.
        bool accepted = await Task.Run(() => Activate(EventName, true));
        Trace("main_notified", share: true, accepted: accepted);
        operation.ReportCompleted();
        if (!accepted)
            MessageBox.Show("记录已收到。请在工具完成当前编辑后点击“读取微信记录”。", "记录归档");
    }
    static async Task Run(string[] args) {
        if (args.Length == 3 && args[0] == "--storage-test") {
            Inbox = Path.GetFullPath(args[2]);
            await SaveFile(await Wait(StorageFile.GetFileFromPathAsync(Path.GetFullPath(args[1]))));
            return;
        }
        IActivatedEventArgs activation = null;
        Exception activationError = null;
        try { activation = AppInstance.GetActivatedEventArgs(); }
        catch (Exception error) { activationError = error; }
        var share = activation as IShareTargetActivatedEventArgs;
        if (share == null) { Trace("direct_start", activationError, share: false); StartMain(); return; }
        try { await Receive(share.ShareOperation); }
        catch (Exception error) {
            Trace("share_failed", error, share: true);
            try { share.ShareOperation.ReportError(error.Message); } catch { }
            MessageBox.Show(error.Message, "记录归档");
        }
    }
    [STAThread] static int Main(string[] args) {
        // This query works without registration and must not start the main app.
        if (args.Length==2 && args[0]=="--capability-check") {
            try {return CapabilityCheck(args[1]);}
            catch(Exception error) {
                File.WriteAllText(args[1],new JavaScriptSerializer().Serialize(new Dictionary<string,object> {
                    {"ok",false},{"hresult",error.HResult}
                }));
                return 1;
            }
        }
        // Probe mode must never launch the app, create incoming data or signal IPC.
        if (args.Length==2 && args[0]=="--registration-check") {
            try { return RegistrationCheck(args[1]); }
            catch (Exception error) {
                File.WriteAllText(args[1],new JavaScriptSerializer().Serialize(new Dictionary<string,object> {
                    {"ok",false},{"error_type",error.GetType().Name},{"hresult",error.HResult}
                }));
                return 1;
            }
        }
        if (args.Length == 2 && args[0] == "--activation-test") return Activate(args[1], false) ? 0 : 1;
        int exitCode = 0;
        using (var control = new Control()) {
            var handle = control.Handle;
            SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
            var context = new ApplicationContext();
            Run(args).ContinueWith(task => control.BeginInvoke(new Action(() => {
                if (task.IsFaulted) {
                    exitCode = 1;
                    if (args.Length == 3 && args[0] == "--storage-test") File.WriteAllText(Path.Combine(args[2], "test-error.txt"), task.Exception.GetBaseException().Message);
                    else MessageBox.Show(task.Exception.GetBaseException().Message, "记录归档");
                }
                context.ExitThread();
            })));
            Application.Run(context);
        }
        return exitCode;
    }
}
