"""python -m web [--host H] [--port P]"""
import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="Odwolania2json - prototyp webowy")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    uvicorn.run("web.app:app", host=a.host, port=a.port)


main()
