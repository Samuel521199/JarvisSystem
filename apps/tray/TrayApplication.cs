using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace Jarvis {
    public sealed class TrayApplication : ApplicationContext {
        readonly NotifyIcon icon = new NotifyIcon();
        readonly ContextMenuStrip menu = new ContextMenuStrip();
        readonly ToolStripMenuItem statusItem = new ToolStripMenuItem("正在连接…");
        readonly ToolStripMenuItem checkItem = new ToolStripMenuItem("尚未检查");
        readonly ToolStripMenuItem exitItem = new ToolStripMenuItem("退出 Jarvis");
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        readonly HttpClient client;
        readonly JavaScriptSerializer json = new JavaScriptSerializer();
        readonly Process owner;
        readonly EventWaitHandle quit, close, ready;
        readonly Dictionary<string, Icon> icons = new Dictionary<string, Icon>();
        readonly string url, instance, version, statePath;
        Task<HttpResponseMessage> pending;
        DateTime nextPoll = DateTime.MinValue;
        string state = "", label = "";
        bool exiting, disposed;

        [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr handle);

        // Code-native small-size J + north star. This is the editable icon source.
        public static Bitmap DrawIcon(int size, string state) {
            Bitmap bitmap = new Bitmap(size, size);
            using (Graphics g = Graphics.FromImage(bitmap)) {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.ScaleTransform(size / 64f, size / 64f);
                using (GraphicsPath plate = new GraphicsPath()) {
                    plate.AddArc(2,2,16,16,180,90); plate.AddArc(46,2,16,16,270,90);
                    plate.AddArc(46,46,16,16,0,90); plate.AddArc(2,46,16,16,90,90); plate.CloseFigure();
                    using (Brush navy = new SolidBrush(Color.FromArgb(22,42,66))) g.FillPath(navy,plate);
                }
                using (Pen white = new Pen(Color.White, 7)) {
                    white.StartCap = LineCap.Square; white.EndCap = LineCap.Round;
                    g.DrawLine(white, 21,19,35,19); g.DrawLine(white,31,19,31,38);
                    g.DrawArc(white, 15,30,16,20,0,180);
                }
                PointF[] star = {new PointF(47,10),new PointF(49,17),new PointF(56,19),new PointF(49,21),
                    new PointF(47,28),new PointF(45,21),new PointF(38,19),new PointF(45,17)};
                using (Brush blue = new SolidBrush(Color.FromArgb(155,214,255))) g.FillPolygon(blue,star);
                Color color = state=="standby" ? Color.FromArgb(64,201,143) : state=="working" ? Color.FromArgb(84,169,255) :
                    state=="needs_attention" ? Color.FromArgb(255,183,67) : Color.FromArgb(169,177,189);
                using (Brush badge = new SolidBrush(color)) g.FillEllipse(badge,44,44,16,16);
                using (Pen border = new Pen(Color.FromArgb(22,42,66),2)) g.DrawEllipse(border,44,44,16,16);
            }
            return bitmap;
        }

        public static string Classify(Dictionary<string,object> payload, string instance) {
            object value;
            if (!payload.TryGetValue("app",out value) || !Object.Equals(value,"Jarvis") ||
                !payload.TryGetValue("instance_id",out value) || !Object.Equals(value,instance) ||
                !payload.TryGetValue("web_online",out value) || !Object.Equals(value,true)) return "offline";
            if (!payload.TryGetValue("core_ready",out value) || !Object.Equals(value,true)) return "needs_attention";
            if (!payload.TryGetValue("assistant_state",out value)) return "needs_attention";
            return Object.Equals(value,"standby") ? "standby" : Object.Equals(value,"working") ? "working" : "needs_attention";
        }

        public TrayApplication(int port, int ownerPid, string instanceId, string appVersion, string output) {
            if (port<1 || port>65535) throw new ArgumentOutOfRangeException("port");
            instance=instanceId; version=appVersion; statePath=output; url="http://127.0.0.1:"+port+"/";
            string prefix="Local\\Jarvis.Tray."+instance+".";
            quit=EventWaitHandle.OpenExisting(prefix+"quit"); close=EventWaitHandle.OpenExisting(prefix+"close");
            ready=EventWaitHandle.OpenExisting(prefix+"ready");
            owner=Process.GetProcessById(ownerPid); IntPtr ownerHandle=owner.Handle;
            client = new HttpClient(new HttpClientHandler { UseProxy=false, AllowAutoRedirect=false });
            client.Timeout=TimeSpan.FromSeconds(1.5); client.MaxResponseContentBufferSize=16384;
            foreach (string key in new [] {"starting","standby","working","needs_attention","offline","exiting"}) {
                using (Bitmap bitmap=DrawIcon(Math.Max(16,SystemInformation.SmallIconSize.Width),key)) {
                    IntPtr handle=bitmap.GetHicon();
                    try { using (Icon temporary=Icon.FromHandle(handle)) icons[key]=(Icon)temporary.Clone(); }
                    finally { DestroyIcon(handle); }
                }
            }
            statusItem.Enabled=false; checkItem.Enabled=false;
            menu.Items.Add("Jarvis "+version).Enabled=false;
            menu.Items.Add(statusItem); menu.Items.Add(checkItem); menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("打开 Jarvis",null,delegate { OpenWindow(); });
            menu.Items.Add("立即刷新状态",null,delegate { nextPoll=DateTime.MinValue; Tick(null,EventArgs.Empty); });
            menu.Items.Add(new ToolStripSeparator()); menu.Items.Add(exitItem);
            exitItem.Click += delegate { RequestExit(); };
            icon.ContextMenuStrip=menu; icon.DoubleClick += delegate { OpenWindow(); };
            ApplyState("starting"); icon.Visible=true;
            WriteState(); ready.Set();
            timer.Interval=250; timer.Tick+=Tick; timer.Start();
        }

        void OpenWindow() {
            try { Process.Start(new ProcessStartInfo(url) { UseShellExecute=true }); }
            catch { MessageBox.Show("无法打开默认浏览器，请访问："+url,"Jarvis"); }
        }

        public void RequestExit() {
            if (owner.HasExited) { ExitThread(); return; }
            if (state=="working" && MessageBox.Show("Jarvis 仍在执行任务。退出将结束本机助手运行，是否继续？",
                "退出 Jarvis", MessageBoxButtons.YesNo, MessageBoxIcon.Question)!=DialogResult.Yes) return;
            exiting=true; exitItem.Enabled=false; ApplyState("exiting"); quit.Set();
        }

        void Tick(object sender, EventArgs args) {
            if (close.WaitOne(0)) { ExitThread(); return; }
            if (owner.HasExited) {
                if (exiting) { ExitThread(); return; }
                exitItem.Text="关闭托盘图标"; ApplyState("offline"); return;
            }
            if (exiting) return;
            if (pending!=null && pending.IsCompleted) {
                try {
                    using (HttpResponseMessage response=pending.GetAwaiter().GetResult()) {
                        response.EnsureSuccessStatusCode();
                        string body=response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
                        ApplyState(Classify(json.Deserialize<Dictionary<string,object>>(body),instance));
                    }
                } catch { ApplyState("offline"); }
                pending=null; checkItem.Text="最近检查 "+DateTime.Now.ToString("HH:mm:ss");
                nextPoll=DateTime.UtcNow.AddSeconds(2);
            }
            if (pending==null && DateTime.UtcNow>=nextPoll) pending=client.GetAsync(url+"api/status");
        }

        public void ApplyState(string next) {
            if (state==next) return;
            state=next;
            label=next=="standby" ? "待命中" : next=="working" ? "运行中" : next=="needs_attention" ? "需要处理" :
                next=="starting" ? "正在连接" : next=="exiting" ? "正在退出" : "连接中断";
            icon.Icon=icons[next]; icon.Text="Jarvis · "+label+" · "+version;
            statusItem.Text="状态："+label; WriteState();
        }

        void WriteState() {
            try {
                string output=json.Serialize(new {instance_id=instance,version=version,state=state,label=label,
                    tray_pid=Process.GetCurrentProcess().Id,owner_pid=owner.Id,icon_visible=icon.Visible,
                    changed_at=DateTime.UtcNow.ToString("o"),url=url});
                File.WriteAllText(statePath,output,new System.Text.UTF8Encoding(false));
            } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }

        protected override void ExitThreadCore() {
            timer.Stop(); icon.Visible=false; WriteState(); base.ExitThreadCore();
        }

        protected override void Dispose(bool disposing) {
            if (disposing && !disposed) {
                disposed=true; timer.Dispose(); icon.Visible=false; icon.Dispose(); menu.Dispose(); client.Dispose();
                foreach (Icon item in icons.Values) item.Dispose();
                quit.Dispose(); close.Dispose(); ready.Dispose(); owner.Dispose();
            }
            base.Dispose(disposing);
        }

        public static void Run(int port,int pid,string instance,string version,string statePath) {
            using (TrayApplication app=new TrayApplication(port,pid,instance,version,statePath)) Application.Run(app);
        }
    }
}
