#!/usr/bin/env python3
"""Sổ ghi token cho skill your-token.

Hai "đồng hồ" tách biệt:
  1. USAGE  : ngân sách của cửa sổ 5 giờ (reset khi qua cửa sổ mới). Budget = free_base x multiplier của gói.
  2. CONTEXT: độ đầy của cuộc chat hiện tại (chỉ reset khi mở chat mới).

Biến môi trường: YT_LEDGER = file sổ (mặc định ./ledger.json); YT_NOW = giờ giả lập (test).
Lệnh: init | plan | add | turn | status | predict | window | calibrate | export | restore | reset
"""
import argparse, json, math, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from count_tokens import chars_to_tokens, detect_lang, est_tokens  # noqa: E402

PLANS_PATH = Path(__file__).resolve().parent.parent / "plans.json"
INPUT_TYPES = {"system", "user", "tool_result"}
OUTPUT_TYPES = {"assistant_text", "tool_call", "thinking", "created_file"}
BLOCK_RE = re.compile(r"```your-token-ledger\s*(\{.*?\})\s*```", re.S)

ASK_PLAN = """CẦN HỎI NGƯỜI DÙNG trước khi init (dùng nút bấm nếu có ask_user_input_v0):
  1) Bạn đang dùng gói nào?  Free | Pro | Max 5x | Max 20x | Khác
  2) Cửa sổ 5 giờ hiện tại bắt đầu cách đây khoảng bao lâu? (tin nhắn đầu tiên kể từ lần reset gần nhất)
Rồi chạy:
  python scripts/ledger.py init --plan <claude_free|claude_pro|claude_max5|claude_max20|custom> --model <model đang chạy>
  python scripts/ledger.py window --started-ago-min <số phút>"""


def plans():
    return json.loads(PLANS_PATH.read_text(encoding="utf-8"))


def now():
    return float(os.environ.get("YT_NOW", time.time()))


def fmt_dur(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def spath():
    return Path(os.environ.get("YT_LEDGER", "ledger.json"))


def load():
    p = spath()
    if not p.exists():
        sys.exit("Chưa có sổ.\n" + ASK_PLAN)
    return json.loads(p.read_text(encoding="utf-8"))


def save(s):
    spath().write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def blank_pending():
    return {"system": 0, "user": 0, "tool_result": 0, "assistant_text": 0,
            "tool_call": 0, "thinking": 0, "created_file": 0}


def blank_totals():
    return {"input_billed": 0, "output": 0, "weighted": 0}


def sync_budget(s):
    s["budget_tokens"] = int(round(s["free_base"] * s["multiplier"]))


def resolve_effort(v):
    sc = plans()["effort_scale"]
    v = str(v).strip().lower()
    if v in sc:
        return v, sc[v]
    if v in sc.values():
        return next((k for k, n in sc.items() if n == v), "?"), v
    sys.exit(f"effort không hợp lệ: {v}. Dùng {list(sc)} hoặc {list(sc.values())}")


def resolve_model(s, name):
    """'Claude Opus 5.5' -> 'opus-5.5'; chọn khoá dài nhất khớp."""
    low = str(name).lower().replace(" ", "-").replace("_", "-")
    cands = [k for k in s["models"] if k in low]
    if not cands:
        sys.exit(f"Không nhận ra model '{name}'. Có sẵn: {list(s['models'])}. "
                 f"Thêm bằng: calibrate --model-weight {low}=1.0")
    return max(cands, key=len)


def model_warning(s):
    pm = s.get("plan_models") or []
    fam = s["model"].split("-")[0]
    if pm and not any(m.split("-")[0] == fam for m in pm):
        print(f"(!) Model {s['model']} thường không có trong gói {s['plan']} "
              f"(có: {', '.join(pm)}). Kiểm tra lại model/gói.")


# ---------- cửa sổ thời gian ----------
def check_window(s):
    ws = s.get("window_start")
    if ws is not None and now() - ws >= s["window_hours"] * 3600:
        s["totals"] = blank_totals()
        s["window_start"] = None
        s["windows_done"] = s.get("windows_done", 0) + 1
        print(f"** CỬA SỔ {s['window_hours']:g}H MỚI: đã reset bộ đếm usage về 0 "
              f"(context của chat này vẫn giữ). Hãy báo người dùng.")
        return True
    return False


def window_line(s):
    ws = s.get("window_start")
    if ws is None:
        return "Cửa sổ: chưa bắt đầu (bắt đầu ở lượt đầu tiên; chỉnh bằng `window --started-ago-min N`)"
    left = ws + s["window_hours"] * 3600 - now()
    return f"Cửa sổ {s['window_hours']:g}h: còn {fmt_dur(left)} đến khi reset"


# ---------- tính toán ----------
def compute(s, pend, rounds, cd=None):
    """(input_billed, output_tokens) của một lượt, TRƯỚC khi nhân trọng số model."""
    cd = s["cache_discount"] if cd is None else cd
    ctx = s["context_tokens"] + pend["system"] + pend["user"]
    repeat = max(0, rounds - 1)
    inp = ctx + repeat * ctx * (1 - cd)          # mỗi vòng tool = đọc lại toàn bộ context
    inp += pend["tool_result"] * (1 + repeat / 2 * (1 - cd))
    out = sum(pend[k] for k in OUTPUT_TYPES)
    return inp, out


def turn_cost(s, inp, out):
    m = s["models"][s["model"]]
    return (inp + out * m["out_ratio"]) * m["usage_weight"]


def level_of(pct, warn, hand):
    return "HANDOFF" if pct >= hand else ("WARN" if pct >= warn else "OK")


def levels(s):
    b = s["budget_tokens"]
    u_pct = (s["totals"]["weighted"] / b) if b else None
    u_lv = level_of(u_pct, s["warn_at"], s["handoff_at"]) if b else "NO_BUDGET"
    c_pct = s["context_tokens"] / s["context_limit"]
    return u_pct, u_lv, c_pct, level_of(c_pct, s["context_warn"], s["context_handoff"])


# ---------- chi phí biên & dự báo ----------
def recent_avg(s, k=3):
    tt = s["turns"][-k:]
    if not tt:
        return {"user": 200, "tool_result": 0, "out": 500, "calls": 0}
    n = len(tt)
    return {"user": sum(x.get("user", 200) for x in tt) / n,
            "tool_result": sum(x.get("tool_result", 0) for x in tt) / n,
            "out": sum(x["output"] for x in tt) / n,
            "calls": sum(x["tool_calls"] for x in tt) / n}


def sim_cost(s, ctx, av):
    cd = s["cache_discount"]
    rep = max(0, av["calls"])
    c = ctx + av["user"]
    inp = c + rep * c * (1 - cd) + av["tool_result"] * (1 + rep / 2 * (1 - cd))
    return turn_cost(s, inp, av["out"])


def runway(s, ctx0, used0, av):
    limit = s["budget_tokens"] * s["handoff_at"]
    used, ctx, n = used0, ctx0, 0
    while n < 500:
        c = sim_cost(s, ctx, av)
        if used + c > limit:
            break
        used += c
        ctx += av["user"] + av["tool_result"] + av["out"]
        n += 1
    return n


def print_marginal(s):
    """In chi phí biên; trả True nếu nên mở chat mới."""
    b = s["budget_tokens"]
    if not b:
        return False
    av = recent_avg(s)
    nxt = sim_cost(s, s["context_tokens"], av)
    pct = nxt / b
    used = s["totals"]["weighted"]
    n_here = runway(s, s["context_tokens"], used, av)
    n_new = runway(s, 1500, used, av)
    print(f"CHI PHÍ BIÊN: tin tiếp theo ~{int(nxt)} ({pct*100:.0f}% budget), đã gồm đọc lại toàn bộ context")
    print(f"DỰ BÁO: còn ~{n_here} lượt trước ngưỡng handoff ở chat này; "
          f"mở chat mới bằng HANDOFF thì ~{n_new} lượt (cùng cửa sổ)")
    if pct >= s.get("marginal_warn", 0.10) and n_new > n_here:
        print("=> NÊN MỞ CHAT MỚI: context đã lớn nên mỗi tin tốn quá nhiều chỉ để đọc lại. "
              "Tạo HANDOFF.md ngay (kể cả khi usage còn thấp) rồi tiếp tục ở chat mới.")
        return True
    return False


def print_tips(s):
    print("MẸO TIẾT KIỆM:")
    print(" - Gộp nhiều câu hỏi vào MỘT tin (mỗi tin riêng = một lần đọc lại context).")
    print(" - Việc đơn giản: hạ model (Haiku) hoặc tắt extended thinking.")
    print(" - Đừng nghỉ >5 phút giữa các tin khi đang làm việc nặng: cache hết hạn, lần sau tính đủ.")
    print(" - File nặng: chỉ đọc đoạn cần (skim), hoặc đưa vào Projects thay vì dán lại vào chat.")


def print_status(s):
    t = s["totals"]
    u_pct, u_lv, c_pct, c_lv = levels(s)
    m = s["models"][s["model"]]
    print(f"plan={s['plan']} (x{s['multiplier']:g} Free) model={s['model']} "
          f"[trọng số x{m['usage_weight']:g}, output = {m['out_ratio']:g}x input] lượt={len(s['turns'])}")
    print(window_line(s))
    print(f"USAGE  : input_billed~{int(t['input_billed'])} output~{int(t['output'])} weighted~{int(t['weighted'])}")
    if u_pct is None:
        print("         Chưa có budget: `calibrate --budget N` hoặc `calibrate --hit-limit` khi bị limit.")
    else:
        print(f"         {u_pct*100:.0f}% budget cửa sổ ({s['budget_tokens']}) -> {u_lv}")
    print(f"CONTEXT: ~{int(s['context_tokens'])}/{s['context_limit']} = {c_pct*100:.0f}% -> {c_lv}")
    new_chat = print_marginal(s)
    if c_lv == "HANDOFF":
        print("=> CONTEXT sắp đầy: tạo HANDOFF.md, gửi file, người dùng mở CHAT MỚI để tiếp tục "
              "(reset cửa sổ không giải quyết được việc này).")
    if u_lv == "HANDOFF":
        ws = s.get("window_start")
        extra = f" Cửa sổ reset sau ~{fmt_dur(ws + s['window_hours']*3600 - now())}." if ws else ""
        print("=> USAGE sắp hết: DỪNG việc mới ở điểm sạch, tạo HANDOFF.md và gửi file ngay." + extra)
    if "WARN" in (u_lv, c_lv) and "HANDOFF" not in (u_lv, c_lv):
        print("=> Cảnh báo: ưu tiên việc quan trọng nhất, tránh đọc sâu và effort cao không cần thiết.")
    if "WARN" in (u_lv, c_lv) or "HANDOFF" in (u_lv, c_lv) or new_chat:
        print_tips(s)


def fill_pending(s, a, prof):
    pend = dict(s["pending"])
    lang = a.lang or "mixed"
    if a.user_chars:
        pend["user"] += chars_to_tokens(a.user_chars, lang)
    if a.result_tokens:
        pend["tool_result"] += a.result_tokens
    if a.out_chars:
        pend["assistant_text"] += chars_to_tokens(a.out_chars, lang)
    if a.created_chars:
        pend["created_file"] += chars_to_tokens(a.created_chars, "code" if a.lang == "code" else lang)
    if a.thinking_tokens is not None:
        pend["thinking"] += a.thinking_tokens
    else:
        pend["thinking"] += math.ceil(pend["assistant_text"] * prof["thinking_ratio"])
    if pend["tool_call"] == 0 and a.tool_calls:
        pend["tool_call"] = a.tool_calls * plans()["tool_call_tokens"]
    return pend


def apply_plan(s, plan_key, p):
    cfg = p["plans"][plan_key]
    s.update({"plan": plan_key, "multiplier": cfg["multiplier"], "window_hours": cfg["window_hours"],
              "warn_at": cfg["warn_at"], "handoff_at": cfg["handoff_at"],
              "cache_discount": cfg["cache_discount"], "plan_models": cfg["models"]})
    sync_budget(s)


# ---------- lệnh ----------
def cmd_init(a):
    p = plans()
    if not a.plan:
        print(ASK_PLAN)
        sys.exit(2)
    if a.plan not in p["plans"]:
        sys.exit(f"Plan không có: {list(p['plans'])}")
    cw = p["context_window"]
    s = {"free_base": p["free_budget_tokens"], "cache_ttl_sec": p["cache_ttl_sec"],
         "context_limit": cw["limit"], "context_warn": cw["warn_at"], "context_handoff": cw["handoff_at"],
         "marginal_warn": cw["marginal_warn"],
         "models": {k: {"out_ratio": round(v["price_out"] / v["price_in"], 3), "usage_weight": v["usage_weight"]}
                    for k, v in p["models"].items()},
         "context_tokens": 0, "window_start": None, "windows_done": 0, "last_turn_time": None,
         "totals": blank_totals(), "pending": blank_pending(), "turns": [], "calibration": []}
    apply_plan(s, a.plan, p)
    if a.budget:
        s["free_base"] = a.budget / s["multiplier"]
        sync_budget(s)
    s["model"] = resolve_model(s, a.model or p["plans"][a.plan]["default_model"])
    save(s)
    print(f"OK init plan={a.plan} (x{s['multiplier']:g}) model={s['model']} "
          f"budget/cửa sổ~{s['budget_tokens']} (giả thuyết, hãy hiệu chỉnh)")
    model_warning(s)


def cmd_plan(a):
    s = load()
    p = plans()
    if a.set not in p["plans"]:
        sys.exit(f"Plan không có: {list(p['plans'])}")
    apply_plan(s, a.set, p)
    if a.model:
        s["model"] = resolve_model(s, a.model)
    save(s)
    print(f"Đã chuyển sang {a.set} (x{s['multiplier']:g} Free): budget/cửa sổ~{s['budget_tokens']}")
    model_warning(s)


def tokens_for_add(a):
    if a.tokens:
        return a.tokens
    if a.file:
        text = Path(a.file).read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        if a.lines:
            x, y = a.lines.split("-")
            lines = lines[int(x) - 1:int(y)]
        elif a.read_mode == "skim":
            lines = lines[:80]
        text = "\n".join(lines)
        lang = a.lang or detect_lang(text, a.file)
        return est_tokens(text, lang) * max(1, a.times)
    if a.chars:
        return chars_to_tokens(a.chars, a.lang or "mixed")
    sys.exit("Cần --tokens, --chars hoặc --file")


def cmd_add(a):
    s = load()
    t = tokens_for_add(a)
    s["pending"][a.type] += t
    save(s)
    print(f"+{t} token ({a.type}, {'input' if a.type in INPUT_TYPES else 'output'}) vào lượt đang mở")


def gap_seconds(s, a):
    if a.gap_min is not None:
        return a.gap_min * 60
    if s.get("last_turn_time") is not None:
        return now() - s["last_turn_time"]
    return 0


def cmd_turn(a):
    s = load()
    check_window(s)
    if s["window_start"] is None:
        s["window_start"] = now()
    if a.model:
        s["model"] = resolve_model(s, a.model)
        model_warning(s)
    raw, name = resolve_effort(a.effort)
    prof = plans()["effort_profiles"][name]
    pend = fill_pending(s, a, prof)
    gap = gap_seconds(s, a)
    expired = gap > s["cache_ttl_sec"]
    cd = 0.0 if expired else s["cache_discount"]       # cache hết hạn -> đọc lại tính đủ
    rounds = a.tool_calls + 1
    inp, out = compute(s, pend, rounds, cd)
    cost = turn_cost(s, inp, out)
    s["totals"]["input_billed"] += inp
    s["totals"]["output"] += out
    s["totals"]["weighted"] += cost
    s["context_tokens"] += pend["system"] + pend["user"] + pend["tool_result"] + out
    s["turns"].append({"n": len(s["turns"]) + 1, "model": s["model"], "effort": name, "effort_raw": raw,
                       "tool_calls": a.tool_calls, "input_billed": int(inp), "output": int(out),
                       "user": int(pend["user"]), "tool_result": int(pend["tool_result"]),
                       "cache_expired": bool(expired), "weighted": int(cost)})
    s["pending"] = blank_pending()
    s["last_turn_time"] = now()
    save(s)
    print(f"lượt {len(s['turns'])} [{s['model']}/{name}] +in {int(inp)} +out {int(out)} +weighted {int(cost)}")
    if expired and s["cache_discount"] > 0:
        print(f"(nghỉ {gap/60:.0f} phút > {s['cache_ttl_sec']/60:.0f}: cache hết hạn, lượt này tính đủ không giảm giá)")
    print_status(s)


def cmd_status(a):
    s = load()
    if check_window(s):
        save(s)
    print_status(s)


def cmd_predict(a):
    s = load()
    ws_expired = s.get("window_start") is not None and now() - s["window_start"] >= s["window_hours"] * 3600
    base_w = 0 if ws_expired else s["totals"]["weighted"]
    if a.model:
        s = dict(s); s["model"] = resolve_model(s, a.model)
    raw, name = resolve_effort(a.effort)
    prof = plans()["effort_profiles"][name]
    if a.tool_calls is None:
        a.tool_calls = prof["expected_tool_calls"]
    pend = fill_pending(s, a, prof)
    expired = (a.gap_min or 0) * 60 > s["cache_ttl_sec"]
    inp, out = compute(s, pend, a.tool_calls + 1, 0.0 if expired else None)
    cost = turn_cost(s, inp, out)
    print(f"Dự đoán [{s['model']}/{name}, {a.tool_calls} tool{', cache hết hạn' if expired else ''}]: ~{int(cost)} weighted")
    b = s["budget_tokens"]
    if b:
        after = (base_w + cost) / b
        print(f"USAGE sau việc này: ~{after*100:.0f}% budget cửa sổ")
        if after >= s["handoff_at"]:
            print("=> Vượt ngưỡng usage: hạ effort/model, chia nhỏ việc, hoặc handoff TRƯỚC khi bắt đầu.")
    else:
        print("(chưa có budget để so sánh usage)")
    ctx_after = (s["context_tokens"] + pend["user"] + pend["tool_result"] + out) / s["context_limit"]
    print(f"CONTEXT sau việc này: ~{ctx_after*100:.0f}%")
    if ctx_after >= s["context_handoff"]:
        print("=> Vượt ngưỡng context: nên handoff/mở chat mới trước khi làm.")


def cmd_window(a):
    s = load()
    if a.started_ago_min is not None:
        s["window_start"] = now() - a.started_ago_min * 60
    if a.hours:
        s["window_hours"] = a.hours
    save(s)
    print(window_line(s))


def cmd_calibrate(a):
    s = load()
    if a.budget:
        s["free_base"] = a.budget / s["multiplier"]
        sync_budget(s)
        print(f"Đặt budget/cửa sổ = {s['budget_tokens']} (tương đương Free ~{int(s['free_base'])})")
    if a.context_limit:
        s["context_limit"] = a.context_limit
        print(f"Đặt context_limit = {a.context_limit}")
    if a.cache_discount is not None:
        s["cache_discount"] = a.cache_discount
        print(f"Đặt cache_discount = {a.cache_discount}")
    for kv in a.model_weight or []:
        k, v = kv.split("=")
        k = k.lower()
        s["models"].setdefault(k, {"out_ratio": 5.0, "usage_weight": 1.0})["usage_weight"] = float(v)
        print(f"usage_weight[{k}] = {float(v)}")
    if a.hit_limit:
        obs = s["totals"]["weighted"]
        if obs <= 0:
            sys.exit("Usage hiện = 0 (sổ chưa có lượt nào trong cửa sổ này) nên không hiệu chỉnh được. "
                     "Chạy hit-limit ngay lúc bị limit, trước khi cửa sổ reset.")
        s["calibration"].append(obs / s["multiplier"])      # quy về đơn vị Free để dùng chung giữa các gói
        s["free_base"] = sum(s["calibration"]) / len(s["calibration"])
        sync_budget(s)
        print(f"Ghi nhận bị limit ở weighted~{int(obs)}. Budget mới = {s['budget_tokens']} "
              f"(trung bình {len(s['calibration'])} lần quan sát, quy đổi theo gói)")
    save(s)


def cmd_export(a):
    s = load()
    s["pending"] = blank_pending()
    block = "```your-token-ledger\n" + json.dumps(s, ensure_ascii=False) + "\n```\n"
    if a.out:
        with open(a.out, "a", encoding="utf-8") as f:
            f.write("\n## Sổ token (your-token)\n" + block)
        print(f"Đã ghi sổ vào {a.out}")
    else:
        print(block)


def cmd_restore(a):
    text = Path(a.file).read_text(encoding="utf-8")
    m = BLOCK_RE.search(text)
    if not m:
        sys.exit("Không thấy khối your-token-ledger trong file.")
    s = json.loads(m.group(1))
    check_window(s)
    s["context_tokens"] = est_tokens(text)
    s["pending"] = blank_pending()
    s["last_turn_time"] = None
    save(s)
    print("Đã khôi phục sổ (gói, model, hiệu chỉnh được giữ). Context tính lại cho CHAT MỚI (chỉ gồm HANDOFF).")
    print("Hỏi người dùng xác nhận gói/model còn đúng không; nếu khác: `plan --set ...`.")
    print_status(s)


def cmd_reset(a):
    s = load()
    s["totals"] = blank_totals()
    s["window_start"] = None
    s["pending"] = blank_pending()
    s["turns"] = []
    s["last_turn_time"] = None
    if a.new_chat:
        s["context_tokens"] = 0
    save(s)
    print("Đã reset usage" + (" và context (chat mới)." if a.new_chat else " (giữ context). Giữ budget, trọng số, hiệu chỉnh."))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    langs = ["vi", "en", "code", "mixed"]

    p = sub.add_parser("init"); p.add_argument("--plan", help="claude_free|claude_pro|claude_max5|claude_max20|custom")
    p.add_argument("--model", help="vd 'Claude Opus 5.5' / opus-5.5 / sonnet")
    p.add_argument("--budget", type=int, help="ghi đè budget cho gói hiện tại"); p.set_defaults(f=cmd_init)

    p = sub.add_parser("plan"); p.add_argument("--set", required=True); p.add_argument("--model")
    p.set_defaults(f=cmd_plan)

    p = sub.add_parser("add")
    p.add_argument("--type", required=True, choices=sorted(INPUT_TYPES | OUTPUT_TYPES))
    p.add_argument("--tokens", type=int); p.add_argument("--chars", type=int)
    p.add_argument("--file"); p.add_argument("--lines", help="vd 1-80")
    p.add_argument("--read-mode", choices=["skim", "normal", "deep"], default="normal")
    p.add_argument("--times", type=int, default=1, help="số lần đọc lại (deep)")
    p.add_argument("--lang", choices=langs); p.set_defaults(f=cmd_add)

    def turn_args(p):
        p.add_argument("--effort", required=True, help="số 0-4 (4=low..0=max) hoặc tên")
        p.add_argument("--model", help="đổi model nếu người dùng vừa chuyển")
        p.add_argument("--tool-calls", type=int, default=None)
        p.add_argument("--user-chars", type=int); p.add_argument("--out-chars", type=int)
        p.add_argument("--created-chars", type=int); p.add_argument("--result-tokens", type=int)
        p.add_argument("--thinking-tokens", type=int); p.add_argument("--lang", choices=langs)
        p.add_argument("--gap-min", type=float, help="phút nghỉ kể từ lượt trước (mặc định: tự tính)")

    p = sub.add_parser("turn"); turn_args(p); p.set_defaults(f=cmd_turn)
    p = sub.add_parser("predict"); turn_args(p); p.set_defaults(f=cmd_predict)
    sub.add_parser("status").set_defaults(f=cmd_status)

    p = sub.add_parser("window")
    p.add_argument("--started-ago-min", type=int, help="cửa sổ bắt đầu cách đây N phút")
    p.add_argument("--hours", type=float); p.set_defaults(f=cmd_window)

    p = sub.add_parser("calibrate"); p.add_argument("--budget", type=int)
    p.add_argument("--context-limit", type=int); p.add_argument("--cache-discount", type=float)
    p.add_argument("--model-weight", nargs="+", metavar="NAME=VALUE")
    p.add_argument("--hit-limit", action="store_true"); p.set_defaults(f=cmd_calibrate)

    p = sub.add_parser("export"); p.add_argument("--out"); p.set_defaults(f=cmd_export)
    p = sub.add_parser("restore"); p.add_argument("--file", required=True); p.set_defaults(f=cmd_restore)
    p = sub.add_parser("reset"); p.add_argument("--new-chat", action="store_true"); p.set_defaults(f=cmd_reset)

    a = ap.parse_args()
    if a.cmd == "turn" and a.tool_calls is None:
        a.tool_calls = 0
    a.f(a)


if __name__ == "__main__":
    main()
