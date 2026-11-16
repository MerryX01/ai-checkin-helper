"""sign_in —— WorkBuddy / Qoder / Trae CN / 豆包 每日自动签到。

分层：
    signin.core        与平台无关的基础设施（结果模型、HTTP、配置、日志、推送）
    signin.platforms   平台插件（一个平台一个模块，导入即注册）
    signin.services    业务编排（执行、汇总、界面与配置之间的映射）
    signin.ui          tkinter 界面（面板由注册表生成）
"""
from pathlib import Path

VERSION = "2.2.1"

# 工程根目录（config.json、logs、scripts 都相对它）
ROOT = Path(__file__).resolve().parent.parent

__all__ = ["VERSION", "ROOT"]
