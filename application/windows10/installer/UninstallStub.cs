using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("MusicHands Uninstaller")]
[assembly: AssemblyProduct("MusicHands")]
[assembly: AssemblyVersion("1.0.0.0")]

namespace MusicHandsUninstall
{
    internal static class Program
    {
        private const string UninstallRegKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicHands";

        private static void StopRunningProcesses()
        {
            foreach (Process p in Process.GetProcessesByName("MusicHands"))
            {
                try
                {
                    if (p.Id != Process.GetCurrentProcess().Id)
                    {
                        p.Kill();
                        p.WaitForExit(3000);
                    }
                }
                catch
                {
                }
            }
        }

        [STAThread]
        public static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool quiet = false;
            foreach (string a in args)
            {
                if (string.Equals(a, "/S", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(a, "/quiet", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(a, "--quiet", StringComparison.OrdinalIgnoreCase))
                {
                    quiet = true;
                }
            }

            if (!quiet)
            {
                DialogResult res = MessageBox.Show(
                    "Are you sure you want to uninstall MusicHands?",
                    "MusicHands Uninstall",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question
                );
                if (res != DialogResult.Yes)
                {
                    return 0;
                }
            }

            StopRunningProcesses();

            string installDir = null;
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallRegKey))
                {
                    if (key != null)
                    {
                        installDir = key.GetValue("InstallLocation") as string;
                    }
                }
                Registry.CurrentUser.DeleteSubKeyTree(UninstallRegKey, false);
            }
            catch
            {
            }

            if (string.IsNullOrEmpty(installDir))
            {
                installDir = Path.GetDirectoryName(Application.ExecutablePath);
            }

            try
            {
                string desktopLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "MusicHands.lnk");
                if (File.Exists(desktopLnk)) File.Delete(desktopLnk);

                string startMenuDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "MusicHands");
                if (Directory.Exists(startMenuDir)) Directory.Delete(startMenuDir, true);
            }
            catch
            {
            }

            if (!string.IsNullOrEmpty(installDir) && Directory.Exists(installDir))
            {
                string cmdArgs = "/C timeout /t 2 /nobreak > NUL & rmdir /s /q \"" + installDir + "\"";
                ProcessStartInfo psi = new ProcessStartInfo("cmd.exe", cmdArgs);
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                Process.Start(psi);
            }

            if (!quiet)
            {
                MessageBox.Show("MusicHands has been uninstalled.", "MusicHands Uninstall", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            return 0;
        }
    }
}
