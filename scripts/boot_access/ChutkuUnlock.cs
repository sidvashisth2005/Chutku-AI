// Chutku lock-screen helper (owner 2026-11-07): after a boot, or while the laptop is locked, the owner sees the
// Windows sign-in screen on the phone and can tap it, type the password and press Enter. Nothing more.
//
// Why a separate program: the sign-in screen lives on the "Winlogon" secure desktop, which only SYSTEM can see or
// type on. Chutku stays a normal, non-admin program; this helper is compiled by scripts\setup_boot_access.ps1 into
// C:\ProgramData\ChutkuBoot (only administrators can change it) and started at boot by a SYSTEM task.
//
//   watch   SYSTEM, session 0 (the boot task): makes this boot's key and keeps one "screen" helper running on the
//           Winlogon desktop of whatever session owns the laptop's screen.
//   screen  SYSTEM, on winsta0\winlogon: a tiny web page on 127.0.0.1 (published to the owner's tailnet only, by
//           `tailscale serve --https=8443`). Every call needs: Host == this laptop's tailnet name, Tailscale-User-Login
//           == the owner, and this boot's key (it arrives in the Telegram link).
//   gate    prints what the gate sees (for checks).
//
// The boundary (fails closed): screen pictures and input only while the sign-in/lock screen is up, meaning the input
// desktop is Winlogon, LogonUI.exe runs in this session and no UAC prompt (consent.exe) is open. Then it can do
// only what someone at the keyboard can do there. After sign-in it shows nothing and types nothing (Chutku's own
// phone remote takes over), and it can never answer a UAC prompt. It also lives on the Winlogon desktop, so Windows
// itself drops its input whenever the normal desktop is in front. Typed text is never logged.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

static class ChutkuUnlock
{
    static readonly string Dir = AppDomain.CurrentDomain.BaseDirectory;
    const int MaxWidth = 1280;

    static int Main(string[] args)
    {
        string mode = args.Length > 0 ? args[0] : "";
        try
        {
            if (mode == "watch") return Watch();
            if (mode == "screen") return Screen();
            if (mode == "gate") { Console.WriteLine(GateJson()); return 0; }
        }
        catch (Exception e) { Log(mode + " stopped: " + e); return 1; }
        Console.Error.WriteLine("usage: ChutkuUnlock.exe watch|screen|gate");
        return 2;
    }

    static void Log(string text)
    {
        try
        {
            string path = Path.Combine(Dir, "unlock.log");
            if (File.Exists(path) && new FileInfo(path).Length > 1000000) File.Delete(path);
            File.AppendAllText(path, DateTime.Now.ToString("s") + " " + text + Environment.NewLine);
        }
        catch (Exception) { }
    }

    // ---- watch: SYSTEM, session 0 ------------------------------------------------------------------------------
    static int Watch()
    {
        byte[] raw = new byte[32];
        using (var rng = new RNGCryptoServiceProvider()) rng.GetBytes(raw);
        File.WriteAllText(Path.Combine(Dir, "key.txt"), BitConverter.ToString(raw).Replace("-", "").ToLowerInvariant());
        Process child = null;
        uint childSession = uint.MaxValue;
        while (true)
        {
            uint session = WTSGetActiveConsoleSessionId();
            bool alive = child != null && !child.HasExited;
            if (session != uint.MaxValue && (!alive || session != childSession))
            {
                if (alive) { try { child.Kill(); child.WaitForExit(5000); } catch (Exception) { } }
                try { child = StartInSession(session); childSession = session; Log("screen helper started in session " + session); }
                catch (Exception e) { child = null; Log("could not start the screen helper: " + e.Message); }
                Thread.Sleep(10000);   // a helper that keeps failing is retried slowly
            }
            Thread.Sleep(2000);
        }
    }

    static Process StartInSession(uint session)
    {
        IntPtr token, dup;
        if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ALL_ACCESS, out token)) throw new Win32Exception();
        try { if (!DuplicateTokenEx(token, TOKEN_ALL_ACCESS, IntPtr.Zero, 2, 1, out dup)) throw new Win32Exception(); }
        finally { CloseHandle(token); }
        try
        {
            if (!SetTokenInformation(dup, 12 /* TokenSessionId */, ref session, 4)) throw new Win32Exception();
            var si = new STARTUPINFO();
            si.cb = Marshal.SizeOf(si);
            si.lpDesktop = @"winsta0\winlogon";
            string exe = Process.GetCurrentProcess().MainModule.FileName;
            PROCESS_INFORMATION pi;
            if (!CreateProcessAsUser(dup, exe, "\"" + exe + "\" screen", IntPtr.Zero, IntPtr.Zero, false,
                    0x08000000 /* CREATE_NO_WINDOW */, IntPtr.Zero, Dir, ref si, out pi)) throw new Win32Exception();
            CloseHandle(pi.hThread);
            try { return Process.GetProcessById(pi.dwProcessId); }
            finally { CloseHandle(pi.hProcess); }
        }
        finally { CloseHandle(dup); }
    }

    // ---- the gate ----------------------------------------------------------------------------------------------
    static string InputDesktop()
    {
        IntPtr desk = OpenInputDesktop(0, false, 0x0001 /* DESKTOP_READOBJECTS */);
        if (desk == IntPtr.Zero) return "";   // not readable: treated as "not the sign-in screen"
        try
        {
            var name = new StringBuilder(256);
            uint needed;
            return GetUserObjectInformation(desk, 2 /* UOI_NAME */, name, (uint)name.Capacity * 2, out needed) ? name.ToString() : "";
        }
        finally { CloseDesktop(desk); }
    }

    static bool RunsHere(string image)
    {
        int session = Process.GetCurrentProcess().SessionId;
        foreach (var p in Process.GetProcessesByName(image)) { if (p.SessionId == session) return true; }
        return false;
    }

    // null when the sign-in/lock screen is up; otherwise what the phone is told
    static string Closed()
    {
        if (!string.Equals(InputDesktop(), "Winlogon", StringComparison.OrdinalIgnoreCase)) return "unlocked";
        if (RunsHere("consent")) return "A Windows permission prompt is open: answer it at the laptop.";
        if (!RunsHere("LogonUI")) return "This is not the sign-in screen.";
        return null;
    }

    static string GateJson()
    {
        return new JavaScriptSerializer().Serialize(new Dictionary<string, object> {
            { "desktop", InputDesktop() }, { "logonui", RunsHere("LogonUI") }, { "consent", RunsHere("consent") },
            { "open", Closed() == null } });
    }

    // ---- screen: SYSTEM, on the Winlogon desktop ---------------------------------------------------------------
    static int Screen()
    {
        SetProcessDPIAware();
        var cfg = (Dictionary<string, object>)new JavaScriptSerializer().DeserializeObject(
            File.ReadAllText(Path.Combine(Dir, "config.json")));
        string host = cfg["host"] + ":" + cfg["unlock_https_port"], login = (string)cfg["login"];
        string key = File.ReadAllText(Path.Combine(Dir, "key.txt")).Trim();
        if (key.Length < 32 || string.IsNullOrEmpty(login)) throw new InvalidOperationException("no key or no owner login");
        var listener = new TcpListener(IPAddress.Loopback, Convert.ToInt32(cfg["unlock_port"]));
        listener.Start();
        Log("listening on 127.0.0.1:" + cfg["unlock_port"]);
        while (true)
        {
            using (TcpClient client = listener.AcceptTcpClient())
            {
                client.ReceiveTimeout = client.SendTimeout = 5000;
                try { Serve(client.GetStream(), host, login, key); }
                catch (Exception e) { Log("request failed: " + e.Message); }
            }
        }
    }

    static void Serve(NetworkStream stream, string host, string login, string key)
    {
        var head = new List<byte>();
        while (head.Count < 16384)
        {
            int b = stream.ReadByte();
            if (b < 0) return;
            head.Add((byte)b);
            int n = head.Count;
            if (n >= 4 && head[n - 4] == 13 && head[n - 3] == 10 && head[n - 2] == 13 && head[n - 1] == 10) break;
        }
        string[] lines = Encoding.ASCII.GetString(head.ToArray()).Split(new[] { "\r\n" }, StringSplitOptions.None);
        string[] first = lines[0].Split(' ');
        if (first.Length < 2) { Reply(stream, 400, "Bad request"); return; }
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 1; i < lines.Length; i++)
        {
            int colon = lines[i].IndexOf(':');
            if (colon > 0) headers[lines[i].Substring(0, colon).Trim()] = lines[i].Substring(colon + 1).Trim();
        }
        string method = first[0], target = first[1], path = target.Split('?')[0];
        var query = new Dictionary<string, string>();
        if (target.Contains("?"))
            foreach (string pair in target.Substring(target.IndexOf('?') + 1).Split('&'))
            {
                string[] kv = pair.Split(new[] { '=' }, 2);
                if (kv.Length == 2) query[kv[0]] = Uri.UnescapeDataString(kv[1]);
            }
        string value;
        int length = headers.TryGetValue("Content-Length", out value) ? int.Parse(value) : 0;
        if (length < 0 || length > 4096) { Reply(stream, 413, "Too long"); return; }
        byte[] body = new byte[length];
        for (int read = 0; read < length; )
        {
            int got = stream.Read(body, read, length - read);
            if (got <= 0) return;
            read += got;
        }

        // 1. the owner's tailnet, through `tailscale serve` on this laptop's name (Funnel requests have no login)
        if (!Same(headers, "Host", host) || !Same(headers, "Tailscale-User-Login", login)) { Reply(stream, 403, "Not allowed."); return; }
        if (method == "GET" && path == "/") { Reply(stream, 200, "text/html; charset=utf-8", Encoding.UTF8.GetBytes(Page)); return; }
        // 2. this boot's key, from the Telegram link
        string given;
        if (!headers.TryGetValue("X-Chutku-Key", out given) || !FixedTimeEquals(given, key))
        { Reply(stream, 401, "This link is old: use the newest 'Laptop is ON' message on Telegram."); return; }
        SetThreadExecutionState(0x00000001 | 0x00000002);   // ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED: stay awake while in use
        // 3. only while the sign-in/lock screen is up
        string closed = Closed();
        if (closed != null) { Reply(stream, 409, closed); return; }
        if (method == "GET" && path == "/api/frame") { Reply(stream, 200, "image/jpeg", Frame()); return; }
        if (method == "POST" && path == "/api/click")
        {
            Click(double.Parse(query["x"], System.Globalization.CultureInfo.InvariantCulture),
                  double.Parse(query["y"], System.Globalization.CultureInfo.InvariantCulture));
            Reply(stream, 200, "ok"); return;
        }
        if (method == "POST" && path == "/api/text") { Type(Encoding.UTF8.GetString(body)); Reply(stream, 200, "ok"); return; }
        if (method == "POST" && path == "/api/key" && query.ContainsKey("name") && Keys.ContainsKey(query["name"]))
        { Press(Keys[query["name"]]); Reply(stream, 200, "ok"); return; }
        Reply(stream, 404, "Not found");
    }

    static bool Same(Dictionary<string, string> headers, string name, string expected)
    {
        string value;
        return headers.TryGetValue(name, out value) && string.Equals(value, expected, StringComparison.OrdinalIgnoreCase);
    }

    static bool FixedTimeEquals(string a, string b)
    {
        if (a.Length != b.Length) return false;
        int diff = 0;
        for (int i = 0; i < a.Length; i++) diff |= a[i] ^ b[i];
        return diff == 0;
    }

    static void Reply(Stream s, int code, string text) { Reply(s, code, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes(text)); }

    static void Reply(Stream s, int code, string type, byte[] body)
    {
        byte[] head = Encoding.ASCII.GetBytes("HTTP/1.1 " + code + " " + (code == 200 ? "OK" : "Refused") + "\r\nContent-Type: " + type +
            "\r\nContent-Length: " + body.Length + "\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n" +
            "Referrer-Policy: no-referrer\r\nConnection: close\r\n\r\n");
        s.Write(head, 0, head.Length);
        s.Write(body, 0, body.Length);
    }

    // ---- picture and input (primary screen: the sign-in box is there) ------------------------------------------
    static byte[] Frame()
    {
        int w = GetSystemMetrics(0), h = GetSystemMetrics(1);
        using (var shot = new Bitmap(w, h))
        {
            using (var g = Graphics.FromImage(shot)) g.CopyFromScreen(0, 0, 0, 0, shot.Size);
            double scale = Math.Min(1.0, (double)MaxWidth / w);
            using (var small = new Bitmap(shot, (int)(w * scale), (int)(h * scale)))
            using (var jpeg = new MemoryStream())
            {
                var codec = Array.Find(ImageCodecInfo.GetImageEncoders(), c => c.MimeType == "image/jpeg");
                var quality = new EncoderParameters(1);
                quality.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 70L);
                small.Save(jpeg, codec, quality);
                return jpeg.ToArray();
            }
        }
    }

    static void Click(double fx, double fy)
    {
        int w = GetSystemMetrics(0), h = GetSystemMetrics(1);
        SetCursorPos((int)(Math.Max(0, Math.Min(1, fx)) * (w - 1)), (int)(Math.Max(0, Math.Min(1, fy)) * (h - 1)));
        Send(new[] { Mouse(0x0002 /* LEFTDOWN */), Mouse(0x0004 /* LEFTUP */) });
    }

    static readonly Dictionary<string, ushort> Keys = new Dictionary<string, ushort> {
        { "enter", 0x0D }, { "backspace", 0x08 }, { "escape", 0x1B }, { "space", 0x20 }, { "tab", 0x09 } };

    static void Press(ushort vk) { Send(new[] { Key(vk, 0, 0), Key(vk, 0, 0x0002 /* KEYUP */) }); }

    static void Type(string text)
    {
        var inputs = new List<INPUT>();
        foreach (char c in text.Length > 256 ? text.Substring(0, 256) : text)
        {
            short scan = VkKeyScan(c);
            if (scan == -1)   // not on the keyboard layout: send the character itself
            {
                inputs.Add(Key(0, c, 0x0004 /* UNICODE */));
                inputs.Add(Key(0, c, 0x0004 | 0x0002));
                continue;
            }
            ushort vk = (ushort)(scan & 0xFF);
            var mods = new List<ushort>();
            if ((scan & 0x100) != 0) mods.Add(0x10);   // Shift
            if ((scan & 0x200) != 0) mods.Add(0x11);   // Ctrl
            if ((scan & 0x400) != 0) mods.Add(0x12);   // Alt
            foreach (ushort m in mods) inputs.Add(Key(m, 0, 0));
            inputs.Add(Key(vk, 0, 0));
            inputs.Add(Key(vk, 0, 0x0002));
            for (int i = mods.Count - 1; i >= 0; i--) inputs.Add(Key(mods[i], 0, 0x0002));
        }
        Send(inputs.ToArray());
    }

    static INPUT Mouse(uint flags) { var i = new INPUT { type = 0 }; i.u.mi.dwFlags = flags; return i; }

    static INPUT Key(ushort vk, ushort unicode, uint flags)
    {
        var i = new INPUT { type = 1 };
        i.u.ki.wVk = vk;
        i.u.ki.wScan = (flags & 0x0004) != 0 ? unicode : (ushort)MapVirtualKey(vk, 0);
        i.u.ki.dwFlags = flags;
        return i;
    }

    static void Send(INPUT[] inputs)
    {
        if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT))) != inputs.Length) throw new Win32Exception();
    }

    // ---- the phone page ----------------------------------------------------------------------------------------
    const string Page = @"<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>Chutku: sign in</title>
<style>body{margin:0;font:16px system-ui,sans-serif;background:#111;color:#eee}main{max-width:900px;margin:auto;padding:12px}
#s{margin:8px 0;color:#9cf}img{width:100%;border:1px solid #333;touch-action:manipulation;display:block}
form,nav{display:flex;gap:8px;margin-top:10px}input{flex:1;font-size:18px;padding:10px;background:#222;color:#eee;border:1px solid #444;border-radius:6px}
button{font-size:16px;padding:10px 14px;background:#2a6;color:#fff;border:0;border-radius:6px}nav button{flex:1;background:#333}a{color:#9cf}</style></head>
<body><main><div id=s>Connecting...</div><img id=i alt='Laptop sign-in screen (tap to click)'>
<form id=f><input id=p type=password autocomplete=off placeholder='Password or PIN'><button>Sign in</button></form>
<nav><button data-k=space>Space</button><button data-k=backspace>&#9003;</button><button data-k=escape>Esc</button><button data-k=enter>Enter</button></nav>
<p style='color:#888;font-size:13px'>Tap the picture to click there. Sign in types the password, then presses Enter.</p></main>
<script>
const m=location.hash.match(/k=([0-9a-f]+)/);if(m){sessionStorage.setItem('k',m[1]);history.replaceState(null,'',location.pathname)}
const k=sessionStorage.getItem('k')||'',s=document.getElementById('s'),i=document.getElementById('i');
const api=(p,o={})=>fetch(p,Object.assign(o,{headers:{'X-Chutku-Key':k}}));
async function tick(){try{const r=await api('/api/frame');
if(r.ok){const u=URL.createObjectURL(await r.blob()),old=i.src;i.src=u;if(old)URL.revokeObjectURL(old);s.textContent='Laptop sign-in screen'}
else{const t=await r.text();if(t=='unlocked'){s.innerHTML='Signed in. Chutku starts in a moment: <a href=""https://'+location.hostname+'/"">open the phone remote</a>';i.removeAttribute('src')}else s.textContent=t}}
catch(e){s.textContent='Laptop not reachable right now.'}setTimeout(tick,500)}
i.onclick=e=>{const b=i.getBoundingClientRect();api('/api/click?x='+((e.clientX-b.left)/b.width).toFixed(4)+'&y='+((e.clientY-b.top)/b.height).toFixed(4),{method:'POST'})};
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const p=document.getElementById('p');
await api('/api/text',{method:'POST',body:p.value});p.value='';api('/api/key?name=enter',{method:'POST'})};
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>api('/api/key?name='+b.dataset.k,{method:'POST'}));
k?tick():s.textContent='Open this page from the Telegram link.';
</script></body></html>";

    // ---- Win32 -------------------------------------------------------------------------------------------------
    const uint TOKEN_ALL_ACCESS = 0xF01FF;

    [StructLayout(LayoutKind.Sequential)] struct INPUT { public uint type; public InputUnion u; }
    [StructLayout(LayoutKind.Explicit)] struct InputUnion { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT { public int dx, dy; public uint mouseData, dwFlags, time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr dwExtraInfo; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct STARTUPINFO
    {
        public int cb; public string lpReserved, lpDesktop, lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)] struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }

    [DllImport("kernel32.dll")] static extern uint WTSGetActiveConsoleSessionId();
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll")] static extern uint SetThreadExecutionState(uint flags);
    [DllImport("advapi32.dll", SetLastError = true)] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool DuplicateTokenEx(IntPtr token, uint access, IntPtr attributes, int level, int type, out IntPtr result);
    [DllImport("advapi32.dll", SetLastError = true)] static extern bool SetTokenInformation(IntPtr token, int cls, ref uint value, int length);
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool CreateProcessAsUser(IntPtr token, string app, string cmd, IntPtr pa, IntPtr ta, bool inherit, uint flags,
        IntPtr env, string dir, ref STARTUPINFO si, out PROCESS_INFORMATION pi);
    [DllImport("user32.dll", SetLastError = true)] static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr desk);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern bool GetUserObjectInformation(IntPtr obj, int index, StringBuilder info, uint length, out uint needed);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint count, INPUT[] inputs, int size);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern short VkKeyScan(char c);
    [DllImport("user32.dll")] static extern uint MapVirtualKey(uint code, uint type);
}
