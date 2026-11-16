"""命令行入口（薄壳）：python run.py [run|check|doctor|ui|teach|install-task|uninstall-task]"""
from signin.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
