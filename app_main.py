"""GUI 入口（打包成 exe 时也用它）：不带参数就开界面，带子命令就走命令行。"""
import sys

from signin import cli


def main() -> int:
    argv = sys.argv[1:]
    if argv:
        # 打包后 sys.argv[0] 是 exe 自己；命令行需要 prog 名好看一点，交给 cli.main 的 parser 处理
        return cli.main(argv)
    from signin.ui import app

    return app.main([])


if __name__ == "__main__":
    raise SystemExit(main())
