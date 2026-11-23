"""mutmut の結果から、週次 issue に載せる Markdown のレポートを作る。

AI を使わず、元の行と変異後の行をトークン単位で比べて決定論的に分類する。

- 高: 演算子・条件・制御の変更、数値・真偽値の変更
- 中: 値の None への置き換え、引数・キーワードの削除、分類できなかったもの
- 低: 文字列リテラルだけの変更（例外メッセージ・dict のキー・既定値など）
- 対象外: help・metavar・span 名など、振る舞いに関わらない文字列の変更

高と中を「対応が必要」として数え、その件数を GITHUB_OUTPUT の actionable に書く。
`uv run mutmut run` のあとに、リポジトリのルートで実行する:

    uv run python scripts/mutation_report.py --out mutation-report.md --full mutation-report-full.md
"""

from __future__ import annotations

import argparse
import difflib
import io
import os
import tokenize
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from mutmut.mutation.data import SourceFileMutationData
from mutmut.mutation.diff_apply import get_diff_for_mutant
from mutmut.stats import status_by_exit_code
from mutmut.utils.file_utils import walk_mutatable_files

ACTIONABLE = ("高", "中")
LEVEL_ORDER = ("高", "中", "低", "対象外")

# GitHub の issue 本文の上限は 65,536 文字。表やヘッダーの分の余裕を残す
BODY_LIMIT = 60000

OPERATORS = {
    "and", "or", "not", "in", "is", "break", "continue",
    "+", "-", "*", "/", "//", "%", "<", "<=", ">", ">=", "==", "!=",
}  # fmt: skip
# この引数の値の文字列は、変わっても振る舞いに影響しない
NOISE_KWARGS = {"help", "metavar", "description", "prog"}
# この呼び出しの最初の引数の文字列は、変わっても振る舞いに影響しない
NOISE_CALLS = {"start_as_current_span", "add_argument_group"}

Token = tuple[int, str]


@dataclass
class Mutant:
    name: str
    path: str
    function: str
    level: str
    reason: str
    removed: str
    added: str


def tokens(source: str) -> list[Token] | None:
    skip = {
        tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER,
        tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT,
    }  # fmt: skip
    try:
        gen = tokenize.generate_tokens(io.StringIO(source.strip() + "\n").readline)
        return [(t.type, t.string) for t in gen if t.type not in skip]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None


def is_noise_change(before: list[Token], i1: int, i2: int) -> bool:
    """before[i1:i2] の変更が、振る舞いに関わらない箇所に収まるかを返す。

    help= などの値、span 名などの引数、help= などの引数そのもののいずれか。
    help=argparse.SUPPRESS や help=help_ のように、値が文字列でない場合も含める。
    """
    if i1 == i2:
        return False
    prev = [s for _, s in before[max(0, i1 - 2) : i1]]
    changed = [s for _, s in before[i1:i2]]
    # 値の書き換え（None への置き換えを含む）。後ろの引数まで変わっていないこと
    if len(prev) == 2 and (
        (prev[1] == "=" and prev[0] in NOISE_KWARGS) or (prev[1] == "(" and prev[0] in NOISE_CALLS)
    ):
        return "," not in changed
    # キーワード引数ごとの削除（前の , も一緒に消えることがある）
    if changed[0] == ",":
        changed = changed[1:]
    return len(changed) >= 2 and changed[0] in NOISE_KWARGS and changed[1] == "="


def classify(removed: str, added: str) -> tuple[str, str]:
    before, after = tokens(removed), tokens(added)
    if before is None or after is None:
        return "中", "分類できない変更"

    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    ops = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    old = [(i, before[i]) for _, i1, i2, _, _ in ops for i in range(i1, i2)]
    new = [after[j] for _, _, _, j1, j2 in ops for j in range(j1, j2)]
    changed = [t for _, t in old] + new
    if not changed:
        return "中", "分類できない変更"

    if all(is_noise_change(before, i1, i2) for _, i1, i2, _, _ in ops):
        return "対象外", "help・metavar・span 名など"

    if all(t == tokenize.STRING for t, _ in changed):
        return "低", "文字列リテラルの変更"

    strings = {s for _, s in changed}
    if strings & OPERATORS:
        return "高", "演算子・条件・制御の変更"
    if any(t == tokenize.NUMBER for t, _ in changed) or strings & {"True", "False"}:
        return "高", "数値・真偽値の変更"
    if "None" in {s for _, s in new}:
        return "中", "値を None に置き換え"
    if old and not new:
        return "中", "引数・キーワードの削除"
    return "中", "分類できない変更"


def function_label(name: str) -> str:
    """nandemo_oshirase.lambda_function.x_route__mutmut_7 -> route"""
    last = name.rsplit(".", 1)[-1].rsplit("__mutmut_", 1)[0]
    if last.startswith("xǁ"):
        return ".".join(last[2:].split("ǁ"))
    return last.removeprefix("x_")


def diff_lines(diff: str) -> tuple[str, str]:
    lines = diff.splitlines()
    removed = [line[1:] for line in lines if line.startswith("-") and not line.startswith("---")]
    added = [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]
    return "\n".join(removed), "\n".join(added)


def collect() -> tuple[Counter[str], list[Mutant]]:
    statuses: Counter[str] = Counter()
    survived: list[Mutant] = []
    for path in walk_mutatable_files():
        data = SourceFileMutationData(path=path)
        data.load()
        for name, exit_code in data.exit_code_by_key.items():
            status = status_by_exit_code[exit_code]
            statuses[status] += 1
            if status != "survived":
                continue
            removed, added = diff_lines(get_diff_for_mutant(name, path=path))
            level, reason = classify(removed, added)
            survived.append(
                Mutant(name, str(path), function_label(name), level, reason, removed, added)
            )
    return statuses, survived


def score(statuses: Counter[str]) -> float:
    killed = statuses["killed"] + statuses["timeout"] + statuses["caught by type check"]
    judged = killed + statuses["survived"] + statuses["suspicious"]
    return 100.0 * killed / judged if judged else 100.0


def render_mutant(m: Mutant) -> str:
    diff = "\n".join(
        [f"- {line.strip()}" for line in m.removed.splitlines()]
        + [f"+ {line.strip()}" for line in m.added.splitlines()]
    )
    return f"- `{m.name}`（{m.reason}）\n  ```diff\n{_indent(diff)}\n  ```\n"


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


def render(statuses: Counter[str], survived: list[Mutant], limit: int | None) -> str:
    by_level = Counter(m.level for m in survived)
    actionable = sum(by_level[lv] for lv in ACTIONABLE)
    head = [
        f"<!-- mutation-score:{score(statuses):.1f} -->",
        "## ミューテーションテストの結果",
        "",
        f"スコア **{score(statuses):.1f}%**（前回 {{{{PREVIOUS_SCORE}}}}）"
        f" / 対応が必要（高・中）**{actionable} 件**",
        "",
        "| killed | survived | no tests | timeout | その他 |",
        "|---:|---:|---:|---:|---:|",
        "| {} | {} | {} | {} | {} |".format(
            statuses["killed"],
            statuses["survived"],
            statuses["no tests"],
            statuses["timeout"],
            sum(statuses.values())
            - sum(statuses[s] for s in ("killed", "survived", "no tests", "timeout")),
        ),
        "",
        "| 区分 | 件数 | 内容 |",
        "|---|---:|---|",
        f"| 高 | {by_level['高']} | 演算子・条件・制御、数値・真偽値の変更 |",
        f"| 中 | {by_level['中']} | 値の None への置き換え、引数の削除 |",
        f"| 低 | {by_level['低']} | 文字列リテラルだけの変更 |",
        f"| 対象外 | {by_level['対象外']} | help・metavar・span 名など |",
        "",
        "高・中が 0 件になると、この issue は自動でクローズされます。"
        "テストを足すか、等価なミュータントなら該当行に `# pragma: no mutate` を付けてください。"
        "差分は `uv run mutmut show <名前>` でも確認できます。",
        "",
    ]
    body = "\n".join(head)
    omitted = 0

    def add(text: str) -> bool:
        nonlocal body
        if limit is not None and len(body) + len(text) > limit:
            return False
        body += text
        return True

    for level in ("高", "中", "低"):
        items = [m for m in survived if m.level == level]
        if not items:
            continue
        folded = level == "低"
        add(
            f"<details><summary>{level}（{len(items)} 件）</summary>\n\n"
            if folded
            else f"### {level}（{len(items)} 件）\n\n"
        )
        groups: dict[tuple[str, str], list[Mutant]] = defaultdict(list)
        for m in items:
            groups[(m.path, m.function)].append(m)
        for (path, func), group in sorted(groups.items()):
            section = f"#### `{path}` › `{func}`（{len(group)} 件）\n\n"
            section += "".join(render_mutant(m) for m in group) + "\n"
            if not add(section):
                omitted += len(group)
        if folded:
            add("</details>\n\n")

    if omitted:
        body += (
            f"\n> 本文の長さの上限のため、{omitted} 件を省略しました。"
            "全件は workflow の artifact（mutation-report）を参照してください。\n"
        )
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="issue 本文に使うレポート")
    parser.add_argument("--full", type=Path, help="省略なしのレポート（artifact 用）")
    args = parser.parse_args()

    statuses, survived = collect()
    args.out.write_text(render(statuses, survived, BODY_LIMIT), encoding="utf-8")
    if args.full:
        args.full.write_text(render(statuses, survived, None), encoding="utf-8")

    actionable = sum(1 for m in survived if m.level in ACTIONABLE)
    print(f"score={score(statuses):.1f}% survived={len(survived)} actionable={actionable}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"actionable={actionable}\n")


if __name__ == "__main__":
    main()
