# 在另一台电脑安装并验证

## 能力与条件

| 目标 | 当地需要 | 成功标志 |
|---|---|---|
| 读图鉴、拆结构、估预算 | 技能文件 | 能查到相关资产的验证状态与占用口径 |
| 离线生成、验证原生卡 | Python 3.12；生成器和校验器只用标准库 | 写出 v1/v5 的 component.json，内部引用和变换通过校验 |
| 离线渲染与封面 | 同一 Python 安装 NumPy、Pillow | 从刚生成的文件重读，得到正、斜两视图和 256 × 256 PNG |
| 加入“我的组件” | 兼容版本的 QQ 飞车 Windows 客户端、本人已确认的数字账号库 | 新卡片名称和封面出现在本人组件库 |
| MCP 读面板、微调、现场拖放 | Windows、64 位 Python 3.12、Codex CLI、本机构建区；首次安装依赖需能访问包源 | MCP 工具可发现，当前窗口和读取能力由状态返回；写入还需前台和可用权限 |

### 安装技能

将 ZIP 里的整个 `qqspeed-editor-modeling` 目录放入当前 Codex 的 `skills` 目录。默认位置是 `%USERPROFILE%\.codex\skills`，设置了 `CODEX_HOME` 时用其下的 `skills`。应只有一层同名目录，`SKILL.md` 在它的根部。复制新版本前保留自己的本地偏好与修改。在新对话输入 `$qqspeed-editor-modeling` 即可调用。也可直接把 ZIP 给自己的 Codex，请它按本页安装、自检。

以下 PowerShell 初始化本次命令用的路径。在技能目录里运行时直接取当前目录。每个输出目录选一个新的工作目录。

```powershell
$skillBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skillDir = Join-Path $skillBase 'skills/qqspeed-editor-modeling'
$py = (Get-Command python -CommandType Application | Select-Object -First 1).Source
$demoDir = Join-Path ([IO.Path]::GetTempPath()) ('qqspeed-demo-' + [guid]::NewGuid())
```

### 离线自检

提供 Python 3.12 的环境即可运行。使用自己的虚拟环境也可以，把 `$py` 指向那个环境的 python。若缺预览依赖，在该环境运行 `& $py -m pip install numpy Pillow`。

```powershell
& $py -X utf8 (Join-Path $skillDir 'scripts/selftest.py')
& $py -X utf8 (Join-Path $skillDir 'scripts/native_card.py') (Join-Path $skillDir 'assets/gate.plan.json') --output (Join-Path $demoDir 'component.json')
& $py -X utf8 (Join-Path $skillDir 'scripts/native_preview.py') (Join-Path $demoDir 'component.json') --view front --output (Join-Path $demoDir 'front.png')
& $py -X utf8 (Join-Path $skillDir 'scripts/native_preview.py') (Join-Path $demoDir 'component.json') --view angle --size 256 --output (Join-Path $demoDir 'cover.png')
& $py -X utf8 (Join-Path $skillDir 'scripts/local_group.py') (Join-Path $demoDir 'component.json') --cover (Join-Path $demoDir 'cover.png')
```

预期是八件木门廊，门洞有净空。八件按样例暂估 160，另留 20 余量。自检把安装测试写入临时模拟账号，运行后自动清理。自己的卡片制作与上架命令见 [原生组合](native-groups.md)。

### 启用现场桥接

先检查当前会话是否已经提供 `qqspeed-editor` 的三个工具。可用就直接检查编辑器，仅在安装或升级桥接时运行下面的安装程序。脚本安装到当前用户的 `%LOCALAPPDATA%\qqspeed-editor-mcp`，联网下载所需库；仅安装阶段注册此用户的 Codex MCP。以下命令在使用者同意安装的机器上运行，无需管理员权限。

```powershell
$bridge = Join-Path $skillDir 'scripts/editor_mcp'
& $py -X utf8 (Join-Path $bridge 'install_bridge.py') --check-only
& $py -X utf8 (Join-Path $bridge 'install_bridge.py')
codex mcp get qqspeed-editor
$bridgePy = Join-Path $env:LOCALAPPDATA 'qqspeed-editor-mcp/venv/Scripts/python.exe'
& $bridgePy -X utf8 (Join-Path $bridge 'verify.py')
```

`--no-register` 仅安装运行环境和程序。`--install-dir` 可指定安装位置，随后从该目录的 `venv/Scripts/python.exe` 调用工具。上面的 Python 入口可直接在限制 PowerShell 脚本的 Windows 上运行。相同名称已有不同注册时，先核对 `codex mcp get qqspeed-editor`。离线样例和本地校验可独立运行。回放识别四帧精准面板和一帧其他面板，另测过期、选错、权限、拖放中断释放和读回；`--window-replay` 可加测一个专用测试窗口。回放通过后，在有游戏和本次任务授权的机器上，先只读调用 `editor_status` 和 `read_editor`，再按本次任务范围试摆。

### 一次拖放

优先用可用的编辑器桌面工具。随包的 `card_drag.py` 也可完成一次有即时截图依据的拖放。它识别当前唯一 GAMEAPP 构建区，使用客户区像素。打开“我的组件”，找到实际卡片和空区，记录基线。命令由操作者根据刚取得的实拍运行。

```powershell
$drag = Join-Path $bridge 'card_drag.py'
$shotDir = Join-Path ([IO.Path]::GetTempPath()) ('qqspeed-drag-' + [guid]::NewGuid())
& $bridgePy -X utf8 $drag snapshot $shotDir --activate
```

查看 `$shotDir/client.png`。将当前卡片中心和安全落点分别填入 `$fromX,$fromY,$toX,$toY`。若移到卡片上会改变其外观，可先悬停卡片，用新的空目录重新获取快照。节省重复全屏截图时优先用 MCP 的具名读数；选择卡片与目标空区仍需要现场画面。

```powershell
& $bridgePy -X utf8 $drag drag $shotDir --start $fromX $fromY --end $toX $toY
```

90 秒内只可消费一次快照。程序核对目标进程、窗口边界、两处图像、遮挡和焦点，在按下鼠标前消费凭据。若已消费、窗口变化或中途失焦，先区分“未放、已放、已放待配置”。要重复放一个新实例时重新观察。鼠标命令送达仅说明手势已发出，实际放入以组或地图的读回为准。临时目录里的快照和进程数据留在本机，用完可清理。

普通权限无法向更高权限的游戏输入时，离线制作和可用的后台观察可以继续。若已有本次明确授权，可用同权限的临时执行途径仅运行本次动作，遇到 Windows 权限提示由本人确认。助手随动作结束，不保存会话控制凭据、不启动常驻输入服务。优先复用已有授权，不把安装 skill 或处理前一张地图视为提升权限的同意。
