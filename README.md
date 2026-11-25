# QQ 飞车编辑器建模

这是用于 QQ 飞车地图编辑器 IDC 构建区的 Codex skill。它可以根据参考图搭建建筑、场景道具和纯构件二维人物，估算地图占用、生成可复用的原生组合卡，并从组件文件渲染正面和斜侧预览。

## 安装

在 Windows PowerShell 运行以下命令，将技能安装到当前用户的 Codex 技能目录。

```powershell
$skillBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skillDir = Join-Path $skillBase 'skills/qqspeed-editor-modeling'
git clone https://github.com/YYMY993/qqspeed-editor-modeling.git $skillDir
```

在新对话输入 `$qqspeed-editor-modeling` 即可使用。已有这个技能的用户请保留本机偏好，按现有安装方式更新。

## 验证和连接

离线制卡与校验使用 Python 3.12。运行以下自检需要在该 Python 环境中安装 NumPy 和 Pillow。

```powershell
python -X utf8 (Join-Path $skillDir 'scripts/selftest.py')
```

自检在临时目录验证生成卡片、二维构件、正面和斜侧渲染、预算超限、账号库识别以及重复安装。连接实际游戏时使用 Windows、64 位 Python 3.12、Codex CLI 和当前用户的 QQ 飞车构建区。按需启用随包的本地 MCP，安装步骤和拖放示例见[安装与自检](references/setup.md)。

建模时先确认方案与预算。占用以目标地图的放置前后读数为准。离线渲染和游戏实拍分别标注。完整流程见[技能说明](SKILL.md)，各类组件的选材和历史实测见[制作与占用实例](references/modeling-practice.md)。
