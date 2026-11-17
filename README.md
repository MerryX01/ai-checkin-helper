# 每日自动签到 · Qoder / WorkBuddy / Trae CN / 豆包

**一句话：你在客户端登录一次，之后每天它就自己签到——不用填 API、不用填令牌、不用填 Cookie。**

双击 `启动界面.cmd` 就能打开界面。勾平台、选时间、点「立即签到」，剩下的交给定时任务。

---

## 它是怎么做到"不用填东西"的

电脑上装了客户端，客户端登录后会把登录凭证加密存在自己的目录里（Windows 上用 DPAPI + AES-256-GCM）。
本工程直接用 Python 把这份凭证读出来用，所以对用户来说只是"我在客户端登录过"。

| 平台 | 你只需要 | 程序从哪拿凭证 | 状态 |
|---|---|---|---|
| **WorkBuddy** | 在 WorkBuddy（客户端目录叫 CodeBuddy CN）登录一次 | `%APPDATA%\CodeBuddy CN\User\globalStorage\state.vscdb` 里的 accessToken，自动解密 | 自动签到 |
| **Qoder** | 在 Qoder 客户端登录一次 | `%APPDATA%\com.qodercn.app.stable\auth.v1.dat`，用本机主密钥解密出 token；活动接口在 `gateway.qoder.com.cn`，必须带 `Cosy-ClientType: 10` | 自动签到（+100 Credits/日） |
| **豆包** | 在豆包客户端登录一次 | `%LOCALAPPDATA%\Doubao\User Data\Profile 3\Network\Cookies`（v10 密文，自动解密成 Cookie，读时剔除过期项）→ 任务面板 + DirectClaim 奖励接口，领取后回读 `checked_in_today` 确认 | 自动签到；以平台回读为准，未确认到账不报成功 |
| **Trae CN** | 在 Trae CN 客户端登录一次 | 解开 `%APPDATA%\Trae CN\User\globalStorage\storage.json` 里的加密信封（AES-128-CBC + sha512 派生密钥），拿到 Cloud-IDE-JWT 和真实设备号；CLI 的 `~/.trae-cn/trae-jwt-token` 也能用 | 自动签到（+200 积分/日） |

Trae 的登录信息是客户端自己的加密格式，本工程用纯 Python 复刻了解密（算法来自公开实现 G57651/dsh-dual-checkin，MIT），
所以同样是「登录一次就行」，不需要令牌、不需要校准。只有在读不到登录态时，才保留「点客户端按钮」作为可选的兜底（默认关闭）。

界面右侧的「登录状态」区会实时显示是不是已经读到凭证；读不到就提示"去客户端登录一次"，不会要求你粘贴任何东西。

### 额度看板 / 用量明细

主界面操作行的 **「额度看板」** 会打开一个独立窗口，实时读取四个平台的真实额度：

| 平台 | 看板显示 | 数据来源 |
|---|---|---|
| Trae CN | 余额、总量、已用、使用率、签到权益包 | `POST /trae/api/v2/pay/ide_user_ent_usage` |
| Qoder | 附加额度余额 / 总量 / 已用、总使用率、到期 | `GET /sash/api/v2/me/usage` |
| WorkBuddy | 套餐/奖励积分分组、余额、总量、已用 | `POST /billing/meter/get-user-resource-summary` |
| 豆包 | 活动赠送额度总量、已用、到期、额度记录；平台只返回「已用 <1」时显示余额下限「≥199」，不伪造精确值 | `POST /alice/commerce/sale/subscription/quota/summary/` + `quota/records` |

- 看板只读，不会触发签到；没有返回的字段显示「—」，不猜测。
- 选中表格中的一行，下方显示该平台的额度构成/记录明细和具体数据源。
- 今天签到收益来自当天真实签到结果（界面运行或命令行运行都会写入 `logs\checkin_history.jsonl`），不会把活动奖励冒充账户余额。

命令行也可以看：

```bat
python run.py quota
python run.py quota --details
python run.py quota --only trae,qoder
```

---

## 开始用（3 步）

1. **装 Python 3**（勾选 tcl/tk）。
2. **双击 `启动界面.cmd`** —— 它会自动挑一个带 tkinter 的解释器（pyw -3 → Python312 → pythonw → py → python），
   全都不行才弹窗报错，不会"双击没反应"。
3. 在界面上勾选平台（支持多选，也可以「全选 / 全不选」）→ 点「立即签到」验证一次 → 点「注册定时任务」（默认 10:10，Qoder 的当日资格 10:00 后才放出）。

> 单独勾选：点平台卡片左侧的小方框，只切换这一家；点卡片主体只是切换右侧设置面板，不会误改勾选状态。
> 「全选 / 全不选」适合批量操作，日常只跑几家时逐个点方框即可。

### 打包好的 exe

`dist\签到助手.exe` 是单文件、免装 Python 的版本（PyInstaller 打包，窗口程序，不弹黑窗）：

1. 把 `dist\` 里的 `签到助手.exe`（和 `使用说明.txt`）拷给对方；
2. 对方双击 exe，在客户端登录一次，界面「登录状态」显示已登录后勾平台、点「立即签到」；
3. 点「注册定时任务」即可每天自动跑——计划任务里登记的是 exe 自己的路径。

exe 的配置和日志都放在 exe 同目录（`config.json`、`logs\checkin.log`），无需管理员权限。
新版 exe 在 GitHub 仓库的 Releases（正式发版）或 Actions 构建产物（每次推送的最新构建）里下载。

### 命令行用法

```bat
python run.py run                :: 真正签到（全部已勾选的平台）
python run.py run --only qoder   :: 只跑一个平台
python run.py run --dry-run      :: 只打印将要发出的请求，不真签
python run.py quota              :: 查看四平台额度 / 用量
python run.py quota --details    :: 同时看额度构成和记录
python run.py check              :: 配置体检，不发请求
python run.py ui                 :: 打开界面
python run.py teach trae         :: 校准 Trae 的签到按钮坐标
python run.py install-task --time 10:10
python run.py uninstall-task
```

---

## 工程结构（桌面根目录下的完整项目）

```
sign_in\
├─ 启动界面.cmd          双击入口（ASCII + CRLF，调 scripts\launch_ui.ps1）
├─ gui_app.py            界面薄壳（3 行）
├─ run.py                命令行入口
├─ config.json           你的配置（界面里改，别手写）
├─ config.example.json   默认配置样例（由 DEFAULTS 生成）
├─ pyproject.toml        工程元数据 / 测试入口
├─ CHANGELOG.md
├─ README.md
├─ docs\
│  ├─ architecture.png        分层架构图（scripts\draw_architecture.py 生成）
│  ├─ ARCHITECTURE.md         分层与数据流
│  ├─ PRINCIPLES_AND_COMPARISON.md  原理 / 封号风险 / 与 dsh-checkin-all 对比
│  ├─ ADDING_A_PLATFORM.md    加一个平台要改什么（只改一个文件）
│  └─ TROUBLESHOOTING.md      常见故障
├─ signin\
│  ├─ core\              基础设施：models / http / config / logging / notify / aesgcm / secrets
│  ├─ platforms\         平台插件：base.py 协议 + registry.py 注册表 + 四个平台
│  ├─ services\          runner（执行编排）/ quota（额度汇总）/ history（签到历史）/ settings（表单与校验）
│  ├─ ui\app.py          主界面（面板由注册表动态生成）
│  ├─ ui\quota.py        额度看板窗口（余额、用量、明细）
│  ├─ apps.py            客户端路径探测与启动
│  ├─ gui.py             窗口定位 + 点击（纯 ctypes，零第三方依赖）
│  └─ cli.py             命令行
├─ scripts\
│  ├─ launch_ui.ps1      界面启动器（探测解释器、失败弹窗、写日志）
│  ├─ run_daily.ps1      定时任务实际执行的脚本
│  ├─ run_hidden.vbs     无窗口拉起（计划任务用）
│  └─ install_task.ps1   注册/删除计划任务
├─ tests\                155 个单测
├─ logs\                 checkin.log / checkin_history.jsonl / ui_launch.log / checkin_console.log
└─ dist\                 发布包：签到助手.exe + 使用说明.txt + config.example.json
```

依赖：**只用标准库**。不需要 pip install 任何东西（`cryptography` 只在开发期用来和自研 AES 实现做对拍）。

---

## 注意

- 凭证始终留在本机，程序只读不写、不上传。
- 定时任务用 `wscript.exe` 拉起 `run_hidden.vbs`，运行时不会弹黑窗口。
- 想清掉登录态？在对应客户端里退出登录即可，程序下一次就会提示"去客户端登录一次"。

##  学习交流分享

   <img width="178" height="226" alt="f2c4149e6261d746d84a98a7ce60f60d" src="https://github.com/user-attachments/assets/7948f180-1b13-4b6e-a487-68e3714c92ba" />

