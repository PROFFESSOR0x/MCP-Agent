#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP-Agent  -  Turn any chatbot that supports Remote MCP (including compatible Claude and ChatGPT clients) into a real AI agent
that reads/edits files and runs code on your machine, with access levels, a public URL and an Auth Token.
حوّل أي chatbot يدعم Remote MCP، بما في ذلك العملاء المتوافقون مع Claude وChatGPT، إلى وكيل ذكاء اصطناعي يقرأ الملفات ويعدلها وينفذ الأكواد على جهازك.

Examples / أمثلة:
  python mcp_agent.py                                          # read-only (whole machine / الجهاز كله)
  python mcp_agent.py --access read-only --workspace ~/projects
  python mcp_agent.py --access operate --workspace ~/myproj    # read+write inside this folder only
  python mcp_agent.py --access full                            # everything / كل شيء
  python mcp_agent.py --access operate -w . --no-exec          # no command execution / بدون تنفيذ أوامر
  python mcp_agent.py --lang ar                                # واجهة عربية  (or: --lang en)

Self-contained: checks the libraries (mcp, pyngrok, uvicorn) and installs what is missing.
On Linux/macOS it creates its own venv automatically and re-launches itself inside it.
"""
import argparse
import os
import sys
import subprocess
import shutil
import tempfile
import stat
import importlib
import importlib.util
import secrets
import hmac
import socket
import time
import re
import asyncio
import functools
from pathlib import Path

try:  # keep Arabic output working on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ----------------------------------------------------------------------------
# 0) i18n  (--lang ar | en)
# ----------------------------------------------------------------------------
# Each entry: key -> (arabic, english).  Tool descriptions sent to the model stay in English.
S = {
    # generic
    "err": ("[خطأ]", "[Error]"),
    # bootstrap
    "py_old": ("يلزم Python 3.10 أو أحدث (النسخة الحالية {v})", "Python 3.10 or newer is required (current: {v})"),
    "venv_still": ("المكتبات ما زالت ناقصة داخل venv. احذف المجلد {d} وأعد التشغيل.",
                   "Dependencies are still missing inside the venv. Delete {d} and run again."),
    "missing": ("[+] مكتبات ناقصة: {l}", "[+] Missing packages: {l}"),
    "venv_make": ("[+] إنشاء بيئة venv خاصة في: {d}", "[+] Creating a private venv at: {d}"),
    "venv_fail": ("[!] تعذر إنشاء venv (على Debian/Ubuntu ثبّت:  sudo apt install python3-venv)",
                  "[!] Could not create a venv (on Debian/Ubuntu run: sudo apt install python3-venv)"),
    "venv_fallback": ("[+] محاولة بديلة: التثبيت في مستوى المستخدم ...", "[+] Fallback: installing at user level ..."),
    "venv_dead": ("فشل إنشاء venv والتثبيت البديل. ثبّت python3-venv ثم أعد التشغيل.",
                  "Failed to create a venv and the fallback install. Install python3-venv and run again."),
    "install_venv": ("[+] تثبيت المكتبات داخل venv (قد يستغرق دقيقة) ...", "[+] Installing packages into the venv (may take a minute) ..."),
    "pip_fail": ("فشل تثبيت المكتبات عبر pip. تحقق من الاتصال بالإنترنت.", "pip failed to install the packages. Check your internet connection."),
    "pip_fail_short": ("فشل تثبيت المكتبات عبر pip.", "pip failed to install the packages."),
    "installing": ("[+] تثبيت المكتبات ...", "[+] Installing packages ..."),
    "direct_fail": ("[!] التثبيت المباشر لم ينجح، سأستخدم venv ...", "[!] Direct install failed, falling back to a venv ..."),
    # arguments
    "desc": ("MCP-Agent: خادم MCP لربط مساعدات الذكاء الاصطناعي المتوافقة بجهازك، مع صلاحيات قراءة/كتابة/تنفيذ ومصادقة آمنة",
             "MCP-Agent by ProfessorX: Connect MCP-compatible AI assistants to your computer with access controls and token authentication"),
    "h_access": ("مستوى الصلاحيات:\n"
                 "  read-only : قراءة أي ملف في الجهاز، بدون كتابة أو تنفيذ (الافتراضي)\n"
                 "  operate   : قراءة + كتابة + تنفيذ داخل مجلد --workspace فقط (مطلوب)\n"
                 "  full      : كل شيء في الجهاز (قراءة/كتابة/تنفيذ)",
                 "Access level:\n"
                 "  read-only : read any file on the machine, no writing or execution (default)\n"
                 "  operate   : read + write + execute inside the --workspace folder only (required)\n"
                 "  full      : everything on the machine (read/write/execute)"),
    "h_ws": ("مجلد العمل. مطلوب مع operate، واختياري مع غيره (يكون المجلد الافتراضي)",
             "Workspace folder. Required with operate, optional otherwise (becomes the default folder)"),
    "h_port": ("المنفذ المحلي (افتراضي 8765، وإذا كان مشغولًا يختار غيره)", "Local port (default 8765; picks another if busy)"),
    "h_token": ("Auth Token للـ MCP. إذا لم تحدده يُولَّد عشوائيًا", "Auth Token for the MCP. Generated randomly if not provided"),
    "h_domain": ("دومين ngrok ثابت (اختياري، لحسابات ngrok التي تملك دومين)", "Static ngrok domain (optional, for ngrok accounts that have one)"),
    "h_ngtok": ("ngrok authtoken (أو متغير NGROK_AUTHTOKEN)", "ngrok authtoken (or the NGROK_AUTHTOKEN variable)"),
    "h_nongrok": ("تشغيل محلي فقط بدون رابط عام", "Run locally only, without a public URL"),
    "h_noexec": ("تعطيل أدوات تنفيذ الأوامر/الأكواد حتى في operate/full", "Disable command/code execution tools even in operate/full"),
    "h_timeout": ("أقصى مهلة (ثواني) لتنفيذ أمر واحد", "Maximum timeout (seconds) for a single command"),
    "h_lang": ("لغة الواجهة: ar أو en (الافتراضي: حسب لغة النظام)", "Interface language: ar or en (default: system language)"),
    "e_ws_req": ("--workspace مطلوب عند استخدام --access operate", "--workspace is required when using --access operate"),
    "e_ws_none": ("المجلد غير موجود: {w}", "Folder does not exist: {w}"),
    "e_tok_short": ("الـ token قصير جدًا (16 حرفًا على الأقل)", "The token is too short (at least 16 characters)"),
    "e_tok_chars": ("الـ token يجب أن يحتوي فقط على حروف/أرقام/_-.~ (لأنه يوضع في الرابط)",
                    "The token may only contain letters/digits/_-.~ (because it goes in the URL)"),
    # auth middleware
    "rejected": ("[!] {t} طلب مرفوض (token غير صحيح) -> {m} {p}", "[!] {t} Request rejected (bad token) -> {m} {p}"),
    # tools: generic
    "out_trunc": ("... [تم اقتطاع {n} حرف] ...", "... [{n} characters truncated] ..."),
    "denied_ws": ("ممنوع: المسار خارج الـ workspace ({w}) في وضع operate", "Denied: path is outside the workspace ({w}) in operate mode"),
    "del_root": ("رفض حذف الجذر أو مجلد المستخدم الرئيسي", "Refusing to delete the filesystem root or the home folder"),
    "del_ws": ("رفض حذف مجلد الـ workspace نفسه", "Refusing to delete the workspace folder itself"),
    "not_exist": ("غير موجود: {p}", "Not found: {p}"),
    "empty_dir": ("(فارغ)", "(empty)"),
    "cap_entries": ("... (تم الاكتفاء بأول {n})", "... (capped at the first {n})"),
    "perm_dir": ("لا توجد صلاحية نظام لقراءة: {p}", "OS permission denied reading: {p}"),
    "not_file": ("{p} ليس ملفًا", "{p} is not a file"),
    "binary": ("[ملف ثنائي، الحجم {n} bytes]", "[binary file, {n} bytes]"),
    "more_lines": ("... [مقتطع. أكمل بـ start_line={n}]", "... [truncated. continue with start_line={n}]"),
    "empty_file": ("(ملف فارغ أو start_line بعد نهاية الملف)", "(empty file, or start_line is past the end)"),
    "no_results": ("لا نتائج", "No results"),
    "cap_results": ("... (الحد {n})", "... (limit {n})"),
    "created": ("تم الإنشاء: {p} ({n} chars)", "Created: {p} ({n} chars)"),
    "replaced": ("تم الاستبدال: {p} ({n} chars)", "Overwritten: {p} ({n} chars)"),
    "old_empty": ("old_str فارغ", "old_str is empty"),
    "old_none": ("النص old_str غير موجود في الملف (تأكد من المسافات وفواصل الأسطر)",
                 "old_str was not found in the file (check whitespace and line endings)"),
    "old_multi": ("old_str يظهر {n} مرات؛ أضف سياقًا أكثر أو استخدم replace_all=true",
                  "old_str appears {n} times; add more context or use replace_all=true"),
    "edited": ("تم التعديل: {p} ({n} استبدال)", "Edited: {p} ({n} replacement(s))"),
    "done": ("تم: {p}", "Done: {p}"),
    "moved": ("تم النقل: {s} -> {d}", "Moved: {s} -> {d}"),
    "deleted": ("تم الحذف: {p}", "Deleted: {p}"),
    "timeout_tag": ("[TIMEOUT بعد {t}s]", "[TIMEOUT after {t}s]"),
    # ngrok
    "ng_start": ("[+] تشغيل ngrok (أول مرة قد يحمّل ملف ngrok تلقائيًا) ...",
                 "[+] Starting ngrok (the first run may download the ngrok binary) ..."),
    "ng_nologin": ("\n[!] ngrok غير مسجَّل الدخول على هذا الجهاز.", "\n[!] ngrok is not logged in on this machine."),
    "ng_s1": ("    1) افتح:  https://dashboard.ngrok.com/signup   (أو سجّل الدخول)",
              "    1) Open:  https://dashboard.ngrok.com/signup   (or log in)"),
    "ng_s2": ("    2) انسخ الـ Authtoken من:  https://dashboard.ngrok.com/get-started/your-authtoken",
              "    2) Copy your Authtoken from:  https://dashboard.ngrok.com/get-started/your-authtoken"),
    "ng_notty": ("لا توجد طرفية تفاعلية. مرّر --ngrok-authtoken أو عرّف متغير NGROK_AUTHTOKEN.",
                 "No interactive terminal. Pass --ngrok-authtoken or set the NGROK_AUTHTOKEN variable."),
    "ng_prompt": ("    الصق الـ Authtoken هنا ثم Enter (أو اتركه فارغًا للانتظار): ",
                  "    Paste the Authtoken here and press Enter (or leave empty to wait): "),
    "ng_cancel": ("تم الإلغاء.", "Cancelled."),
    "ng_wait": ("    اضغط Enter بعد أن تسجّل الدخول/تحفظ الـ token ... ", "    Press Enter after you log in / save the token ... "),
    "ng_saved": ("    [✓] تم حفظ الـ authtoken في إعدادات ngrok.", "    [✓] Authtoken saved to the ngrok config."),
    "ng_bad": ("    [x] الـ token غير صالح: {e}", "    [x] Invalid token: {e}"),
    "ng_108": ("حسابك على ngrok مفتوح في جلسة أخرى (الخطة المجانية تسمح بجلسة واحدة). أغلقها وأعد التشغيل.\n{m}",
               "Your ngrok account has another session open (the free plan allows one). Close it and run again.\n{m}"),
    "ng_fail": ("فشل تشغيل ngrok:\n{m}", "ngrok failed to start:\n{m}"),
    "no_port": ("لا يوجد منفذ متاح", "No free port available"),
    # banner
    "b_ready": ("✅ الـ MCP جاهز", "✅ MCP server is ready"),
    "lvl_ro": ("قراءة فقط (كل الجهاز)", "read-only (whole machine)"),
    "lvl_op": ("قراءة + كتابة داخل: {w}", "read + write only inside: {w}"),
    "lvl_full": ("صلاحيات كاملة", "full access"),
    "b_access": ("  الصلاحيات : {a}  -  {d}", "  Access     : {a}  -  {d}"),
    "b_exec": ("  التنفيذ    : {s}", "  Execution  : {s}"),
    "on": ("مفعّل", "enabled"),
    "off": ("معطّل", "disabled"),
    "b_ws": ("  Workspace  : {w}", "  Workspace  : {w}"),
    "b_url": ("\n  🔗 رابط MCP Connector (أضفه إلى عميل يدعم Remote MCP):\n     {u}",
              "\n  🔗 MCP Connector URL (add it to a client that supports Remote MCP):\n     {u}"),
    "b_tok": ("\n  🔑 Auth Token:\n     {t}", "\n  🔑 Auth Token:\n     {t}"),
    "b_how1": ("\n  طريقة الإضافة:", "\n  How to connect:"),
    "b_how2": ("   أضف الرابط من إعدادات Connectors / Remote MCP في العميل الذي تستخدمه.",
               "   Add the URL from your client’s Connectors / Remote MCP settings."),
    "b_how3": ("   (إذا كان العميل يدعم Bearer Token، يمكنك استخدام الهيدر بدلًا من تضمينه في الرابط).",
               "   (If your client supports bearer authentication, use the header instead of embedding the token in the URL)."),
    "b_hdr": ("  للعملاء الذين يدعمون الهيدرات: {b}/mcp  مع  Authorization: Bearer <token>",
              "  For clients that support headers: {b}/mcp  with  Authorization: Bearer <token>"),
    "b_w_op1": ("\n  ⚠ تنبيه: أدوات الملفات محصورة بالـ workspace، لكن run_command يشغّل أوامر نظام عادية",
                "\n  ⚠ Note: file tools are confined to the workspace, but run_command runs ordinary system commands"),
    "b_w_op2": ("    (ليس sandbox). لعزل صارم استخدم --no-exec.", "    (it is NOT a sandbox). For strict isolation use --no-exec."),
    "b_warn": ("\n  ⚠ من يملك الرابط/التوكن يملك صلاحياتك. لا تشاركه. Ctrl+C للإيقاف.",
               "\n  ⚠ Whoever has the URL/token has your permissions. Do not share it. Ctrl+C to stop."),
    "stopped": ("\n[+] تم الإيقاف.", "\n[+] Stopped."),
}


def _detect_lang(argv):
    val = None
    for i, a in enumerate(argv):
        if a in ("--lang", "-lang") and i + 1 < len(argv):
            val = argv[i + 1]
        elif a.startswith(("--lang=", "-lang=")):
            val = a.split("=", 1)[1]
    val = (val or os.environ.get("MCP_AGENT_LANG") or "").strip().lower()
    if val in ("ar", "en"):
        return val
    try:
        import locale
        loc = (locale.getlocale()[0] or "") or os.environ.get("LANG", "")
    except Exception:
        loc = os.environ.get("LANG", "")
    return "ar" if loc.lower().startswith("ar") else "en"


LANG = _detect_lang(sys.argv[1:])


def T(key, **kw):
    s = S[key][0 if LANG == "ar" else 1]
    return s.format(**kw) if kw else s


# ----------------------------------------------------------------------------
# 1) Settings and requirements
# ----------------------------------------------------------------------------
APP_NAME = "MCP-Agent"
REQUIRED = {  # module name : pip spec
    "mcp": "mcp>=1.10,<2",
    "pyngrok": "pyngrok>=7.0",
    "uvicorn": "uvicorn>=0.30",
    "starlette": "starlette",
}
VENV_DIR = Path.home() / ".claude_agent_mcp" / "venv"
BOOT_FLAG = "MCP_AGENT_BOOT"
ACCESS_LEVELS = ("read-only", "operate", "full")


def log(msg):
    print(msg, flush=True)


def die(msg, code=1):
    print(f"\n{T('err')} {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ----------------------------------------------------------------------------
# 2) Arguments (parsed before any install so --help is instant)
# ----------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(description=T("desc"), formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--access", "-access", default="read-only",
                    choices=list(ACCESS_LEVELS) + ["readonly"], help=T("h_access"))
    ap.add_argument("--workspace", "-w", default=None, help=T("h_ws"))
    ap.add_argument("--port", type=int, default=8765, help=T("h_port"))
    ap.add_argument("--token", default=os.environ.get("MCP_AUTH_TOKEN"), help=T("h_token"))
    ap.add_argument("--domain", default=None, help=T("h_domain"))
    ap.add_argument("--ngrok-authtoken", default=None, help=T("h_ngtok"))
    ap.add_argument("--no-ngrok", action="store_true", help=T("h_nongrok"))
    ap.add_argument("--no-exec", action="store_true", help=T("h_noexec"))
    ap.add_argument("--max-timeout", type=int, default=600, help=T("h_timeout"))
    ap.add_argument("--lang", "-lang", default=LANG, choices=["ar", "en"], help=T("h_lang"))
    cfg = ap.parse_args()

    cfg.access = "read-only" if cfg.access == "readonly" else cfg.access

    if cfg.access == "operate" and not cfg.workspace:
        ap.error(T("e_ws_req"))

    ws = Path(cfg.workspace).expanduser() if cfg.workspace else Path.cwd()
    if cfg.access == "operate":
        ws.mkdir(parents=True, exist_ok=True)
    if not ws.exists() or not ws.is_dir():
        ap.error(T("e_ws_none", w=ws))
    cfg.workspace = ws.resolve()

    if not cfg.token:
        cfg.token = secrets.token_urlsafe(32)
    if len(cfg.token) < 16:
        ap.error(T("e_tok_short"))
    if not re.fullmatch(r"[A-Za-z0-9_\-.~]+", cfg.token):
        ap.error(T("e_tok_chars"))
    return cfg


# ----------------------------------------------------------------------------
# 3) Dependency check + venv + re-exec
# ----------------------------------------------------------------------------
def _missing_pkgs():
    return [spec for mod, spec in REQUIRED.items() if importlib.util.find_spec(mod) is None]


def _in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _venv_python():
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _pip(py, pkgs, extra=()):
    cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", *extra, *pkgs]
    return subprocess.call(cmd) == 0


def _deps_ok_in(py):
    code = "import " + ", ".join(REQUIRED.keys()) + "; from mcp.server.fastmcp import FastMCP"
    return subprocess.call([str(py), "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def _reexec(py):
    env = dict(os.environ)
    env[BOOT_FLAG] = "1"
    env["MCP_AGENT_LANG"] = LANG
    args = [str(py), os.path.abspath(__file__), *sys.argv[1:]]
    if os.name == "nt":
        sys.exit(subprocess.call(args, env=env))
    os.execve(str(py), args, env)


def _use_venv():
    py = _venv_python()
    if not py.exists():
        log(T("venv_make", d=VENV_DIR))
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
        rc = subprocess.call([sys.executable, "-m", "venv", str(VENV_DIR)])
        if rc != 0 or not py.exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            log(T("venv_fail"))
            log(T("venv_fallback"))
            if _pip(sys.executable, _missing_pkgs(), ["--user", "--break-system-packages"]):
                importlib.invalidate_caches()
                if not _missing_pkgs():
                    return
            die(T("venv_dead"))
    if not _deps_ok_in(py):
        log(T("install_venv"))
        if not _pip(py, list(REQUIRED.values())):
            die(T("pip_fail"))
    _reexec(py)


def bootstrap():
    if sys.version_info < (3, 10):
        die(T("py_old", v=sys.version.split()[0]))

    if os.environ.get(BOOT_FLAG) == "1":
        if _missing_pkgs():
            die(T("venv_still", d=VENV_DIR))
        return

    missing = _missing_pkgs()
    if not missing:
        return
    log(T("missing", l=", ".join(missing)))

    if _in_venv():  # already running inside a venv
        if not _pip(sys.executable, missing):
            die(T("pip_fail_short"))
        importlib.invalidate_caches()
        return

    if os.name != "nt":  # Linux / macOS => private venv (avoids PEP 668)
        _use_venv()
        return

    # Windows: install directly, fall back to a venv if that fails
    log(T("installing"))
    if _pip(sys.executable, missing, ["--user"]):
        importlib.invalidate_caches()
        if not _missing_pkgs():
            return
    log(T("direct_fail"))
    _use_venv()


# ----------------------------------------------------------------------------
# 4) Protection layer: Auth Token (pure ASGI, no external libs)
#    Some MCP clients cannot send custom headers, so the token can go in the URL path:
#       https://xxxx.ngrok-free.app/<TOKEN>/mcp
#    We also accept  Authorization: Bearer <TOKEN>  for clients that support it.
# ----------------------------------------------------------------------------
class AuthASGI:
    def __init__(self, app, token):
        self.app = app
        self.token = token.encode()

    async def _respond(self, send, status, body=b'{"error":"not found"}'):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        stype = scope["type"]
        if stype == "lifespan":
            return await self.app(scope, receive, send)
        if stype != "http":
            if stype == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return

        path = scope.get("path", "")
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode("latin-1")

        ok, new_path = False, path
        parts = path.split("/", 2)  # ['', first, rest]
        if len(parts) >= 2 and parts[1] and hmac.compare_digest(parts[1].encode(), self.token):
            ok = True
            new_path = "/" + (parts[2] if len(parts) > 2 else "")
            if new_path == "/":
                new_path = "/mcp"
        elif auth.lower().startswith("bearer ") and hmac.compare_digest(auth[7:].strip().encode(), self.token):
            ok = True

        if not ok:
            log(T("rejected", t=time.strftime("%H:%M:%S"), m=scope.get("method"), p=path[:40]))
            if auth:
                return await self._respond(send, 401, b'{"error":"unauthorized"}')
            return await self._respond(send, 404)

        if new_path != path:
            scope = dict(scope, path=new_path, raw_path=new_path.encode())
        await self.app(scope, receive, send)


# ----------------------------------------------------------------------------
# 5) MCP server and tools
# ----------------------------------------------------------------------------
MAX_OUT = 30000
SKIP_DIRS = {".git", "node_modules", "__pycache__", "__py_cache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


def _trunc(s, limit=MAX_OUT):
    if len(s) <= limit:
        return s
    half = limit // 2
    return s[:half] + "\n" + T("out_trunc", n=len(s) - limit) + "\n" + s[-half:]


def _is_inside(path, root):
    try:
        a = os.path.normcase(str(path))
        b = os.path.normcase(str(root))
        return os.path.commonpath([a, b]) == b
    except ValueError:  # different drives on Windows
        return False


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _exec(args, shell, cwd, timeout):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    kw = dict(cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
              text=True, encoding="utf-8", errors="replace", shell=shell, env=env)
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
        if shell:
            kw["executable"] = shutil.which("bash") or "/bin/sh"
    start = time.time()
    proc = subprocess.Popen(args, **kw)
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out, _ = proc.communicate()
    dur = time.time() - start
    head = f"[exit_code={proc.returncode}] [time={dur:.1f}s]" + (" " + T("timeout_tag", t=timeout) if timed_out else "")
    return head + "\n" + _trunc(out or "")



def _apply_unified_diff(path, patch_text):
    """Apply a strict, single-file unified diff atomically; never guess on mismatched context."""
    p = Path(path)
    raw = p.read_bytes()
    try:
        original = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("apply_patch only supports UTF-8 text files") from exc
    if "\0" in original:
        raise ValueError("apply_patch does not support binary files")

    newline = "\r\n" if "\r\n" in original else "\n"
    original = original.replace("\r\n", "\n").replace("\r", "\n")
    source_lines = original.splitlines(keepends=True)
    patch_text = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    patch_lines = patch_text.splitlines(keepends=True)

    # Accept standard unified-diff file headers, but apply only the explicitly supplied target path.
    i = 0
    if patch_lines and patch_lines[0].startswith("--- "):
        i = 1
        if i >= len(patch_lines) or not patch_lines[i].startswith("+++ "):
            raise ValueError("Unified diff has a --- header but no +++ header")
        i += 1

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)?(?:\n)?$")
    hunks = []
    while i < len(patch_lines):
        line = patch_lines[i]
        match = hunk_re.match(line)
        if not match:
            if not line.strip():
                i += 1
                continue
            raise ValueError(f"Expected a unified-diff hunk header at patch line {i + 1}")
        old_start = int(match.group(1))
        old_count = int(match.group(2) if match.group(2) is not None else 1)
        new_count = int(match.group(4) if match.group(4) is not None else 1)
        i += 1
        old_lines, new_lines = [], []
        seen_old = seen_new = 0
        while i < len(patch_lines) and not patch_lines[i].startswith("@@ "):
            body = patch_lines[i]
            if body.startswith("\\ No newline at end of file"):
                # Unified diff marks the preceding source/destination line as lacking a final newline.
                if i == 0 or patch_lines[i - 1][0] not in " +-":
                    raise ValueError("Unexpected no-newline marker in patch")
                previous_kind = patch_lines[i - 1][0]
                if previous_kind in " -":
                    if not old_lines:
                        raise ValueError("No source line before no-newline marker")
                    old_lines[-1] = old_lines[-1].removesuffix("\n")
                if previous_kind in " +":
                    if not new_lines:
                        raise ValueError("No destination line before no-newline marker")
                    new_lines[-1] = new_lines[-1].removesuffix("\n")
                i += 1
                continue
            if not body or body[0] not in " +-":
                break
            content = body[1:]
            if body[0] in " -":
                old_lines.append(content)
                seen_old += 1
            if body[0] in " +":
                new_lines.append(content)
                seen_new += 1
            i += 1
        if seen_old != old_count or seen_new != new_count:
            raise ValueError(
                f"Malformed hunk: header declares -{old_count}/+{new_count} lines, "
                f"but body contains -{seen_old}/+{seen_new}"
            )
        hunks.append((old_start, old_count, old_lines, new_lines))

    if not hunks:
        raise ValueError("Patch contains no unified-diff hunks")

    changed = list(source_lines)
    offset = 0
    for old_start, old_count, old_lines, new_lines in hunks:
        index = (old_start if old_count == 0 else old_start - 1) + offset
        if index < 0 or index > len(changed):
            raise ValueError(f"Hunk position is outside the file (old line {old_start})")
        actual = changed[index:index + old_count]
        if actual != old_lines:
            expected_text = "".join(old_lines[:4]).rstrip()
            actual_text = "".join(actual[:4]).rstrip()
            raise ValueError(
                f"Patch context mismatch near line {old_start}; file was not changed. "
                f"Expected: {expected_text!r}; found: {actual_text!r}"
            )
        changed[index:index + old_count] = new_lines
        offset += len(new_lines) - old_count

    updated = "".join(changed)
    if newline != "\n":
        updated = updated.replace("\n", newline)
    encoded = updated.encode("utf-8")

    # Write beside the destination and atomically replace it only after every hunk matches.
    mode = stat.S_IMODE(p.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".patch-tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return len(hunks), len(source_lines), len(changed)


def build_server(cfg):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        ts = TransportSecuritySettings(enable_dns_rebinding_protection=False)  # protection is our token
    except Exception:
        ts = None

    access, ws = cfg.access, cfg.workspace
    can_write = access in ("operate", "full")
    can_exec = can_write and not cfg.no_exec

    import platform
    scope_txt = {
        "read-only": "READ-ONLY: you may read any file on this machine. Writing and command execution are disabled.",
        "operate": f"OPERATE: read/write ONLY inside the workspace `{ws}`. Paths outside it are rejected.",
        "full": "FULL ACCESS: read/write/execute anywhere on this machine. Be careful and avoid destructive actions unless asked.",
    }[access]
    instructions = (
        f"Local agent server running on {platform.system()} ({platform.machine()}). {scope_txt}\n"
        f"Default working directory: {ws}. Relative paths are resolved against it.\n"
        "Workflow: explore with list_directory/find_files/search_text, read with read_file, "
        "apply_patch for contextual unified-diff edits, edit_file for small exact replacements, "
        "write_file for new or complete files, then verify with run_command."
    )

    kwargs = dict(instructions=instructions, stateless_http=True, json_response=True)
    if ts is not None:
        kwargs["transport_security"] = ts
    mcp = FastMCP(APP_NAME, **kwargs)

    # ---------------- helpers ----------------
    def resolve(p, must_exist=False):
        pth = Path(os.path.expandvars(p)).expanduser() if p else ws
        if not pth.is_absolute():
            pth = ws / pth
        pth = pth.resolve()  # resolves symlinks and ".." so the workspace cannot be escaped
        if access == "operate" and not _is_inside(pth, ws):
            raise PermissionError(T("denied_ws", w=ws))
        if must_exist and not pth.exists():
            raise FileNotFoundError(T("not_exist", p=pth))
        return pth

    def guard_delete(p):
        if p == Path(p.anchor) or p == Path.home().resolve():
            raise PermissionError(T("del_root"))
        if access == "operate" and os.path.normcase(str(p)) == os.path.normcase(str(ws)):
            raise PermissionError(T("del_ws"))

    def audited(fn):
        def short(kw):
            s = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in kw.items())
            return s[:200]
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def w(*a, **k):
                log(f"[tool] {time.strftime('%H:%M:%S')} {fn.__name__}({short(k)})")
                return await fn(*a, **k)
        else:
            @functools.wraps(fn)
            def w(*a, **k):
                log(f"[tool] {time.strftime('%H:%M:%S')} {fn.__name__}({short(k)})")
                return fn(*a, **k)
        return w

    def reg(fn, read_only=False, destructive=False, open_world=False):
        f = audited(fn)
        try:
            ann = ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive,
                                  idempotentHint=read_only, openWorldHint=open_world)
            mcp.tool(annotations=ann)(f)
        except TypeError:
            mcp.tool()(f)

    # ---------------- read tools (all levels) ----------------
    def get_access_info() -> str:
        """Show the current access level, workspace, OS and which tool groups are enabled."""
        return (f"access={access}\nworkspace={ws}\nos={platform.platform()}\n"
                f"write_enabled={can_write}\nexec_enabled={can_exec}\nhome={Path.home()}")

    def list_directory(path: str = ".", recursive: bool = False, max_entries: int = 500) -> str:
        """List files/folders in a directory. Set recursive=true for a tree-like listing (capped by max_entries)."""
        base = resolve(path, must_exist=True)
        if not base.is_dir():
            raise NotADirectoryError(str(base))
        lines = []

        def fmt(entry_path, name, is_dir):
            if is_dir:
                return f"[dir]  {name}/"
            try:
                size = os.stat(entry_path).st_size
            except OSError:
                size = "?"
            return f"[file] {name}  ({size} bytes)"

        if not recursive:
            try:
                entries = sorted(os.scandir(base), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
            except PermissionError:
                raise PermissionError(T("perm_dir", p=base))
            for e in entries:
                lines.append(fmt(e.path, e.name, e.is_dir(follow_symlinks=False)))
                if len(lines) >= max_entries:
                    lines.append(T("cap_entries", n=max_entries))
                    break
        else:
            for root, dirs, files in os.walk(base):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                rel = os.path.relpath(root, base)
                for d in dirs:
                    lines.append(f"[dir]  {os.path.normpath(os.path.join(rel, d))}/".replace("./", "", 1))
                for f_ in sorted(files):
                    lines.append(fmt(os.path.join(root, f_), os.path.normpath(os.path.join(rel, f_)), False))
                if len(lines) >= max_entries:
                    lines.append(T("cap_entries", n=max_entries))
                    break
        return f"{base}\n" + ("\n".join(lines) if lines else T("empty_dir"))

    def read_file(path: str, start_line: int = 1, max_lines: int = 2000) -> str:
        """Read a text file with line numbers (format: 'N<TAB>text'). Use start_line/max_lines to page through big files.
        Line number prefixes are NOT part of the file content."""
        p = resolve(path, must_exist=True)
        if not p.is_file():
            raise IsADirectoryError(T("not_file", p=p))
        with open(p, "rb") as fb:
            if b"\0" in fb.read(8192):
                return T("binary", n=p.stat().st_size)
        out = []
        with open(p, "r", encoding="utf-8", errors="replace", newline=None) as f:
            for i, line in enumerate(f, 1):
                if i < start_line:
                    continue
                if len(out) >= max_lines:
                    out.append(T("more_lines", n=i))
                    break
                out.append(f"{i:6d}\t{line.rstrip(chr(10))}")
        return _trunc("\n".join(out), 60000) if out else T("empty_file")

    def find_files(pattern: str, path: str = ".", max_results: int = 200) -> str:
        """Find files by glob pattern on name (e.g. '*.py') or relative path (e.g. 'src/**/*.ts'). Skips .git/node_modules/venv."""
        import fnmatch
        base = resolve(path, must_exist=True)
        res = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files + dirs:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, base).replace("\\", "/")
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
                    res.append(full)
                    if len(res) >= max_results:
                        return "\n".join(res) + "\n" + T("cap_results", n=max_results)
        return "\n".join(res) if res else T("no_results")

    def _search(pattern, path, glob, ignore_case, max_results):
        import fnmatch
        base = resolve(path, must_exist=True)
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        hits = []
        targets = [base] if base.is_file() else None
        walker = [(str(base.parent), [], [base.name])] if targets else os.walk(base)
        for root, dirs, files in walker:
            if not targets:
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if not fnmatch.fnmatch(name, glob):
                    continue
                fp = os.path.join(root, name)
                try:
                    if os.path.getsize(fp) > 2_000_000:
                        continue
                    with open(fp, "rb") as fb:
                        if b"\0" in fb.read(4096):
                            continue
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        for ln, line in enumerate(f, 1):
                            if rx.search(line):
                                hits.append(f"{fp}:{ln}: {line.strip()[:300]}")
                                if len(hits) >= max_results:
                                    return "\n".join(hits) + "\n" + T("cap_results", n=max_results)
                except OSError:
                    continue
        return "\n".join(hits) if hits else T("no_results")

    async def search_text(pattern: str, path: str = ".", glob: str = "*", ignore_case: bool = False,
                          max_results: int = 200) -> str:
        """Regex search inside text files (like grep -rn). 'glob' filters file names, e.g. '*.py'."""
        return await asyncio.to_thread(_search, pattern, path, glob, ignore_case, max_results)

    reg(get_access_info, read_only=True)
    reg(list_directory, read_only=True)
    reg(read_file, read_only=True)
    reg(find_files, read_only=True)
    reg(search_text, read_only=True)

    # ---------------- write tools (operate / full) ----------------
    if can_write:
        def write_file(path: str, content: str, create_dirs: bool = True) -> str:
            """Create or overwrite a file with the given content (UTF-8)."""
            p = resolve(path)
            if create_dirs:
                p.parent.mkdir(parents=True, exist_ok=True)
            existed = p.exists()
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            return T("replaced" if existed else "created", p=p, n=len(content))

        def edit_file(path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
            """Replace exact text in a file. old_str must match exactly once (include surrounding lines for uniqueness)
            unless replace_all=true. Do not include the line-number prefixes from read_file."""
            p = resolve(path, must_exist=True)
            with open(p, "r", encoding="utf-8", newline="") as f:
                text = f.read()
            if not old_str:
                raise ValueError(T("old_empty"))
            n = text.count(old_str)
            if n == 0:
                raise ValueError(T("old_none"))
            if n > 1 and not replace_all:
                raise ValueError(T("old_multi", n=n))
            text = text.replace(old_str, new_str) if replace_all else text.replace(old_str, new_str, 1)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            return T("edited", p=p, n=n if replace_all else 1)

        def apply_patch(path: str, patch: str) -> str:
            """Apply a strict unified diff to one existing UTF-8 text file.
            Accepts standard ---/+++ headers and one or more @@ hunks. Every hunk must match exactly;
            the file is written atomically only after all hunks validate. Paths obey the active access level."""
            p = resolve(path, must_exist=True)
            if not p.is_file():
                raise IsADirectoryError(T("not_file", p=p))
            hunks, before, after = _apply_unified_diff(p, patch)
            return f"Applied {hunks} hunk(s) to {p}; lines {before} -> {after}."

        def make_directory(path: str) -> str:
            """Create a directory (including parents)."""
            p = resolve(path)
            p.mkdir(parents=True, exist_ok=True)
            return T("done", p=p)

        def move_path(source: str, destination: str) -> str:
            """Move or rename a file/folder."""
            s, d = resolve(source, must_exist=True), resolve(destination)
            guard_delete(s)
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(s), str(d))
            return T("moved", s=s, d=d)

        def delete_path(path: str, recursive: bool = False) -> str:
            """Delete a file, or a folder (folders need recursive=true if not empty)."""
            p = resolve(path, must_exist=True)
            guard_delete(p)
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p) if recursive else p.rmdir()
            else:
                p.unlink()
            return T("deleted", p=p)

        reg(write_file, destructive=True)
        reg(edit_file, destructive=True)
        reg(apply_patch, destructive=True)
        reg(make_directory)
        reg(move_path, destructive=True)
        reg(delete_path, destructive=True)

    # ---------------- execution tools ----------------
    if can_exec:
        async def run_command(command: str, cwd: str = ".", timeout: int = 120) -> str:
            """Run a shell command (bash on Linux/macOS, cmd on Windows) and return exit code + combined output.
            Non-interactive only (stdin is closed). Long-running servers should be avoided or run with a timeout."""
            d = resolve(cwd, must_exist=True)
            if not d.is_dir():
                raise NotADirectoryError(str(d))
            t = max(1, min(int(timeout), cfg.max_timeout))
            return await asyncio.to_thread(_exec, command, True, d, t)

        async def run_python(code: str, cwd: str = ".", timeout: int = 60) -> str:
            """Execute a Python snippet in a fresh interpreter and return its output."""
            d = resolve(cwd, must_exist=True)
            py = shutil.which("python3") or shutil.which("python") or sys.executable
            t = max(1, min(int(timeout), cfg.max_timeout))
            return await asyncio.to_thread(_exec, [py, "-c", code], False, d, t)

        reg(run_command, destructive=True, open_world=True)
        reg(run_python, destructive=True, open_world=True)

    return mcp


# ----------------------------------------------------------------------------
# 6) ngrok (with automatic login flow)
# ----------------------------------------------------------------------------
AUTH_ERR = re.compile(r"4018|authtoken|authentication|ERR_NGROK_10[5-7]|not logged|credentials", re.I)


def start_tunnel(port, cfg):
    from pyngrok import ngrok
    from pyngrok.exception import PyngrokError

    tok = cfg.ngrok_authtoken or os.environ.get("NGROK_AUTHTOKEN")
    if tok:
        ngrok.set_auth_token(tok.strip())

    log(T("ng_start"))
    while True:
        try:
            opts = {}
            if cfg.domain:
                opts["domain"] = cfg.domain
            tunnel = ngrok.connect(port, "http", **opts)
            url = tunnel.public_url
            return url.replace("http://", "https://", 1) if url.startswith("http://") else url
        except PyngrokError as e:
            msg = str(e)
            try:
                ngrok.kill()
            except Exception:
                pass
            if AUTH_ERR.search(msg):
                log(T("ng_nologin"))
                log(T("ng_s1"))
                log(T("ng_s2"))
                if not sys.stdin or not sys.stdin.isatty():
                    die(T("ng_notty"))
                try:
                    t = input(T("ng_prompt")).strip()
                except (EOFError, KeyboardInterrupt):
                    die(T("ng_cancel"))
                if not t:
                    input(T("ng_wait"))
                else:
                    try:
                        ngrok.set_auth_token(t)  # saved in the ngrok config, so it is not asked again
                        log(T("ng_saved"))
                    except PyngrokError as e2:
                        log(T("ng_bad", e=e2))
                continue
            if "108" in msg or "simultaneous" in msg.lower():
                die(T("ng_108", m=msg))
            die(T("ng_fail", m=msg))


# ----------------------------------------------------------------------------
# 7) Run
# ----------------------------------------------------------------------------
def pick_port(preferred):
    for p in (preferred, 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    die(T("no_port"))


def run(cfg):
    import uvicorn

    server = build_server(cfg)
    app = AuthASGI(server.streamable_http_app(), cfg.token)
    port = pick_port(cfg.port)

    public = None
    if not cfg.no_ngrok:
        public = start_tunnel(port, cfg)

    base = public or f"http://127.0.0.1:{port}"
    desc = {"read-only": T("lvl_ro"),
            "operate": T("lvl_op", w=cfg.workspace),
            "full": T("lvl_full")}[cfg.access]
    line = "=" * 74
    log(f"\n{line}\n  {T('b_ready')}\n{line}")
    log(T("b_access", a=cfg.access, d=desc))
    log(T("b_exec", s=T("on") if (cfg.access != "read-only" and not cfg.no_exec) else T("off")))
    log(T("b_ws", w=cfg.workspace))
    log(T("b_url", u=f"{base}/{cfg.token}/mcp"))
    log(T("b_tok", t=cfg.token))
    log(T("b_how1"))
    log(T("b_how2"))
    log(T("b_how3"))
    log(T("b_hdr", b=base))
    if cfg.access == "operate" and not cfg.no_exec:
        log(T("b_w_op1"))
        log(T("b_w_op2"))
    log(T("b_warn"))
    log(line + "\n")

    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        if public:
            try:
                from pyngrok import ngrok
                ngrok.kill()
            except Exception:
                pass
        log(T("stopped"))


def main():
    cfg = parse_args()
    bootstrap()
    run(cfg)


if __name__ == "__main__":
    main()
