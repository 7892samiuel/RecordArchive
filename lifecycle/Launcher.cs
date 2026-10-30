using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class Launcher {
    const string Fingerprint = "945694BF185971C80B144A97421C58D564C32FD5";
    const string IdentityHash = "@@IDENTITY_SHA256@@";
    static string Base = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
    static bool? TransferTargetAvailable;
    static string ShareSetupFailure;
    static string Quote(string text) { return "'" + text.Replace("'", "''") + "'"; }
    static string Encoded(string text) { return Convert.ToBase64String(Encoding.Unicode.GetBytes(text)); }
    static string SystemShell { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"); } }
    static Dictionary<string,object> Load(string path) { return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(path, Encoding.UTF8)); }
    static bool Flag(Dictionary<string,object> data, string key) { return data.ContainsKey(key) && Convert.ToBoolean(data[key]); }
    static bool ShareCapability() {
        var info=Load(Path.Combine(Base,"_internal","build-info.json"));
        string receiver=Path.Combine(Base,"_internal","RecordShareReceiver.exe");
        if (!info.ContainsKey("receiver_capability_probe_version") || Convert.ToInt32(info["receiver_capability_probe_version"])!=2)
            throw new Exception("分享组件版本不匹配，请完整解压新版。");
        using(var file=File.OpenRead(receiver))
        using(var sha=SHA256.Create()) {
            string hash=BitConverter.ToString(sha.ComputeHash(file)).Replace("-","").ToLowerInvariant();
            if (hash!=Convert.ToString(info["receiver_sha256"])) throw new Exception("分享组件不完整，请重新解压。");
        }
        string report=Path.Combine(Path.GetTempPath(),"RecordArchiveCapability-"+Guid.NewGuid().ToString("N")+".json");
        try {
            var start=new ProcessStartInfo(receiver,"--capability-check \""+report+"\"");
            start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
            using(var process=Process.Start(start)) {
                if(!process.WaitForExit(10000)){process.Kill();throw new Exception("系统分享能力查询超时。");}
                var result=Load(report);
                if(process.ExitCode!=0 || !Flag(result,"ok")) throw new Exception("系统分享能力查询失败。");
                TransferTargetAvailable=Flag(result,"transfer_target_supported");
                // Legacy ShareTarget receipt works independently of the newer
                // TransferTarget discovery API used by WeChat's share sender.
                return Flag(result,"share_target_supported");
            }
        }finally{if(File.Exists(report))File.Delete(report);}
    }
    static bool PrepareSharing(Func<bool> available,Action initialize) {
        try {
            if(!available())return false;
            initialize();return true;
        } catch(OperationCanceledException) {
            ShareSetupFailure="cancelled";
        } catch(Exception error) {
            // Keep the UI available to explain setup failure and let users
            // inspect already received batches. Never imply registration worked.
            ShareSetupFailure=error.GetType().Name;
        }
        return false;
    }
    static Dictionary<string,object> Run(string action, string root, string support, bool elevated) {
        string report = Path.Combine(Path.GetTempPath(), "RecordArchiveSetup-" + Guid.NewGuid().ToString("N") + ".json");
        string script = Path.Combine(support, "setup.ps1");
        string command = "$ErrorActionPreference='Stop'; $env:PSModulePath=Join-Path $PSHOME 'Modules'; & ([ScriptBlock]::Create([IO.File]::ReadAllText(" + Quote(script) + "))) -Action " + action + " -AppRoot " + Quote(root) + " -SupportRoot " + Quote(support) + " -ExpectedFingerprint " + Quote(Fingerprint) + " -Report " + Quote(report);
        if (elevated) {
            if (action != "Trust") throw new Exception("不支持的管理员操作。");
            string package = Path.Combine(root, "share", "RecordArchive.Identity.msix");
            command = "$ErrorActionPreference='Stop'; $env:PSModulePath=Join-Path $PSHOME 'Modules'; $file=" + Quote(package) + "; " +
                "if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine '" + IdentityHash + "') { throw 'Identity hash mismatch' }; " +
                "$signature=Get-AuthenticodeSignature -LiteralPath $file; $cert=$signature.SignerCertificate; " +
                "if (-not $cert -or $cert.Thumbprint -ne '" + Fingerprint + "' -or $cert.NotBefore -gt (Get-Date) -or $cert.NotAfter -le (Get-Date)) { throw 'Unexpected certificate' }; " +
                "$basic=@($cert.Extensions|Where-Object {$_.Oid.Value -eq '2.5.29.19'}); $usage=@($cert.Extensions|Where-Object {$_.Oid.Value -eq '2.5.29.37'}); " +
                "if (-not $basic.Count -or $basic[0].CertificateAuthority -or -not $usage.Count -or $usage[0].EnhancedKeyUsages.Count -ne 1 -or $usage[0].EnhancedKeyUsages[0].Value -ne '1.3.6.1.5.5.7.3.3') { throw 'Code signing leaf required' }; " +
                "$store=New-Object Security.Cryptography.X509Certificates.X509Store('TrustedPeople','LocalMachine'); " +
                "$public=[Security.Cryptography.X509Certificates.X509Certificate2]::new($cert.RawData); try { $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite); $store.Add($public) } finally { $store.Close(); $public.Dispose() }; " +
                "if ((Get-AuthenticodeSignature -LiteralPath $file).Status -ne 'Valid') { throw 'Signature is not trusted' }";
        }
        ProcessStartInfo start = new ProcessStartInfo(SystemShell, "-NoProfile -NonInteractive -EncodedCommand " + Encoded(command));
        start.UseShellExecute = elevated; start.CreateNoWindow = !elevated; start.WindowStyle = ProcessWindowStyle.Hidden;
        if (elevated) start.Verb = "runas";
        try {
            using (Process process = Process.Start(start)) {
                if (!process.WaitForExit(90000)) throw new Exception("初始化等待超时，请稍后重试。");
                if (elevated) {
                    if (process.ExitCode != 0) throw new Exception("管理员初始化未完成，未启用分享入口。请检查是否取消了授权，或重新获取完整文件。");
                    return new Dictionary<string,object>{{"ok",true}};
                }
                if (!File.Exists(report)) throw new Exception("初始化未完成。若取消了管理员授权，分享入口不会启用。");
                var result = Load(report);
                if (process.ExitCode != 0 || !Flag(result, "ok")) throw new Exception(result.ContainsKey("error") ? Convert.ToString(result["error"]) : "操作未完成。");
                return result;
            }
        } finally { if (File.Exists(report)) File.Delete(report); }
    }
    static void Initialize(bool preapproved) {
        string support = Path.Combine(Base, "_internal", "distribution");
        var status = Run("Status", Base, support, false);
        if (!Flag(status, "trusted")) {
            if (!preapproved && MessageBox.Show("首次启用微信分享，需要将本工具的测试代码签名证书加入本机“受信任的人”，影响本机所有用户，并请求一次管理员授权。\n\n不添加根证书，不关闭签名检查。此为测试版，证书有效至 2026-11-11；尚非正式公众签名。\n\n是否继续？", "记录归档 · 首次初始化", MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes)
                throw new OperationCanceledException("已取消初始化，没有启用分享入口。");
            Run("Trust", Base, support, true);
        }
        Run("Register", Base, support, false);
    }
    static void Uninstall(bool quiet) {
        string root = Base, support = Path.Combine(Base, "_internal", "distribution");
        string cachedInfo = Path.Combine(Base, "install.json");
        if (File.Exists(cachedInfo)) { root = Convert.ToString(Load(cachedInfo)["root"]); support = Base; }
        else {
            string cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".record-archive", "RecordArchiveLifecycle");
            string info = Path.Combine(cache, "install.json");
            if (File.Exists(info) && String.Equals(Convert.ToString(Load(info)["root"]).TrimEnd(Path.DirectorySeparatorChar), root, StringComparison.OrdinalIgnoreCase)) support = cache;
        }
        if (!quiet && MessageBox.Show("卸载将注销当前用户的微信分享入口并移除程序文件。导出文件和其他个人文件会保留。\n\n请先保存并关闭记录归档，是否继续？", "卸载记录归档", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        Run("Uninstall", root, support, false);
        string cleanup = Path.Combine(support, "cleanup.ps1");
        string command = "$ErrorActionPreference='Stop'; $env:PSModulePath=Join-Path $PSHOME 'Modules'; & ([ScriptBlock]::Create([IO.File]::ReadAllText(" + Quote(cleanup) + "))) -AppRoot " + Quote(root) + " -SupportRoot " + Quote(support) + " -OwnerProcessId " + Process.GetCurrentProcess().Id;
        ProcessStartInfo start = new ProcessStartInfo(SystemShell, "-NoProfile -NonInteractive -EncodedCommand " + Encoded(command));
        start.UseShellExecute = false; start.CreateNoWindow = true; start.WindowStyle = ProcessWindowStyle.Hidden;
        start.WorkingDirectory = Path.GetTempPath();
        Process.Start(start);
    }
    static int Core(string[] args, bool sharing = false) {
        var escaped = new List<string>();
        foreach (string arg in args) { if (arg.IndexOf('"') >= 0) throw new Exception("参数中包含不支持的引号。"); escaped.Add("\"" + arg + "\""); }
        ProcessStartInfo start = new ProcessStartInfo(Path.Combine(Base, "_internal", "WeChatRecordExporter.Core.exe"), String.Join(" ", escaped));
        start.UseShellExecute = false; start.WorkingDirectory = Base;
        if (args.Length == 0) {
            start.EnvironmentVariables["RECORD_ARCHIVE_INITIALIZED_ROOT"] = Base;
            start.EnvironmentVariables["RECORD_ARCHIVE_SHARE_AVAILABLE"] = sharing ? "1" : "0";
            if(TransferTargetAvailable.HasValue)
                start.EnvironmentVariables["RECORD_ARCHIVE_TRANSFER_TARGET_AVAILABLE"] = TransferTargetAvailable.Value ? "1" : "0";
            if(ShareSetupFailure!=null)
                start.EnvironmentVariables["RECORD_ARCHIVE_SHARE_SETUP_FAILURE"] = ShareSetupFailure;
        }
        using (Process process = Process.Start(start)) {
            if (args.Length > 0) { process.WaitForExit(); return process.ExitCode; }
            return 0;
        }
    }
    [STAThread] static int Main(string[] args) {
        string resultPath = args.Length > 1 ? args[1] : null;
        bool diagnostic = args.Length > 0 && (args[0] == "--initialize-test" || args[0] == "--setup-status" || args[0] == "--uninstall-test");
        try {
            if (args.Length > 0 && args[0] == "--self-check") return Core(args);
            if (args.Length > 0 && (args[0] == "--uninstall" || args[0] == "--uninstall-test")) {
                Uninstall(diagnostic);
                if (diagnostic) File.WriteAllText(resultPath, "{\"ok\":true}");
                return 0;
            }
            if (args.Length > 0 && args[0] == "--setup-status") {
                var status = Run("Status", Base, Path.Combine(Base, "_internal", "distribution"), false);
                File.WriteAllText(resultPath, new JavaScriptSerializer().Serialize(status)); return 0;
            }
            bool sharing=false;
            using (Mutex mutex = new Mutex(false, "Local\\RecordArchive.PortableShare.Setup")) {
                if (mutex.WaitOne(0)) {
                    try { sharing=PrepareSharing(ShareCapability,()=>Initialize(diagnostic && args[0] == "--initialize-test")); }
                    finally { mutex.ReleaseMutex(); }
                } else ShareSetupFailure="initialization_busy";
            }
            if (diagnostic) { File.WriteAllText(resultPath,new JavaScriptSerializer().Serialize(new Dictionary<string,object>{{"ok",true},{"share_enabled",sharing},{"share_setup_failure",ShareSetupFailure}})); return 0; }
            return Core(new string[0],sharing);
        } catch (Exception error) {
            if (diagnostic && resultPath != null) File.WriteAllText(resultPath, new JavaScriptSerializer().Serialize(new Dictionary<string,object>{{"ok",false},{"error",error.Message}}));
            else MessageBox.Show(error.Message, "记录归档", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }
}
