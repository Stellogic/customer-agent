from __future__ import annotations

import json
import sys

from prototype.scenarios import phase, reset, run_matrix, state_snapshot


BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def render(message: str = "") -> None:
    print("\033[2J\033[H", end="")
    print(f"{BOLD}PROTOTYPE — LangGraph 恢复与业务幂等{RESET}")
    if message:
        print(f"\n{message}")
    print(f"\n{BOLD}当前完整状态{RESET}")
    print(json.dumps(state_snapshot(), ensure_ascii=False, indent=2))
    print(f"\n{BOLD}动作{RESET}")
    print(f"{BOLD}[b]{RESET} {DIM}创建 generation，模拟提交响应丢失并对账，运行至 interrupt{RESET}")
    print(f"{BOLD}[r]{RESET} {DIM}恢复，模拟业务工具已提交但响应丢失{RESET}")
    print(f"{BOLD}[c]{RESET} {DIM}重启式恢复，使用同幂等键完成{RESET}")
    print(f"{BOLD}[s]{RESET} {DIM}创建新 generation 并验证旧代次迟到调用被拒{RESET}")
    print(f"{BOLD}[m]{RESET} {DIM}重置后运行完整验证矩阵{RESET}")
    print(f"{BOLD}[x]{RESET} {DIM}重置{RESET}  {BOLD}[q]{RESET} {DIM}退出{RESET}")


def interactive() -> None:
    reset()
    actions = {
        "b": lambda: phase("bootstrap"),
        "r": lambda: phase("resume-loss"),
        "c": lambda: phase("recover"),
        "s": lambda: phase("stale"),
        "m": lambda: [item.__dict__ for item in run_matrix()],
        "x": lambda: reset() or {"reset": True},
    }
    message = "已初始化临时状态。"
    while True:
        render(message)
        choice = input("\n选择动作: ").strip().lower()
        if choice == "q":
            return
        try:
            message = json.dumps(actions[choice](), ensure_ascii=False, indent=2)
        except KeyError:
            message = "未知动作。"
        except Exception as exc:  # Deliberately visible in a throwaway TUI.
            message = f"{type(exc).__name__}: {exc}"


def main() -> int:
    if len(sys.argv) == 1:
        interactive()
        return 0
    if sys.argv[1] == "matrix":
        results = run_matrix()
        for result in results:
            print(f"{'PASS' if result.passed else 'FAIL'} | {result.scenario}")
        return 0 if all(result.passed for result in results) else 1
    if sys.argv[1] == "phase":
        print(json.dumps(phase(sys.argv[2]), ensure_ascii=False))
        return 0
    raise SystemExit("usage: run_prototype.py [matrix|phase <name>]")


if __name__ == "__main__":
    raise SystemExit(main())
