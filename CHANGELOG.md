# 变更记录

## 2.2.2（2026-11-17）

### 修复「豆包没成功」的误导提示（2026-11-17 二次修正）

- **2026-11-17 复盘修正**：进一步实测确认本机豆包登录态其实是**个人账号**（额度接口回「个人订阅/免费体验」，历史签到记录正常），之前的「飞书/企业登录态」结论是把**过期的 Cookie 残留**当成了证据——10-28 点过一次「免费用豆包工作」后，`LARK_SUITE_ACCESS_TOKEN`（11-04 已过期）、`LARK_SUITE_DPOP`（10-28 已过期）、`feishu_dpop_keypair`（永不过期的密钥残留）一直留在 Cookies 库里，脚本照单全收才误判。
- 现在**读 Cookie 时按浏览器行为剔除过期项**（`_expired()`），过期的 LARK 残留既不进请求头也不再触发误判；`is_work_account()` 不再把 `feishu_dpop_keypair` 当企业号依据，只认有效的 `LARK_SUITE_ACCESS_TOKEN` / `LARK_SUITE_DPOP` / `has_biz_token=true`。
- 保留对**真**企业登录态的识别（飞书 SSO 账号领不了个人版签到）：只探一次气泡签到，明确说明「没有可领取的签到活动 + 上次成功签到日期 + 换个人账号的方法」。
- **客户端占用登录数据时给出准确提示**：豆包客户端运行时独占 Cookies 库（实测 `WinError 32/13`），之前误报「先去登录一次」；现在重试 3 次，仍占用则提示「完全退出豆包客户端（含托盘）后重试」。
- **「确认中」文案改诚实**：实测领取接口受理（code 0）后平台反复回 `biz_error.code=3`「领取结果确认中」，重试多次、换真实 device_id 均不到账；不再引导「过几分钟再点一次」，改为说明实情并建议在豆包客户端 UI 里手动签一次验证。
- 全量测试 155 个通过。

### 修复额度看板「三处 —」

- **WorkBuddy 今日签到**：接入 `/billing/meter/checkin-activity-status`，读 `today_credit` / `daily_credit` / `streak_days`；今日签到显示 `+100`，明细补「连续签到 / 本周签到 / 活动截止」。
- **豆包余额**：平台只回「已用 `<1`」时，按数学下限显示 `≥199`，同时保留 `已用 <1`，不再空白；仍然不伪造精确余额。
- **豆包今日签到**：飞书/企业登录态显示「无资格」，已签但接口没返回积分时显示「已签」，均不冒充成功金额。
- 新增 `QuotaSnapshot.today_text`，额度明细里对「无资格 / 已签 / 需登录 / 失败」给出人话解释。
- 签到成功后回读 WorkBuddy 状态确认到账；状态读不到时不再把 HTTP 200 包装成「签到成功」。
- 全量测试 150 个通过。

## 2.2.1（2026-11-16）

### 修复「只能全选/全不选」

- 左侧平台小方框之前点击只读取当前值、没有取反，导致单点无效果；现在 `_toggle_enabled` 先翻转再同步配置。
- 新增 `settings.toggle_platform()` 纯逻辑和回归测试；真实控件点击验证：只勾 Trae + Qoder 时，WorkBuddy/豆包正确变为「未启用」。
- 界面提示补充：点小方框单独勾选，点卡片主体只切换设置面板。

### GitHub / exe 迭代

- 增加 `.github/workflows/build-exe.yml`：tag `v*` 自动测试、编译、构建 exe，并创建 Release 附件；也支持手动触发下载 artifact。
- 增加 `scripts/release.ps1`：一条命令同步版本号、跑测试、编译、构建、提交和打标签，`-Push` 可直接推送到 GitHub。
- `dist\签到助手.exe`、`build\`、`config.json`、`logs\` 不进入 git，避免把本机凭证或二进制中间产物提交。
- 全量测试 138 个。

## 2.2.0（2026-11-16）

### 新增「额度看板 / 用量明细」

- 新增 `QuotaSnapshot` 与 `PlatformSpec.quota` 可选回调；四个平台各实现只读额度查询：
  - Qoder：`GET /sash/api/v2/me/usage`，解析 `addOnQuota.total/used/remaining/percentage`。
  - Trae CN：`POST /trae/api/v2/pay/ide_user_ent_usage`，解析 `total_balance`、`usage_summary`、权益包。
  - WorkBuddy：`POST /billing/meter/get-user-resource-summary`，解析 `TotalCredits` 与 `CreditGroups`。
  - 豆包：`POST /alice/commerce/sale/subscription/quota/summary/` + `/alice/ug/campaign/quota/records/`，
    解析活动赠送额度与额度记录。
- 新增主界面「额度看板」窗口：余额、总量、已用、使用率、今日签到、状态一张表；选中平台后在下方看额度构成/记录/数据源。
- 新增 `python run.py quota [--details] [--only ...]` 命令行入口。
- 新增 `logs\checkin_history.jsonl`：记录每天真实签到结果，看板用它稳住「今日签到收益」，不把活动奖励当余额。
- 新增 `tests/test_quota.py`（14 例）与 `tests/test_history.py`（4 例）；全量 137 tests OK。
- 真机看板实测：Trae 602.5 / 1,100（已用 497.5，45.2%）；Qoder 203 / 1,900（已用 1,697，平台返回 89.0%）；
  WorkBuddy 394.45 / 2,912（已用 2,517.55，86.5%）；豆包活动赠送总量 200、已用 `<1`（平台未返回精确剩余，余额显示「—」）。
- `dist\签到助手.exe` 重建为 2.2.0。

## 2.1.2（2026-11-16）

### 豆包：从「拉起客户端」改成真实读取 + 真实领取

- `login_state()` 从 `%LOCALAPPDATA%\Doubao\User Data\Profile 3\Network\Cookies` 读登录 Cookie：
  Chromium v10 密文用本机 `Local State` 主密钥解密，剥掉 32 字节域哈希前缀，再过滤非 ASCII 值。
  `Default\Network\Cookies` 被运行中的豆包独占锁住时，会自动跳过，不阻塞签到。
- 新增真实协议：`POST /alice/ug/campaign/v3/detail/` 读任务面板；`daily_signin` 是 DirectClaim，
  走任务面板同款 `POST /alice/ug/campaign/item/reward/claim/`（`campaign_group_code` + `campaign_item_code`），
  气泡接口 `/alice/ug/campaign/landing/checkin` 作为兜底；领取后**回读任务面板**确认 `checked_in_today=true`，
  确认不了就按未到账上报。
- 三种结果分开报：领取成功（+额度）/ 今日已签 / 当前没有可领取活动或平台仍在「确认中」（SKIPPED）；
  登录失效（710012001）提示重新登录，绝不把"拉起客户端"或空活动当成功。
- 真机结果（2026-11-16）：登录态与任务面板读取成功（`checked_in_today=false`、`reward=400`、
  上次签到 `2026-10-28`）；任务奖励接口受理后返回 `biz_error:3 领取结果确认中`，连续回读仍未到账；
  `Local State` 里该活动 `phase=settled`——平台端当天确实没有完成发奖，程序如实报「跳过 / 未确认到账」。
- 新增 `tests/test_doubao.py`（7 个用例）；旧「启动即签到」契约的测试同步改写，全量 119 tests OK。

## 2.1.1（2026-11-16）

### 修复 Qoder「假成功」

- 真实活动接口是 `https://gateway.qoder.com.cn/sash/api/v1/me/campaigns`，并且必须带
  `Cosy-ClientType: 10`；之前的代码打的是 `openapi.qoder.com.cn`，也缺少这个头，接口返回空活动列表，
  被误判成「今日已签」。
- 解析改为识别真实字段：`claimStatus`（CLAIMABLE / CLAIMED）+ `actionType`（CLAIM_BENEFIT）+ `benefit.amount`，
  不再用不存在的 `status/type`。
- 领取接口 `POST .../campaigns/{campaignId}/claim`，校验返回 `status=CLAIMED`；`replayed=true` 按幂等已领处理。
- 三种结果分开报：「已领取 100 Credits」「今日已领 100 Credits（已到账）」「活动还没放出，10:00 后再试」，
  不再把空列表当成成功。
- 真机验证：领取成功，账户余额 103 → 203 Credits（+100，有效期 30 天）。
- 新增 `tests/test_qoder.py`（8 个用例）覆盖真实响应结构、请求头、幂等与假成功回归。

## 2.1.0（2026-11-16）

### Trae 也能"登录一次就行"

- 新增 `signin/platforms/trae.py` 的登录态读取：
  - 桌面客户端 `storage.json` 的 `iCubeAuthInfo://icube.cloudide` 加密信封：sha512 派生 + AES-128-CBC 解密，校验 64 字节摘要后取出 `token` / `userId`；
    `iCubeAuthInfo://icube-dc:*` 的 key 名就是真实设备号（`x-device-id`）。
  - CLI 登录文件 `~/.trae-cn/trae-jwt-token`、`~/.trae/trae-jwt-token` 作为备用。
  - 多份登录按「有设备号优先 → 令牌最长」挑选，界面上显示 `…账号尾号`。
- `signin/core/aesgcm.py` 扩展为通用 AES：新增 AES-128 密钥扩展、解密块、`cbc_decrypt`（NIST 向量已验证）。
- Trae 签到改走 `checkin_credits/status` + `claim`，请求头补齐客户端同款字段；真机签到成功 +200 积分。
- 「点客户端按钮」降级为默认关闭的兜底项，不再要求校准。

### 打包与分发

- 新增 `app_main.py`：无参数开界面，带参数走命令行；PyInstaller 打成 `dist\签到助手.exe`（单文件、窗口程序、免 Python）。
- `config.ROOT` 兼容 frozen：exe 模式下配置/日志落在 exe 同目录；日志的相对路径也按工程根解析，从别处启动不会乱跑。
- `install-task` 在 exe 模式下直接用 `schtasks` 注册指向 exe 的任务，不再依赖 `scripts\`。
- `dist\` 附带 `使用说明.txt` 与 `config.example.json`。

### 界面

- 左侧新增「全选 / 全不选」，一次勾多个平台批量签到。

## 2.0.0（2026-11-16）

### 核心变化：从"填凭证"改成"登录一次就行"

- 新增 `signin/core/secrets.py`：DPAPI 解保护 + Chromium `v10` AES-GCM 解密 + `state.vscdb` secret 读取。
- 新增 `signin/core/aesgcm.py`：纯 Python AES-256-GCM（只解密），运行时不再依赖 `cryptography`。
- Qoder / WorkBuddy 改为**自动读取本机客户端登录态**，界面上不再有令牌 / Cookie 输入框；读不到才提示"去客户端登录一次"。
- Trae CN 的令牌 / 设备号降级为「显示高级项」里的高级设置，默认走客户端点击；点击实现改为纯 `ctypes`（去掉 pyautogui 依赖）。
- 界面新增「登录状态」区块（实时显示已登录身份 + 刷新按钮）与「显示高级项」开关。

### 工程结构

- 重构为四层包：`core` / `platforms` / `services` / `ui`，平台由注册表驱动，新增平台只写一个模块。
- 新增 `docs/ARCHITECTURE.md`、`docs/ADDING_A_PLATFORM.md`、`docs/TROUBLESHOOTING.md`、`pyproject.toml`。

### 托盘/启动链路

- `scripts/launch_ui.ps1` 修掉探测 bug（`Start-Process -ArgumentList` 不加引号会把 `-c` 的代码拆散，导致"明明有 tkinter 却判没有"）；
  改为写临时探测脚本 + `Start-Process -Wait`，候选 `pyw -3` → `Python312\pythonw.exe` → `pythonw` → `py` → `python`。
- 双击 `启动界面.cmd` 全链路实测通过（日志出现"已启动：pyw -3 gui_app.py"且窗口真的出现）。

### 验证

- 单测 93 例全绿（新增 `tests/test_aesgcm.py`、`tests/test_login.py`）。
- `python -m compileall` 退出 0；`py -3 gui_app.py --selftest` 输出 `UI-OK panels=4 cards=4 scale=2.0 fields=7`。
- 真机签到：WorkBuddy 签到成功；Qoder 读取凭证成功、当天返回"今日已签"。

## 1.0.0

- 四平台签到 + 命令行 + 图形界面 + Windows 定时任务脚本。
