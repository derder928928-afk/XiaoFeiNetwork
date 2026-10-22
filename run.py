"""打包入口：冻结后由此启动主程序。"""
import sys

from xiaofei.app import main

if __name__ == "__main__":
    raise SystemExit(main())
