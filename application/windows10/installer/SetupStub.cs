using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using System.Drawing;
using Microsoft.Win32;

[assembly: AssemblyTitle("MusicHands Setup")]
[assembly: AssemblyProduct("MusicHands")]
[assembly: AssemblyDescription("MusicHands Windows 10 Installer")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace MusicHandsSetup
{
    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    internal class ShellLink
    {
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    internal interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cchMaxPath, out IntPtr pfd, int fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cchMaxName);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cchMaxPath);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cchMaxPath);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cchIconPath, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, int dwReserved);
        void Resolve(IntPtr hwnd, int fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    internal static class ShortcutHelper
    {
        public static void CreateShortcut(string shortcutPath, string targetPath, string workingDir, string description)
        {
            string dir = Path.GetDirectoryName(shortcutPath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }

            IShellLinkW link = (IShellLinkW)new ShellLink();
            link.SetPath(targetPath);
            link.SetWorkingDirectory(workingDir);
            link.SetDescription(description);
            link.SetIconLocation(targetPath, 0);

            IPersistFile file = (IPersistFile)link;
            file.Save(shortcutPath, false);
        }
    }

    public class InstallerForm : Form
    {
        private TextBox txtInstallDir;
        private Button btnBrowse;
        private CheckBox chkDesktopShortcut;
        private CheckBox chkStartMenuShortcut;
        private CheckBox chkInstallDriver;
        private CheckBox chkLaunchAfter;
        private ProgressBar progressBar;
        private Label lblStatus;
        private Button btnInstall;
        private Button btnCancel;
        private bool isInstalling = false;
        private bool isFinished = false;
        private string installedExePath = null;

        public InstallerForm()
        {
            Text = "MusicHands Setup";
            Size = new Size(520, 390);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Segoe UI", 9F, FontStyle.Regular);
            BackColor = Color.White;

            Label lblHeader = new Label();
            lblHeader.Text = "Install MusicHands";
            lblHeader.Font = new Font("Segoe UI", 14F, FontStyle.Bold);
            lblHeader.AutoSize = true;
            lblHeader.Location = new Point(20, 16);
            Controls.Add(lblHeader);

            Label lblSub = new Label();
            lblSub.Text = "This wizard will install MusicHands and the virtual MIDI driver on your computer.";
            lblSub.AutoSize = true;
            lblSub.Location = new Point(22, 48);
            Controls.Add(lblSub);

            Label lblDir = new Label();
            lblDir.Text = "Destination folder:";
            lblDir.AutoSize = true;
            lblDir.Location = new Point(22, 84);
            Controls.Add(lblDir);

            string defaultDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs",
                "MusicHands"
            );

            txtInstallDir = new TextBox();
            txtInstallDir.Text = defaultDir;
            txtInstallDir.Location = new Point(22, 106);
            txtInstallDir.Size = new Size(370, 24);
            Controls.Add(txtInstallDir);

            btnBrowse = new Button();
            btnBrowse.Text = "Browse...";
            btnBrowse.Location = new Point(400, 104);
            btnBrowse.Size = new Size(80, 26);
            btnBrowse.Click += OnBrowseClick;
            Controls.Add(btnBrowse);

            chkInstallDriver = new CheckBox();
            chkInstallDriver.Text = "Install virtual MIDI driver (teVirtualMIDI / loopMIDI)";
            chkInstallDriver.Checked = true;
            chkInstallDriver.AutoSize = true;
            chkInstallDriver.Location = new Point(22, 146);
            Controls.Add(chkInstallDriver);

            chkDesktopShortcut = new CheckBox();
            chkDesktopShortcut.Text = "Create a Desktop shortcut";
            chkDesktopShortcut.Checked = true;
            chkDesktopShortcut.AutoSize = true;
            chkDesktopShortcut.Location = new Point(22, 174);
            Controls.Add(chkDesktopShortcut);

            chkStartMenuShortcut = new CheckBox();
            chkStartMenuShortcut.Text = "Create a Start Menu shortcut";
            chkStartMenuShortcut.Checked = true;
            chkStartMenuShortcut.AutoSize = true;
            chkStartMenuShortcut.Location = new Point(22, 202);
            Controls.Add(chkStartMenuShortcut);

            chkLaunchAfter = new CheckBox();
            chkLaunchAfter.Text = "Launch MusicHands when installation finishes";
            chkLaunchAfter.Checked = true;
            chkLaunchAfter.AutoSize = true;
            chkLaunchAfter.Location = new Point(22, 230);
            Controls.Add(chkLaunchAfter);

            lblStatus = new Label();
            lblStatus.Text = "Ready to install.";
            lblStatus.AutoSize = false;
            lblStatus.Location = new Point(22, 266);
            lblStatus.Size = new Size(460, 20);
            Controls.Add(lblStatus);

            progressBar = new ProgressBar();
            progressBar.Location = new Point(22, 288);
            progressBar.Size = new Size(458, 20);
            progressBar.Minimum = 0;
            progressBar.Maximum = 100;
            Controls.Add(progressBar);

            btnInstall = new Button();
            btnInstall.Text = "Install";
            btnInstall.Location = new Point(304, 318);
            btnInstall.Size = new Size(84, 28);
            btnInstall.Click += OnInstallClick;
            Controls.Add(btnInstall);

            btnCancel = new Button();
            btnCancel.Text = "Cancel";
            btnCancel.Location = new Point(396, 318);
            btnCancel.Size = new Size(84, 28);
            btnCancel.Click += (s, e) => Close();
            Controls.Add(btnCancel);
        }

        private void OnBrowseClick(object sender, EventArgs e)
        {
            using (FolderBrowserDialog dlg = new FolderBrowserDialog())
            {
                dlg.SelectedPath = txtInstallDir.Text;
                dlg.Description = "Select the destination folder for MusicHands:";
                if (dlg.ShowDialog(this) == DialogResult.OK)
                {
                    txtInstallDir.Text = dlg.SelectedPath;
                }
            }
        }

        private void SetStatus(string message, int progress)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action<string, int>(SetStatus), message, progress);
                return;
            }
            lblStatus.Text = message;
            if (progress >= 0 && progress <= 100)
            {
                progressBar.Value = progress;
            }
        }

        private void OnInstallClick(object sender, EventArgs e)
        {
            if (isFinished)
            {
                if (chkLaunchAfter.Checked && !string.IsNullOrEmpty(installedExePath) && File.Exists(installedExePath))
                {
                    try
                    {
                        ProcessStartInfo psi = new ProcessStartInfo(installedExePath);
                        psi.WorkingDirectory = Path.GetDirectoryName(installedExePath);
                        psi.UseShellExecute = true;
                        Process.Start(psi);
                    }
                    catch
                    {
                    }
                }
                Close();
                return;
            }

            if (isInstalling)
                return;

            string targetDir = txtInstallDir.Text.Trim();
            if (string.IsNullOrEmpty(targetDir))
            {
                MessageBox.Show(this, "Please choose a valid installation directory.", "MusicHands Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            isInstalling = true;
            txtInstallDir.Enabled = false;
            btnBrowse.Enabled = false;
            chkInstallDriver.Enabled = false;
            chkDesktopShortcut.Enabled = false;
            chkStartMenuShortcut.Enabled = false;
            btnInstall.Enabled = false;
            btnCancel.Enabled = false;

            bool installDriver = chkInstallDriver.Checked;
            bool createDesktop = chkDesktopShortcut.Checked;
            bool createStartMenu = chkStartMenuShortcut.Checked;

            Thread worker = new Thread(() => RunInstallation(targetDir, installDriver, createDesktop, createStartMenu));
            worker.IsBackground = true;
            worker.Start();
        }

        private void RunInstallation(string targetDir, bool installDriver, bool createDesktop, bool createStartMenu)
        {
            try
            {
                SetStatus("Stopping running MusicHands processes...", 5);
                Program.StopRunningProcesses();

                SetStatus("Creating destination folder...", 10);
                if (!Directory.Exists(targetDir))
                {
                    Directory.CreateDirectory(targetDir);
                }

                SetStatus("Extracting application files...", 15);
                Assembly asm = Assembly.GetExecutingAssembly();
                using (Stream payloadStream = asm.GetManifestResourceStream("payload.zip"))
                {
                    if (payloadStream == null)
                    {
                        throw new InvalidOperationException("Embedded payload.zip resource was not found inside the installer.");
                    }

                    using (ZipArchive archive = new ZipArchive(payloadStream, ZipArchiveMode.Read))
                    {
                        int total = Math.Max(1, archive.Entries.Count);
                        int index = 0;
                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            index++;
                            string relativePath = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                            string destPath = Path.Combine(targetDir, relativePath);

                            if (string.IsNullOrEmpty(entry.Name))
                            {
                                Directory.CreateDirectory(destPath);
                                continue;
                            }

                            string parentDir = Path.GetDirectoryName(destPath);
                            if (!string.IsNullOrEmpty(parentDir) && !Directory.Exists(parentDir))
                            {
                                Directory.CreateDirectory(parentDir);
                            }

                            // Preserve existing user config files when upgrading
                            bool isUserConfig = (
                                string.Equals(relativePath, "config.json", StringComparison.OrdinalIgnoreCase) ||
                                string.Equals(relativePath, "enabled.json", StringComparison.OrdinalIgnoreCase) ||
                                string.Equals(relativePath, "camera.json", StringComparison.OrdinalIgnoreCase)
                            );
                            if (isUserConfig && File.Exists(destPath))
                            {
                                continue;
                            }

                            entry.ExtractToFile(destPath, true);

                            if (index % 15 == 0 || index == total)
                            {
                                int pct = 15 + (int)((index * 60.0) / total);
                                SetStatus("Extracting: " + entry.Name, pct);
                            }
                        }
                    }
                }

                if (installDriver)
                {
                    SetStatus("Checking / installing virtual MIDI driver...", 80);
                    Program.EnsureLoopMidiDriverInstalled(asm);
                }

                string mainExe = Path.Combine(targetDir, "MusicHands.exe");
                installedExePath = mainExe;

                SetStatus("Creating shortcuts and registering uninstaller...", 90);
                string uninstallerPath = Path.Combine(targetDir, "Uninstall.exe");

                if (createDesktop)
                {
                    string desktopLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "MusicHands.lnk");
                    ShortcutHelper.CreateShortcut(desktopLnk, mainExe, targetDir, "MusicHands Desktop Application");
                }

                if (createStartMenu)
                {
                    string startMenuLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "MusicHands", "MusicHands.lnk");
                    ShortcutHelper.CreateShortcut(startMenuLnk, mainExe, targetDir, "MusicHands Desktop Application");
                }

                Program.RegisterUninstaller(targetDir, mainExe, uninstallerPath);

                SetStatus("Installation complete!", 100);
                BeginInvoke(new Action(() =>
                {
                    isInstalling = false;
                    isFinished = true;
                    btnInstall.Text = "Finish";
                    btnInstall.Enabled = true;
                }));
            }
            catch (Exception ex)
            {
                BeginInvoke(new Action(() =>
                {
                    isInstalling = false;
                    lblStatus.Text = "Installation failed.";
                    btnInstall.Enabled = true;
                    btnCancel.Enabled = true;
                    MessageBox.Show(this, "Installation failed:\n\n" + ex.Message, "MusicHands Setup Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }));
            }
        }
    }

    internal static class Program
    {
        private const string UninstallRegKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicHands";

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern IntPtr LoadLibrary(string lpFileName);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool FreeLibrary(IntPtr hModule);

        public static bool IsDriverInstalled()
        {
            string[] names = Environment.Is64BitProcess
                ? new[] { "teVirtualMIDI64.dll", "teVirtualMIDI.dll" }
                : new[] { "teVirtualMIDI32.dll", "teVirtualMIDI.dll" };

            foreach (string name in names)
            {
                IntPtr handle = LoadLibrary(name);
                if (handle != IntPtr.Zero)
                {
                    FreeLibrary(handle);
                    return true;
                }
            }
            return false;
        }

        public static void EnsureLoopMidiDriverInstalled(Assembly asm)
        {
            if (IsDriverInstalled())
            {
                return;
            }

            using (Stream driverZipStream = asm.GetManifestResourceStream("loopMIDISetup.zip"))
            {
                if (driverZipStream == null)
                {
                    return;
                }

                string tempDir = Path.Combine(Path.GetTempPath(), "musichands_driver_" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(tempDir);
                try
                {
                    using (ZipArchive archive = new ZipArchive(driverZipStream, ZipArchiveMode.Read))
                    {
                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            if (!string.IsNullOrEmpty(entry.Name))
                            {
                                string outPath = Path.Combine(tempDir, entry.Name);
                                entry.ExtractToFile(outPath, true);
                            }
                        }
                    }

                    string[] exes = Directory.GetFiles(tempDir, "*.exe", SearchOption.AllDirectories);
                    if (exes.Length == 0)
                    {
                        return;
                    }

                    ProcessStartInfo psi = new ProcessStartInfo();
                    psi.FileName = exes[0];
                    psi.Arguments = "/install /passive /norestart";
                    psi.WorkingDirectory = Path.GetDirectoryName(exes[0]);
                    psi.UseShellExecute = true;
                    psi.Verb = "runas";

                    using (Process proc = Process.Start(psi))
                    {
                        if (proc != null)
                        {
                            proc.WaitForExit();
                        }
                    }
                }
                finally
                {
                    try { Directory.Delete(tempDir, true); } catch { }
                }
            }
        }

        public static void StopRunningProcesses()
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

        public static void RegisterUninstaller(string installDir, string mainExe, string uninstallerPath)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallRegKey))
                {
                    if (key != null)
                    {
                        key.SetValue("DisplayName", "MusicHands");
                        key.SetValue("DisplayVersion", "1.0.0");
                        key.SetValue("Publisher", "MusicHands");
                        key.SetValue("InstallLocation", installDir);
                        key.SetValue("DisplayIcon", mainExe);
                        key.SetValue("UninstallString", "\"" + uninstallerPath + "\"");
                        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    }
                }
            }
            catch
            {
            }
        }

        private static int RunUninstaller()
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

            MessageBox.Show("MusicHands has been uninstalled.", "MusicHands Uninstall", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 0;
        }

        [STAThread]
        public static int Main(string[] args)
        {
            bool isUninstall = false;
            bool isSilent = false;
            string customDir = null;

            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (string.Equals(a, "--uninstall", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(a, "/uninstall", StringComparison.OrdinalIgnoreCase))
                {
                    isUninstall = true;
                }
                else if (string.Equals(a, "/S", StringComparison.OrdinalIgnoreCase) ||
                         string.Equals(a, "/silent", StringComparison.OrdinalIgnoreCase) ||
                         string.Equals(a, "/quiet", StringComparison.OrdinalIgnoreCase))
                {
                    isSilent = true;
                }
                else if (a.StartsWith("/D=", StringComparison.OrdinalIgnoreCase))
                {
                    customDir = a.Substring(3).Trim('"');
                }
            }

            if (Path.GetFileName(Application.ExecutablePath).StartsWith("Uninstall", StringComparison.OrdinalIgnoreCase))
            {
                isUninstall = true;
            }

            if (isUninstall)
            {
                return RunUninstaller();
            }

            if (isSilent)
            {
                string targetDir = customDir ?? Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Programs",
                    "MusicHands"
                );
                StopRunningProcesses();
                Directory.CreateDirectory(targetDir);
                Assembly asm = Assembly.GetExecutingAssembly();
                using (Stream payloadStream = asm.GetManifestResourceStream("payload.zip"))
                using (ZipArchive archive = new ZipArchive(payloadStream, ZipArchiveMode.Read))
                {
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        string relativePath = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                        string destPath = Path.Combine(targetDir, relativePath);
                        if (string.IsNullOrEmpty(entry.Name))
                        {
                            Directory.CreateDirectory(destPath);
                            continue;
                        }
                        string parentDir = Path.GetDirectoryName(destPath);
                        if (!string.IsNullOrEmpty(parentDir)) Directory.CreateDirectory(parentDir);
                        entry.ExtractToFile(destPath, true);
                    }
                }
                EnsureLoopMidiDriverInstalled(asm);
                string mainExe = Path.Combine(targetDir, "MusicHands.exe");
                string uninstallerPath = Path.Combine(targetDir, "Uninstall.exe");
                RegisterUninstaller(targetDir, mainExe, uninstallerPath);
                return 0;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm());
            return 0;
        }
    }
}
