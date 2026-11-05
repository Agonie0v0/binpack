---
name: 通用 NAS 镜像打包工具
description: 简约、克制的通用打包工作台候选视觉系统
colors:
  page: "#f7f8fa"
  paper: "#fff"
  ink: "#25272d"
  secondary: "#686d78"
  line: "#e8eaef"
  soft: "#f4f5f8"
  accent: "#4b5cca"
  success: "#39705a"
  preview-surface: "#fafbfc"
  placeholder: "#6b7280"
  focus: "#a0ace9"
  error: "#a33942"
typography:
  display:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif'
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-1.1px"
  title:
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.6
  body:
    fontSize: "13px"
    lineHeight: 1.7
  label:
    fontSize: "12px"
    fontWeight: 500
  code:
    fontFamily: '"Cascadia Code", Consolas, monospace'
    fontWeight: 400
rounded:
  workbench: "18px"
  workbench-mobile: "15px"
  upload: "11px"
  control: "8px"
  chip: "5px"
spacing:
  field-gap: "18px"
  section-gap: "20px"
  page-gutter: "36px"
  mobile-gutter: "20px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    height: "44px"
    padding: "0 20px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "43px"
    padding: "0 12px"
  workbench:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.workbench}"
---

# Design System: 通用 NAS 镜像打包工具

## Overview

**候选系统，待用户反馈；不是已批准的最终视觉规范。** 本文记录当前代码原型，依据 `design/index.html`、`design/studio.css`、`design/studio.js`，并对照桌面和手机截图。用户已确认通用版、美观、简约、高级、先看效果；具体配色与构图仍为设计提案。

认证扩展沿用同一系统，依据 `design/auth-brief.md`、`auth.css`、登录/初始化/账号页面及认证脚本；构图对照 `login-desktop.jpg`、`login-mobile.jpg`、`setup-mobile.jpg`、`account-desktop.jpg`、`account-mobile.jpg`。账号密码登录、文件上传、隔离帮助分析、Docker 构建、归档下载与可选本机导入均已接入真实服务端。工作台最新构图见 `workbench-desktop.png` 和 `workbench-mobile.png`，截图为未连接 Docker 的本地测试状态。用户要求登录页同样美观、简约、高级；本扩展不改变候选视觉状态。

**Creative North Star: "安静的 NAS 工作台"**（对现有原型的描述）。用留白、精确对齐和轻边界组织操作；主任务集中在一个工作面，预览辅助判断，历史记录降低权重。

**Key Characteristics:**

- 通用二进制入口，无任何程序专属模板。
- 石墨色主操作、少量蓝色互动提示、浅色材料层次。
- 进度与下载对应实际任务；连接状态和识别依据在影响操作的位置展示。

## Colors

Primary 使用石墨色 `ink` 承载正文、主按钮和当前导航；蓝色 `accent` 用于选择文件、拖入状态和输入光标。Neutral 使用 `page`、`paper`、`preview-surface` 区分页面、工作面和预览，`line` 划分层次，`secondary` 承载辅助文字。

`success` 仅表示文件就绪和实际任务完成；错误使用 `error` 并配文字说明。占位文字采用 `placeholder`，不可再降低透明度。焦点使用独立的 `focus` 色。

## Typography

中文系统无衬线字体与操作系统保持一致。标题采用 display，手机缩为 26px、字距 −0.8px；分区标题采用 title。输入正文 13px，标签 12px，辅助文字通常 11px；手机部分辅助文字为 10px。镜像引用和文件名使用 code，预览镜像引用桌面 18px、手机 17px。

这些数值记录当前原型，不应据此扩大微小文字的使用范围。文件名与镜像引用允许任意位置换行，避免撑宽容器。

认证页面标题为 28px，手机为 25px；登录与初始化输入、提交按钮高 46px，账号页输入高 44px。认证卡片副说明允许占满可用宽度（`max-width:none`），不继承工作台手机标题说明的 28ch 限制，避免初始化说明尾字孤行。

## Layout

桌面容器最大宽度 1168px，左右内边距使用 page-gutter，可用内容宽度 1096px。工作面表单与预览比例为 1.55:1；表单内边距 31px 34px 29px，预览为 31px 30px 26px。镜像名与标签保留双列，高级设置默认折叠，历史使用下方列表。

- ≥1450px：工作面比例 1.6:1，上传区由 214px 增至 232px，内部留白略增。
- ≤800px：页面边距 26px，工作面比例 1.4:1；隐藏高级设置的补充摘要和右侧小标签。
- ≤620px：页面边距使用 mobile-gutter；表单、预览按顺序单列，分隔线由竖向改为横向；上传区 200px，主按钮全宽。工作台与记录页的页头分两行，第二行保留创建镜像与打包记录导航；历史操作换行排列，保留下载、导入和清理入口。镜像名、标签及端口、目录仍为双列。

登录与首次初始化在页头、页脚之间居中，面板分别宽 420px、460px，并以 `max-width:100%` 适配窄屏；沿用工作面圆角、白底和淡阴影。登录面板内边距为 39px 38px 30px。账号页容器最大宽 824px，白色面板内保留最大宽 400px 的单列密码表单。

认证手机规则（≤620px）：主体左右边距 20px、卡片内边距 31px 25px 27px、圆角 15px；字段顺序不变，账号页保存按钮全宽。工作台账号菜单保留头像、截断的账号名与箭头，控制整体宽度。≤360px 时认证主体左右边距为 16px，隐藏页头辅助文字；使用自然页面滚动，不固定表单或裁切长内容。

## Elevation & Depth

以底色和细边界表达层次。工作面仅使用极淡阴影（`0 12px 40px #30394c06`），输入框为 `0 1px 2px #20283803`；避免将辅助区升级为同等权重的浮起卡片。

## Shapes

工作面、上传区、输入与按钮、状态标签分别使用 frontmatter 的圆角角色；手机工作面切换为 workbench-mobile。边框通常 1px，上传空态为虚线，选择文件后为实线。图标为圆端描边，常规 20px、描边 1.65px；仅用于动作或文件识别。

## Components

- **主按钮**：石墨色；悬停背景 `#41444c`；禁用背景 `#eceef2`、文字 `#747984`。未选文件、未连接 Docker 或实际任务进行中禁用。
- **输入与上传**：输入边框 `#dfe2e8`，悬停 `#b9bfcb`；上传悬停、焦点或拖入时为蓝边与 `#f5f7fe` 底。原生文件输入覆盖上传区。统一键盘焦点为 3px outline、4px offset；保留原生表单校验与错误文字。
- **导航与折叠**：当前导航为深色文字和底部 2px 线；高级设置使用原生 details/summary，展开时箭头旋转。帮助与历史详情使用明确的展开状态。
- **预览与状态**：镜像名、标签和基础环境随输入更新。等待、识别、构建、导入、完成和失败均以文字表达。状态和进度由服务端任务返回；仅识别成功不代表程序业务运行通过。
- **历史**：位于独立的 `/history` 页面，首页仅保留创建表单及当前结果。导航链接切换真实页面，当前页使用 `aria-current="page"`。从持久化任务读取，按时间倒序展示；进行中的任务自动刷新，加载失败保留已有记录并允许手动重试。提供实际归档、Compose 和 SHA256 下载，以及导入和清理；上传缓存清理和清理边界说明一并位于记录页。记录页辅助文字与操作最小 12px。
- **项目地址**：工作台、记录页和账号页右上角提供与帮助图标一致的 GitHub 图标入口，40px 高点击区、可见键盘焦点和可访问名称；在新窗口打开项目仓库。

颜色和箭头过渡为 180ms；减少动态效果偏好关闭过渡与平滑滚动。进度由真实任务阶段更新，不使用定时模拟成功。

### 认证扩展

- **登录与初始化**：账号、密码单列；可选择保持登录 7 天。首次使用才展示设置入口，凭容器日志中的一次性初始化凭证创建单一管理员；初始化完成后不再开放创建。账号规则和密码长度通过字段旁说明展示。忘记密码展开终端重置说明，不虚构在线找回流程。
- **密码字段与提交状态**：显隐按钮位于字段右侧，保留标签、原生自动填充、`aria-pressed` 和随状态变化的可访问名称。提交前保留原生校验；提交时禁用按钮并显示“正在登录…”“正在创建账号…”或“正在保存…”，失败恢复可操作状态。登录/初始化失败清空密码，修改密码失败清空当前密码。
- **反馈**：错误与连接失败使用表单内中文文字，认证请求统一处理网络和响应解析异常；不将代理 HTML 或原始英文异常直接作为表单反馈。消息区预留高度以减少跳动；密码已更新的提示使用现有 success 色。登录过期返回登录页并明确提示。
- **账号管理与退出**：工作台页头使用方圆首字头像、账号名和箭头组成单一点击面，下拉菜单补充身份与操作图标；手机缩短账号名宽度。菜单提供账号设置与退出；账号页展示当前管理员及当前密码、新密码、确认密码。修改成功后所有设备退出，本设备返回登录页显示更新提示。退出期间禁用入口，失败提供重试文字。菜单支持外部点击与 Escape 关闭；浏览器标签统一使用包裹图标和中文页面标题。

## Do's and Don'ts

- **Do** 保留单一主工作面、输入顺序、轻量预览与真实空态。
- **Do** 展示识别依据与不确定结果；静态 ELF 分析和隔离帮助分析不等于业务运行验证。
- **Do** 以当前代码为 token 依据；截图用于构图对照。
- **Don't** 增加 VoHive 或任何程序专属模板、虚构成功记录、性能数字或能力承诺。
- **Don't** 从任意数字猜测端口、替用户设置必填配置，或覆盖程序原生配置和 TLS 行为。
- **Don't** 将本候选系统或内部审阅通过视为用户已批准最终视觉方向。
