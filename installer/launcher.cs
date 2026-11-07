// W3: Chutku.exe, the app's launcher. Built by scripts/build_release.py with the .NET Framework csc.exe that ships
// with Windows (no SDK needed):  csc /target:winexe /win32icon:chutku.ico /out:Chutku.exe launcher.cs
//
// - One Chutku per Windows user: the first launch holds a named mutex for as long as Chutku runs; a second launch
//   only opens the window of the running one (`-m chutku.cli open`).
// - It starts <app>\python\pythonw.exe -m chutku.guard with CHUTKU_HOME=%LOCALAPPDATA%\Chutku and no window.
// - Arguments: --background starts without opening the window (the sign-in task); --stop stops the running
//   Chutku (`-m chutku.cli control stop`); --doctor runs the health check and returns its exit code (installer test).
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;

[assembly: AssemblyTitle("Chutku")]
[assembly: AssemblyProduct("Chutku")]
[assembly: AssemblyDescription("Chutku voice assistant")]
[assembly: AssemblyCompany("Chutku")]
[assembly: AssemblyCopyright("MIT licence")]
[assembly: AssemblyVersion("0.0.0.0")]
[assembly: AssemblyFileVersion("0.0.0.0")]

static class Launcher
{
    static string AppFolder()
    {
        return Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    }

    static string Home()
    {
        string configured = Environment.GetEnvironmentVariable("CHUTKU_HOME");
        if (!string.IsNullOrEmpty(configured)) return configured;
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Chutku");
    }

    static Process Run(string arguments, bool wait)
    {
        string app = AppFolder();
        string python = Path.Combine(app, "python", "pythonw.exe");
        if (!File.Exists(python))
        {
            System.Windows.Forms.MessageBox.Show("Chutku is damaged (python\\pythonw.exe is missing). Install it again.",
                                                 "Chutku");
            Environment.Exit(2);
        }
        string home = Home();
        Directory.CreateDirectory(home);
        var start = new ProcessStartInfo(python, arguments)
        {
            WorkingDirectory = app,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        start.EnvironmentVariables["CHUTKU_HOME"] = home;
        start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";   // the app folder is never written to
        Process process = Process.Start(start);
        if (wait) process.WaitForExit();
        return process;
    }

    [STAThread]
    static int Main(string[] args)
    {
        string command = args.Length > 0 ? args[0].ToLowerInvariant() : "";
        if (command == "--stop") return Run("-m chutku.cli control stop", true).ExitCode;
        if (command == "--doctor") return Run("-m chutku.cli doctor", true).ExitCode;
        bool first;
        using (var running = new Mutex(true, "Local\\Chutku.Launcher", out first))
        {
            if (!first)
            {
                Run("-m chutku.cli open", true);   // already running: show its window
                return 0;
            }
            Process guard = Run(command == "--background" ? "-m chutku.guard" : "-m chutku.guard --open", false);
            guard.WaitForExit();                     // the mutex is held while Chutku runs
            return guard.ExitCode;
        }
    }
}
