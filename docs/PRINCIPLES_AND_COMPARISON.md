# 原理、封号风险与开源项目对比（v2.2.2）

> 本文对应 2026-11-17 的真实接口探测与代码修复。架构图见 `docs/architecture.png`；
> 同图可用 `py -3 scripts/draw_architecture.py` 重新生成。

---

## 一、这个脚本到底怎么工作

### 一句话

它不保存你的账号密码，也不模拟键盘去点客户端；它只是**借用客户端自己已经保存的登录凭证**，
按平台自己用的接口发一次请求，然后**回读状态确认真的到账**。确认不了，就不写“成功”。

### 生活化类比

把客户端想成一家你已经办过会员卡的超市：

- 你第一次在客户端登录，相当于办卡并拿到一张门禁卡（Cookie / token）。
- 脚本不复制你的身份证，也不替你设密码；它只是从你家里的卡包（客户端数据目录）里
  取出这张门禁卡，去服务台说一句“我来领今天的会员礼”。
- 服务台说“放你柜子里了”，脚本不会立刻回去邀功；它会再查一次柜子（任务面板/签到状态），
  看到东西真的在里面，才写“签到成功”。
- 如果服务台说“今天没有这个活动”“你这个卡不是个人会员”，脚本就如实写“无资格/没有活动”，
  不会把“受理了”当成“到账了”。

### 一次签到的数据流

```text
主界面「立即签到」 / Windows 任务计划
  → services.runner.run_all(cfg, only, dry_run)
      → 按注册顺序挑出启用的平台
          → spec.run(client, section)
              → section 没凭证时，先 spec.login_state() 读本机客户端登录态
              → 调平台自己的 status / claim 接口
              → 回读任务面板或签到状态，确认今天真的签了
          → CheckinResult(status, credits, message)
  → 结果写 logs/checkin_history.jsonl
  → 主界面刷新四张卡片；额度看板用同一份结果补「今日签到」
```

### 额度看板的数据流（只读，不签到）

```text
额度看板 / `python run.py quota`
  → services.quota.collect(cfg, results=今天的签到结果)
      → 每个平台调 spec.quota() 读自己的余额/用量接口
          → Trae：ide_user_ent_usage
          → Qoder：sash/api/v2/me/usage
          → WorkBuddy：get-user-resource-summary + checkin-activity-status
          → 豆包：quota/summary + quota/records
      → QuotaSnapshot(balance, total, used, percent, today_earned, today_text, details)
  → 七列表格 + 选中行的额度构成/记录/数据源
```

### 登录态是怎么读的（只读，不写回）

| 平台 | 本机位置 | 读取方式 |
|---|---|---|
| Trae CN | `%APPDATA%\<Trae 应用>\User\globalStorage\storage.json`，或 `~/.trae-cn/trae-jwt-token` | 解密 `iCubeAuthInfo` 信封 / 直接读 JWT |
| Qoder | `%APPDATA%\com.qodercn.app.stable\auth.v1.dat` | DPAPI + `v10` AES-256-GCM 解密 |
| WorkBuddy | `%APPDATA%\CodeBuddy CN\User\globalStorage\state.vscdb` | 读 SQLite `ItemTable` 里的加密 Buffer |
| 豆包 | `%LOCALAPPDATA%\Doubao\User Data\Profile 3\Network\Cookies` | 读 Chromium Cookies 库并解密 `v10` 密文 |

脚本只读这些文件，不修改客户端数据，不保存账号密码。

### 为什么能扩展

平台适配层是一个注册表：新增平台只要写一个 `PlatformSpec`（`login_state`、`run`、`quota`、`fields`、`actions`），
界面面板、`config.json` 默认值、环境变量映射、CLI 的 `--only` 取值都会自动生成。
`platforms` 不 import `ui`，`core` 不 import `platforms`，依赖只向下。

---

## 二、本次修复的真实证据

### 豆包「没成功」的真正原因

真实探测（2026-11-17，使用本机客户端当前登录 Cookie）：

- Cookie 同时带 `feishu_dpop_keypair`、`LARK_SUITE_ACCESS_TOKEN`；`has_biz_token=false`、`is_staff_user=false`。
  → 这是**飞书/企业（工作版）登录态**，不是个人版豆包账号。
- 任务面板仍能看到 `daily_signin` 任务：`checked_in_today=false`、`continuous_days=0`、
  `last_checkin_date=2026-10-28`、`reward_amount=200`。
- 直接领取 `POST /alice/ug/campaign/item/reward/claim/`：HTTP 200，`code=0`，
  但 `data.biz_error.code=3`、message「领取结果确认中，请稍后重试」；回读任务面板仍是 `checked_in_today=false`。
- 气泡签到 `POST /alice/ug/campaign/landing/checkin`：HTTP 200，`data=null`、
  `code=710010702`、msg「系统错误」。

结论：**这个账号没有个人版「天天领额度」的领取资格**，平台不会真的发放；
不是网络问题、不是 Cookie 过期、也不是脚本“卡住了”。

修复后：

- 识别到飞书/企业登录态，只探一次气泡签到，不再反复打领取接口、也不再写「已受理，等待到账」。
- 主界面明确显示：没有可领取的签到活动 + 上次成功签到日期 2026-10-28 + 换个人豆包账号的方法。
- 额度看板「今日签到」列显示「无资格」，不再显示「—」。

> 想继续领豆包每日 200 额度：在 [doubao.com](https://www.doubao.com) 网页版登录**个人账号**，
> 再用这个账号登录一次豆包客户端，脚本下次就会用新的个人 Cookie。
> 企业/工作版账号本身没有这个玩法，换脚本版本也变不出来。

### 额度看板三处「—」的处理

| 位置 | 修复前 | 修复后 | 依据 |
|---|---|---|---|
| WorkBuddy 今日签到 | `—` | `+100` | 新接入 `/billing/meter/checkin-activity-status`，读 `today_credit=100`、`streak_days=17` |
| 豆包余额 | `—` | `≥199` | 平台只返回总量 200、已用 `<1`；余额必然 >199，显示数学下限，保留「已用 <1」，不伪造精确值 |
| 豆包今日签到 | `—` | `无资格` | 飞书/企业登录态没有个人版签到资格 |

WorkBuddy 实测：

```json
{"active": true, "today_checked_in": true, "streak_days": 17,
 "daily_credit": 100, "today_credit": 100, "total_credits": 1700,
 "activity_name": "Buddy应用", "end_time": "2026-12-31 23:59:59"}
```

豆包额度实测：

```json
{"feature_group": "doubao_activity_reward_quota",
 "total_amount": "200", "used_amount": "<1",
 "less_than_one_percent": true, "used_percent": 0,
 "end_time": 1795759534787}
```

### 改完后的真实输出

```text
平台        余额      总量      已用      使用率  今日签到  状态
Trae CN     702.5     1,200     497.5     41.5%   —         正常
Qoder       203       1,900     1,697     89.0%   —         正常
WorkBuddy   494.45    3,012     2,517.55  83.6%   +100      正常
豆包        ≥199      200       <1        0.0%    无资格    正常
```

全量测试 `150 tests OK`；`compileall` 退出码 0；界面自检 `UI-OK panels=4 cards=4 fields=8` / `DASH-OK rows=4`。

---

## 三、会不会封号？

### 结论

**不能承诺“绝对不会”，但按现在的用法，风险是低的、可控的；不是零风险。**

平台是否处罚，最终看平台自己的用户协议和风控策略，任何第三方脚本都无法替你保证。
能控制的是“让请求尽量像正常客户端，而不是像刷子”。

### 风险分级

| 行为 | 风险 | 说明 |
|---|---|---|
| 每天只签一次、单账号 | 低 | 和你在客户端手动点一次几乎一样；接口是客户端自己在用的 |
| 读取本机客户端已有登录态 | 低 | 不碰密码、不写回客户端、不复制到别的机器 |
| 固定设备标识（由账号派生） | 低 | 不随机换设备、不伪装成新设备 |
| 高频重试 / 反复领取 | 中 | 会被看成异常流量；本项目对“无活动/已签”直接停手 |
| 多账号批量、共享 Cookie | 中高 | 平台通常明确限制；本项目目前是单账号/平台 |
| 代理/VPN 切换 IP、改设备指纹 | 高 | 容易触发风控；本项目不做 |
| 绕过活动资格、伪造请求参数 | 高 | 可能直接封禁；本项目不做，遇到无资格就如实报 |

### 针对豆包的特殊说明

- 当前账号是飞书/企业登录态，个人版签到活动领不了；旧代码会反复打领取接口，
  既拿不到额度，也增加异常请求。新代码只探一次气泡签到就停，反而**降低**了风险。
- 想领 200 额度，请换个人豆包账号；不要拿企业号硬刷。

### 使用建议

1. 一个平台一个账号，每天最多一次；不要手动再连点。
2. 不要把 `config.json`、Cookie、token 发给别人，也不要用别人的登录态。
3. 不要挂代理/加速器频繁切换 IP；不要改设备指纹。
4. 平台提示“活动结束/无资格”就停，不要反复试。
5. 如果平台协议明确禁止自动化，以平台条款为准；本工具不提供绕过手段。

---

## 四、和 GitHub `AIcivilization/dsh-checkin-all` 的区别

参考项目：<https://github.com/AIcivilization/dsh-checkin-all>（Node.js，DeepSeek Harness 插件）。
以下对比基于它的 README 与 `lib/providers/doubao.js`、`lib/providers/buddy.js` 源码。

### 定位不同

| 维度 | 本项目（sign_in 2.2.2） | dsh-checkin-all |
|---|---|---|
| 形态 | Windows 桌面程序：Tkinter 主界面 + 额度看板 + CLI + PyInstaller exe | DSH 插件：对话页里的签到卡片 + npm 分发 |
| 语言/运行时 | Python 3，只用标准库 | Node.js，依赖 DSH 运行时 |
| 平台数 | 4：Trae CN / Qoder / WorkBuddy / 豆包 | 9：MiniMax Code、WPS 灵犀、百度 DuMate、AStudio、Qoder、Trae、豆包、华为 CodeArts、腾讯 WorkBuddy + DIY |
| 多账号 | 当前一平台一份凭证 | 每个服务支持多账号，逐个签、分别记账 |
| 自定义服务 | 需要写 `PlatformSpec` 代码 | 面板粘贴 JSON 定义，不用改代码 |
| 额度看板 | 独立七列表格 + 选中行额度构成/记录/数据源 | 卡片显示积分/连续天数，没有同等的独立额度看板 |
| 自动运行 | Windows 任务计划 + `run_daily.ps1` | 插件内置调度；也支持 crontab |
| 发布 | GitHub Actions 构建 exe + Release | npm 包 / DSH 插件市场 |
| 测试 | 150 个 unittest | README 标注 124 passing |

### 协议实现上的差异（重点）

| 平台 | 本项目 | dsh-checkin-all |
|---|---|---|
| 豆包 | 先走 `item/reward/claim`（真实按钮路径），失败再走 `landing/checkin` 兜底；识别飞书/企业登录态 | 只走 `landing/checkin`；用 `710010702` 判“没有可领活动”；同样按北京时间算今天 |
| WorkBuddy | `daily-checkin` + 新增 `checkin-activity-status` 回读，拿 `today_credit`、`streak_days` | `checkin-activity-status` + `daily-checkin` + `get-user-resource`；用状态预判已签 |
| Trae | 解 `storage.json` 加密信封 / CLI JWT | 解本机 Trae 登录（storage.json 加密信封或 `trae-jwt-token`） |
| Qoder | 读 `auth.v1.dat`，`Cosy-ClientType` 头，活动 list → claim | 读本机 Qoder App 登录，或面板填 PAT；`jobToken/exchange` → campaigns → claim |
| 确认到账 | 豆包回读 `checked_in_today`；WorkBuddy 回读 `today_checked_in` | 以接口 outcome 为准，区分 claimed / already / no_task |

### 谁更适合什么

- **只想在 Windows 上双击就用、还要看四个平台余额/用量明细**：本项目更直接。
- **DSH 用户、要 9 个平台、多账号、DIY 新服务**：dsh-checkin-all 更成熟。
- **想二次开发**：本项目是 Python + 标准库 + 注册表，改一个文件就能加平台；
  dsh-checkin-all 是 Node.js provider + JSON 自定义，适合不想写代码的人。

### 可以借鉴的地方

1. 多账号：`accounts[]` 逐个签、汇总时任一成功即成功。
2. 失败退避：连续失败按 1/2/4/8/16/32 分钟拉长重试，失败 6 次当天停手。
3. 时区统一按北京时间，避免本机时区导致的重复签/连续天数错乱。
4. WorkBuddy 先用状态接口判断已签，再决定是否打领取接口（本项目已接入状态回读）。
5. 豆包用 `710010702` 作为“无活动”的明确信号（本项目已用于企业登录态判断）。

---

## 五、后续建议（按优先级）

1. **豆包换个人账号**：这是当前唯一能让豆包每日 200 额度真正到账的办法。
2. **多账号支持**：`config.json` 的 `accounts[]` + 逐个签 + 汇总；这是参考项目最强的一块。
3. **退避策略**：失败 1/2/4/8 分钟重试，连续失败当天停手，减少异常流量。
4. **统一时区**：所有平台按北京时间判断“今天”，避免本机时区变化。
5. **GitHub 发布链路**：当前本地 commit/tag 已就绪，但 `gh` 未登录、无 remote；登录后建私密仓库并推送即可让 Actions 产出 Release。
