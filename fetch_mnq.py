#!/usr/bin/env python3
"""轉接檔：保留給既有的 update-mnq 排程使用，實際邏輯在 fetch_futures.py"""
from fetch_futures import run

if __name__ == "__main__":
    run("mnq")
