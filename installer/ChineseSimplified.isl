; BattDock Inno Setup 简体中文语言配置（UTF-8 BOM）
[LangOptions]
LanguageName=简体中文
LanguageID=$0804
LanguageCodePage=936
DialogFontName=Microsoft YaHei UI
DialogFontSize=9
WelcomeFontName=Microsoft YaHei UI
WelcomeFontSize=14
TitleFontName=Microsoft YaHei UI
TitleFontSize=24
CopyrightFontName=Microsoft YaHei UI
CopyrightFontSize=9

[Messages]
SetupAppTitle=安装程序
SetupWindowTitle=安装 - %1
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1

InformationTitle=提示
ConfirmTitle=确认
ErrorTitle=错误

SetupLdrStartupMessage=即将安装 %1，是否继续？
LdrCannotCreateTemp=无法创建临时文件，安装已中止
LdrCannotExecTemp=无法在临时目录中执行文件，安装已中止

ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=立即安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonYesToAll=全部是(&A)
ButtonNo=否(&N)
ButtonNoToAll=全部否(&O)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&R)...
ButtonWizardBrowse=浏览(&R)...
ButtonNewFolder=新建文件夹(&M)

SelectLanguageTitle=选择安装语言
SelectLanguageLabel=请选择安装过程中使用的语言。

ClickNext=单击「下一步」继续，或单击「取消」退出安装程序。
BeveledLabel=BattDock
BrowseDialogTitle=选择安装文件夹
BrowseDialogLabel=请在下方列表中选择文件夹，然后单击「确定」。
NewFolderName=新建文件夹

WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=即将把 [name/ver] 安装到您的计算机。%n%n安装无需管理员权限，支持后续软件内一键自动更新。

WizardSelectDir=选择安装位置
SelectDirDesc=您希望将 [name] 安装到哪个文件夹？
SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹中。
SelectDirBrowseLabel=单击「下一步」继续；如需更改安装路径，请单击「浏览」。
DiskSpaceGBLabel=至少需要 [gb] GB 可用磁盘空间。
DiskSpaceMBLabel=至少需要 [mb] MB 可用磁盘空间。
CannotInstallToRootDirectory=无法直接安装到磁盘根目录。
DirDoesntExist=文件夹：%n%n%1%n%n不存在，是否立即创建？
NoAccessToDir=没有权限写入所选文件夹，请选择其他位置。
InvalidPath=请输入包含盘符的完整路径（例如：C:\APP）。

WizardSelectTasks=选择附加任务
SelectTasksDesc=您希望安装程序执行哪些附加任务？
SelectTasksLabel2=请勾选安装 [name] 时需要执行的附加选项，然后单击「下一步」。

WizardReady=准备就绪
ReadyLabel1=安装程序已准备好将 [name] 安装到您的计算机。
ReadyLabel2a=单击「立即安装」开始安装，或单击「上一步」修改配置。
ReadyLabel2b=单击「立即安装」开始安装。
ReadyMemoUserInfo=用户信息：
ReadyMemoDir=目标文件夹：
ReadyMemoType=安装类型：
ReadyMemoComponents=已选组件：
ReadyMemoGroup=开始菜单文件夹：
ReadyMemoTasks=附加任务：

WizardPreparing=正在准备安装
PreparingDesc=正在准备安装 [name]，请稍候。
PreviousInstallNotCompleted=之前的安装或卸载尚未完成，请重启计算机后重试。
CannotContinue=安装无法继续，请单击「取消」退出。
ApplicationsFound=以下程序正在使用需要更新的文件，建议允许安装程序自动关闭它们。
ApplicationsFound2=以下程序正在使用需要更新的文件，建议允许安装程序自动关闭它们，安装完成后将尝试重新启动。
CloseApplications=自动关闭相关程序(&A)
DontCloseApplications=暂不关闭相关程序(&D)
ErrorCloseApplications=安装程序无法自动关闭所有占用文件的程序，请手动关闭后重试。

WizardInstalling=正在安装
InstallingLabel=正在安装 [name]，请稍候...

FinishedHeadingLabel=[name] 安装完成
FinishedLabelNoIcons=[name] 已成功安装到您的计算机。
FinishedLabel=[name] 已成功安装到您的计算机。您可以通过桌面或开始菜单快捷方式随时启动。
ClickFinish=单击「完成」退出安装向导。
FinishedRestartLabel=需要重新启动计算机以完成 [name] 的安装，是否现在重启？
FinishedRestartMessage=需要重新启动计算机以完成 [name] 的安装。%n%n是否现在重启？
ShowReadmeCheck=查看说明文档
YesRadio=是，立即重启计算机(&Y)
NoRadio=否，稍后手动重启(&N)
RunEntryExec=立即启动 %1
RunEntryShellExec=查看 %1

StatusExtractFiles=正在释放程序文件...
StatusCreateIcons=正在创建快捷方式...
StatusCreateIniEntries=正在写入配置项...
StatusCreateRegistryEntries=正在注册应用信息...
StatusRegisterFiles=正在注册文件...
StatusSavingUninstall=正在写入卸载信息...
StatusRunProgram=正在完成安装...
StatusRestartingApplications=正在重新启动程序...
StatusRollback=正在回滚更改...

UninstallNotFound=文件「%1」不存在，无法卸载。
UninstallOpenError=无法打开文件「%1」，无法卸载。
UninstallUnsupportedVer=卸载日志「%1」版本不受支持，无法卸载。
UninstallUnknownEntry=卸载日志中存在无法识别的记录（%1）。
ConfirmUninstall=确定要彻底卸载 %1 及其所有组件吗？
UninstallOnlyOnWin64=此软件仅支持在 64 位 Windows 上卸载。
OnlyAdminCanUninstall=此安装需要管理员权限才能卸载。
UninstallStatusLabel=正在从您的计算机中移除 %1，请稍候...
UninstalledAll=%1 已成功从您的计算机中移除。
UninstalledMost=%1 已基本卸载完成。%n%n部分文件未能移除，您可以稍后手动删除。
UninstalledAndNeedsRestart=需要重启计算机以完成 %1 的卸载。%n%n是否立即重启？
UninstallDataCorrupted=「%1」文件已损坏，无法卸载。

ConfirmDeleteSharedFileTitle=移除共享文件？
ConfirmDeleteSharedFile2=系统提示以下共享文件已不再被其他程序使用，是否移除？%n%n%1
SharedFileNameLabel=文件名：
SharedFileLocationLabel=位置：
WizardUninstalling=正在卸载
StatusUninstalling=正在卸载 %1...

ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。如果现在退出，软件将不会被安装。%n%n确定要退出安装吗？
ErrorCreatingDir=安装程序无法创建文件夹「%1」
ErrorTooManyFilesInDir=无法在文件夹「%1」中创建文件，文件数量过多

[CustomMessages]
AdditionalIcons=快捷方式：
CreateDesktopIcon=创建桌面快捷方式
AutoStartGroup=启动选项：
AutoStartTask=开机静默自启（后台驻留系统托盘）
LaunchProgram=立即启动 %1
RemoveUserConfigPrompt=是否同时删除 BattDock 的个人配置文件与历史设备偏好设置？%n（若计划稍后重新安装，建议选择「否」以保留配置）
