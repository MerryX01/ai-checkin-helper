# 常见故障

## 双击没反应 / 没窗口

先看 `logs\ui_launch.log`（每次启动都会追加一行原因）。

| 日志里出现 | 含义 | 处理 |
|---|---|---|
| `已启动：pyw -3 gui_app.py` | 正常启动 | 窗口可能被全屏浏览器挡住：窗口已置顶 1.2 秒，实在找不到就看任务栏 |
| `跳过：… 没有可用的 tkinter`（全部跳过） | 解释器缺少 tcl/tk | 装官方 Python 3（勾选 tcl/tk），或用 `启动界面.cmd` 重新跑一次 |
| `没有找到带 tkinter 的 Python，界面无法启动` | 同上的最终结论 | 会弹窗户提示；命令行仍可用 `python run.py run` |

判断某个解释器行不行，唯一标准是它能不能真的建 Tcl 解释器（`import tkinter` 成功不算）：

```bat
"C:\...\python.exe" -c "import tkinter;tkinter.Tcl()"
```

本机注：PATH 上的 `python` 是精简运行时，`import tkinter` 能过但 `tkinter.Tcl()` 报 `Can't find a usable init.tcl`，所以启动器优先挑 `pyw -3`。

## 界面能开，但「登录状态」显示未登录

| 平台 | 检查顺序 |
|---|---|
| Qoder | 客户端是否真的登录过（打开 Qoder 看右上角）；`%APPDATA%\com.qodercn.app.stable\auth.v1.dat` 是否存在 |
| WorkBuddy | 客户端是 **CodeBuddy CN**（`%APPDATA%\CodeBuddy CN`）；退出重登一次再点「刷新」 |
| Trae | 显示「未登录」才需要处理：确认 Trae CN 客户端登录过；CLI 用户看 `~/.trae-cn/trae-jwt-token` 是否存在 |
| 豆包 | 读 `%LOCALAPPDATA%\Doubao\User Data\Profile 3\Network\Cookies`（Default 被客户端锁住时自动跳过）；提示「没有可领取的活动」说明平台活动本身未开放，不是读取失败 |

点界面上的「刷新」会重新读一次；凭证是只读的，程序不会改客户端任何文件。

## 额度看板

| 显示 | 原因 | 处理 |
|---|---|---|
| `需登录` | 该平台登录态没读到，或额度接口返回 401/403 | 在对应客户端登录一次，回主界面点「刷新」，再看板点「刷新全部」 |
| `读取失败` | 额度接口网络/业务错误 | 看该平台下方明细里的数据源与错误；确认客户端能正常打开用量页 |
| 余额/总量是「—」 | 平台没有在该接口返回这个字段 | 不猜测；以平台自己的用量页为准 |
| 今日签到「—」 | 今天还没跑签到，或该平台没返回签到积分数 | 先点「立即签到」；历史记录写在 `logs\checkin_history.jsonl` |

## 签到失败

| 提示 | 原因 | 处理 |
|---|---|---|
| `登录已失效（HTTP 401）` | 客户端里退出/换号了，旧令牌失效 | 打开客户端重新登录一次 |
| `今日已签` | 今天已经签过，幂等跳过 | 正常，不用管 |
| Trae：`设备号不匹配 / 9004、9074` | 走的是 `x-device-id` 与令牌不配套 | 用客户端自动读到的登录态重试（设备号取自 `iCubeAuthInfo://icube-dc:*`） |
| Trae：`未登录` | 客户端没登录，或登录信息格式又改版 | 打开 Trae CN 登录一次；仍不行就看 `logs\checkin.log` 里的「格式不认识」提示 |
| `HTTP 403` | 接口拒绝（多为令牌无效或地区/权限限制） | 先确认客户端里能正常用该功能 |

完整日志在 `logs\checkin.log`；定时任务那次的标准输出在 `logs\checkin_console.log`。

## 定时任务没跑

```bat
schtasks /Query /TN SignInDailyCheckin /FO LIST
```

- `未注册`：界面点「注册定时任务」，或 `python run.py install-task --time 10:10`。
- 已注册但没执行：看 `logs\checkin_console.log` 有没有新的时间戳；没有就是任务没被触发（电脑睡眠/注销）。
- 想删掉：界面点「移除」，或 `python run.py uninstall-task`。

## 配置坏了

`config.json` 解析失败会直接报 `ConfigError`（带路径）。恢复办法：

1. 备份现有文件；
2. 把 `config.example.json` 复制成 `config.json`（里面是全部默认值）；
3. 重新在界面里勾选平台。

配置是"深合并"的：缺字段不会报错，会自动补默认值，所以手改少一两个键通常没事。
