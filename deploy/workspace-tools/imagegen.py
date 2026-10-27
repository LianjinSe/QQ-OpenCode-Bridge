#!/usr/bin/env python3
"""通过桥接虚拟环境执行；凭据由已安装的 qqbot 包内部读取。"""

from qqbot.imagegen import main

if __name__ == "__main__":
    main(workspace=True)
