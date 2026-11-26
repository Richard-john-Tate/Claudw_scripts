#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laravel_map.py - explore, explain and visualise a Laravel codebase and its Docker dev environment.

It reads the project's source (no app boot needed) and writes a set of linked HTML pages:

  index.html      Overview: what the app is, its stack, an architecture diagram, where to start reading
  start.html      Getting started: how to boot the Docker env, URLs/ports, scripts, CI, your local status
  changes.html    What changed: since your last run or --since <ref|date>, plus a catch-up checklist
  routes.html     Every route (web/api/admin/Filament/package), as a table, a URI tree and per controller
  http.html       Controllers, middleware, form requests, API resources and the request lifecycle
  trace.html      Request traces: follow a route/command/job/component through every method it reaches,
                  with the tables it reads and writes, jobs, events, mail and external calls ("who calls" too)
  models.html     Eloquent models, their relationships, casts, scopes, observers and policies
  database.html   Schema rebuilt from migrations (ER diagram), tables, migration timeline
  events.html     Events, listeners, jobs, mail, notifications, scheduled tasks, commands, channels
  frontend.html   Blade views & components, Inertia pages, assets, plus a view graph
  livewire.html   Livewire / Volt components, their actions, events and where they are used (if present)
  filament.html   Filament panels, resources, pages, widgets and the URLs they create (if present)
  classes.html    Every class by role, with an interactive dependency graph
  docker.html     Docker compose services, how they connect, Dockerfiles, ports, volumes
  config.html     Environment variables -> config keys, packages (composer / npm) explained
  insights.html   Health checks, hotspots, who-knows-what, TODOs, risky patterns
  data.json       Everything above as JSON (handy for other tools / LLMs)

Where the HTML goes:
  python3 laravel_map.py                 run inside a Laravel repo -> <repo>/laravel-map/
  python3 laravel_map.py ~/code/shop     path given -> ./shop-map/ in the directory you run it from
  python3 laravel_map.py PATH -o DIR     anywhere you like
The output folder gets its own ".gitignore" containing "*", so git ignores it without touching any tracked file.

Usage:
  python3 laravel_map.py [PROJECT_DIR] [options]

  --since REF_OR_DATE   compare against a branch/tag/sha or a date ("2026-09-01", "3 weeks ago").
                        Without it, each run compares with the previous run (snapshots are kept in the output folder).
  --artisan [auto|CMD]  enrich with live data from `php artisan` (auto-detects Sail / docker compose / local PHP)
  --db                  with --artisan, also read real columns via `artisan model:show`
  --editor NAME         clickable file references: auto (default), vscode, cursor, phpstorm, idea,
                        sublime, zed, none, or a template like "myeditor://open?file={path}&line={line}"
  --offline             bundle Mermaid and d3 next to the pages so diagrams work without internet
  -o / --out DIR        output directory
  --open                open index.html in a browser when done

Only the Python 3.8+ standard library is required (PyYAML is used for compose files if installed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import webbrowser
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "1.0.0"
OUT_DIR_NAME = "laravel-map"
SKIP_DIRS = {"vendor", "node_modules", ".git", ".idea", ".vscode", ".fleet", ".phpunit.cache", ".cache",
             "coverage", ".nuxt", ".next", ".output", ".pnpm-store", ".yarn", OUT_DIR_NAME}
SKIP_REL = {"storage", "bootstrap/cache", "public/build", "public/vendor", "public/hot", "public/js", "public/css"}
MAX_FILE_BYTES = 1_500_000
SECRET_HINT = re.compile(r"(PASS|SECRET|TOKEN|KEY|PRIVATE|CREDENTIAL|AUTH|SALT|DSN|WEBHOOK)", re.I)


# =====================================================================================================
# 1. Small utilities
# =====================================================================================================

def log(msg):
    print(f"  {msg}", file=sys.stderr)


def read_text(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def sha1(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def run(cmd, cwd=None, timeout=60, env=None):
    """Run a command; never raises. Returns (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           shell=isinstance(cmd, str), encoding="utf-8", errors="replace", env=env)
        return p.returncode, p.stdout or "", p.stderr or ""
    except (OSError, subprocess.SubprocessError, ValueError) as ex:
        return 127, "", str(ex)


def mask(key, value):
    """Hide values that look like secrets (by key name); never echo real credentials into HTML."""
    if value is None:
        return None
    value = str(value)
    if value == "" or value.lower() in ("null", "false", "true"):
        return value
    if SECRET_HINT.search(key or ""):
        return "•••" if not value.startswith("${") else value
    return value


def short(fqn):
    return (fqn or "").rsplit("\\", 1)[-1]


def ns_of(fqn):
    return fqn.rsplit("\\", 1)[0] if fqn and "\\" in fqn else ""


UNCOUNTABLE = {"audio", "bison", "cattle", "chassis", "compensation", "data", "deer", "education", "emoji",
               "equipment", "evidence", "feedback", "firmware", "fish", "furniture", "gold", "hardware",
               "information", "jedi", "kin", "knowledge", "love", "metadata", "money", "moose", "news",
               "nutrition", "offspring", "plankton", "police", "rain", "rice", "series", "sheep",
               "software", "species", "swine", "traffic", "wheat", "staff", "media", "settings"}
IRREGULAR = {"person": "people", "man": "men", "woman": "women", "child": "children", "tooth": "teeth",
             "foot": "feet", "mouse": "mice", "goose": "geese", "ox": "oxen", "leaf": "leaves",
             "life": "lives", "knife": "knives", "wife": "wives", "half": "halves", "criterion": "criteria",
             "analysis": "analyses", "index": "indices", "matrix": "matrices", "vertex": "vertices",
             "axis": "axes", "crisis": "crises", "thesis": "theses", "medium": "media", "datum": "data",
             "cactus": "cacti", "focus": "foci", "fungus": "fungi", "nucleus": "nuclei", "syllabus": "syllabi",
             "move": "moves", "sex": "sexes", "zombie": "zombies", "cookie": "cookies", "movie": "movies"}
IRREGULAR_REV = {v: k for k, v in IRREGULAR.items()}


def plural(word):
    if not word:
        return word
    low = word.lower()
    if low in UNCOUNTABLE:
        return word
    if low in IRREGULAR:
        p = IRREGULAR[low]
        return p if word.islower() else p[0].upper() + p[1:]
    if re.search(r"[^aeiou]y$", low):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", low):
        return word + "es"
    return word + "s"


def singular(word):
    if not word:
        return word
    low = word.lower()
    if low in UNCOUNTABLE:
        return word
    if low in IRREGULAR_REV:
        return IRREGULAR_REV[low]
    if low.endswith("ies") and len(low) > 3:
        return word[:-3] + "y"
    if re.search(r"(ss|x|z|ch|sh|ses)es$", low) or re.search(r"(ch|sh|x|z)es$", low):
        return word[:-2]
    if low.endswith("sses"):
        return word[:-2]
    if low.endswith("s") and not low.endswith("ss"):
        return word[:-1]
    return word


def snake(s, sep="_"):
    s = re.sub(r"\s+", "", s or "")
    return re.sub(r"(.)(?=[A-Z])", r"\1" + sep, s).lower()


def kebab(s):
    return snake(s, "-")


def plural_studly(s):
    parts = re.split(r"(?=[A-Z])", s)
    parts = [p for p in parts if p]
    if not parts:
        return s
    parts[-1] = plural(parts[-1])
    return "".join(parts)


def table_for_model(cls_short):
    return snake(plural_studly(cls_short))


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def rel_time(iso):
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        d = dt.datetime.now(dt.timezone.utc) - t
        s = d.total_seconds()
        if s < 3600:
            return f"{int(s // 60)} min ago"
        if s < 86400:
            return f"{int(s // 3600)} h ago"
        if s < 86400 * 60:
            return f"{int(s // 86400)} days ago"
        return f"{int(s // (86400 * 30))} months ago"
    except (ValueError, AttributeError):
        return ""


def walk(root, subdir="", exts=None, max_depth=None):
    """Yield (abs_path, rel_path) for files under root/subdir, skipping vendor & friends."""
    base = os.path.join(root, subdir) if subdir else root
    if not os.path.isdir(base):
        return
    base_depth = base.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dirnames:
            r = f"{rel_dir}/{d}" if rel_dir else d
            if d in SKIP_DIRS or r in SKIP_REL or d.startswith(".") and d not in (".github", ".docker", ".devcontainer"):
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)
        if max_depth is not None and dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
        for f in sorted(filenames):
            if exts and not any(f.endswith(x) for x in exts):
                continue
            ap = os.path.join(dirpath, f)
            yield ap, (f"{rel_dir}/{f}" if rel_dir else f)


# =====================================================================================================
# 2. PHP tokenizer and expression parser (just enough PHP to read Laravel code reliably)
# =====================================================================================================

_TOKEN_RE = re.compile(r"""
   (?P<ws>\s+)
  |(?P<doc>/\*\*.*?\*/)
  |(?P<comment>/\*.*?\*/|//[^\n]*|\#(?!\[)[^\n]*)
  |(?P<heredoc><<<[ \t]*(?P<hq>['"]?)(?P<hid>[A-Za-z_]\w*)(?P=hq)\r?\n.*?\r?\n[ \t]*(?P=hid)\b)
  |(?P<sq>'(?:[^'\\]|\\.)*')
  |(?P<dq>"(?:[^"\\]|\\.)*")
  |(?P<var>\$[A-Za-z_\x80-￿][\w\x80-￿]*)
  |(?P<name>\\?[A-Za-z_\x80-￿][\w\x80-￿]*(?:\\[A-Za-z_\x80-￿][\w\x80-￿]*)*)
  |(?P<num>0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)
  |(?P<op><\?php|<\?=|\?>|\?->|->|::|=>|\.\.\.|\?\?=|\?\?|===|!==|<=>|==|!=|<=|>=|&&|\|\||\+\+|--|\.=|\+=|-=|\*=|/=|\#\[|.)
""", re.S | re.X)

PHP_KEYWORDS = {"if", "elseif", "else", "while", "do", "for", "foreach", "switch", "case", "default", "catch",
                "finally", "try", "array", "list", "isset", "empty", "unset", "echo", "print", "return", "fn",
                "function", "match", "exit", "die", "eval", "include", "include_once", "require",
                "require_once", "new", "clone", "throw", "yield", "static", "self", "parent", "use",
                "global", "declare", "and", "or", "xor", "instanceof", "insteadof", "as", "class",
                "interface", "trait", "enum", "extends", "implements", "public", "private", "protected",
                "abstract", "final", "readonly", "const", "namespace", "goto", "break", "continue", "var"}
BUILTIN_TYPES = {"int", "integer", "string", "bool", "boolean", "float", "double", "array", "callable",
                 "iterable", "object", "mixed", "void", "null", "never", "false", "true", "self", "static",
                 "parent", "resource"}
CASTS = {"int", "integer", "bool", "boolean", "float", "double", "real", "string", "array", "object", "unset",
         "binary"}
BINOPS = {".", "??", "+", "-", "*", "/", "%", "||", "&&", "|", "&", "^", "==", "===", "!=", "!==", "<", ">",
          "<=", ">=", "<=>", "and", "or", "xor", "instanceof", "=", ".=", "+=", "-=", "*=", "/=", "??="}
EXPR_STOP = {",", ";", ")", "]", "}", "=>", ":"}


class Tok:
    __slots__ = ("k", "v", "line", "doc")

    def __init__(self, k, v, line, doc=None):
        self.k, self.v, self.line, self.doc = k, v, line, doc

    def __repr__(self):
        return f"{self.k}:{self.v}@{self.line}"


def _php_unescape(raw, dq):
    body = raw[1:-1]
    if not dq:
        return body.replace("\\\\", "\0").replace("\\'", "'").replace("\0", "\\")
    return (body.replace("\\\\", "\0").replace('\\"', '"').replace("\\$", "$").replace("\\n", "\n")
            .replace("\\t", "\t").replace("\0", "\\"))


def tokenize(text):
    toks, line, last, doc = [], 1, 0, None
    for m in _TOKEN_RE.finditer(text):
        k, s = m.lastgroup, m.start()
        line += text.count("\n", last, s)
        last = s
        if k in ("ws", "comment"):
            continue
        v = m.group()
        if k == "doc":
            doc = v
            continue
        if k == "sq":
            k, v = "str", _php_unescape(v, False)
        elif k == "dq":
            k, v = "str", _php_unescape(v, True)
        elif k == "heredoc":
            body = v.split("\n", 1)[1] if "\n" in v else ""
            k, v = "str", body.rsplit("\n", 1)[0]
        elif k in ("hq", "hid"):
            continue
        elif k == "op" and v in ("<?php", "?>", "<?="):
            continue
        toks.append(Tok(k, v, line, doc))
        doc = None
    return toks


def bracket_map(toks):
    pair, stack = {}, []
    opens = {"(": ")", "[": "]", "{": "}", "#[": "]"}
    for i, t in enumerate(toks):
        if t.k != "op":
            continue
        if t.v in opens:
            stack.append(i)
        elif t.v in (")", "]", "}"):
            j = len(stack) - 1
            while j >= 0 and opens[toks[stack[j]].v] != t.v:
                j -= 1
            if j >= 0:
                o = stack[j]
                del stack[j:]
                pair[o] = i
                pair[i] = o
    return pair


class Cls(str):
    """A resolved class reference such as  App\\Models\\User::class."""


class PathStr(str):
    """A path we resolved from base_path()/database_path()/… ; remembers the original expression for display."""
    src = ""


DISPLAY_ROOT = {"path": None}


class Node:
    """A PHP expression we could not (or chose not to) reduce to a plain Python value."""
    __slots__ = ("type", "name", "cls", "args", "kw", "base", "calls", "start", "end", "params", "text",
                 "line", "arrow")

    def __init__(self, type, **kw):
        self.type = type
        for k in Node.__slots__[1:]:
            setattr(self, k, kw.get(k))

    def __repr__(self):
        if self.text:
            return self.text
        if self.type == "call":
            return f"{self.name}(…)"
        if self.type == "static":
            return f"{short(self.cls)}::{self.name}(…)"
        if self.type == "const":
            return f"{short(self.cls)}::{self.name}" if self.cls else str(self.name)
        if self.type == "new":
            return f"new {short(self.cls)}(…)"
        if self.type == "closure":
            return "Closure"
        if self.type == "var":
            return self.name
        if self.type == "chain":
            return repr(self.base) + "".join(f"->{c.name}(…)" for c in self.calls)
        return self.type


class Call:
    __slots__ = ("name", "args", "kw", "line", "prop")

    def __init__(self, name, args, kw, line, prop=False):
        self.name, self.args, self.kw, self.line, self.prop = name, args or [], kw or {}, line, prop


class ParseError(Exception):
    pass


def chain_root(v):
    """For  Route::prefix('x')->middleware('y')  return (root_static_node, [Call...] incl. root)."""
    if isinstance(v, Node) and v.type == "chain":
        root, calls = v.base, list(v.calls)
    else:
        root, calls = v, []
    if isinstance(root, Node) and root.type == "static":
        return root, [Call(root.name, root.args, root.kw, root.line)] + calls
    return root, calls


def fmt_val(v, depth=0):
    """Readable PHP-ish rendering of a parsed value."""
    if isinstance(v, Cls):
        return f"{short(v)}::class"
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, PathStr) and v.src:
        return v.src
    if isinstance(v, str):
        root = DISPLAY_ROOT["path"]
        if root and root in v:
            v = v.replace(root.rstrip("/") + "/", "").replace(root, ".")
        return "'" + v + "'"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        inner = ", ".join(fmt_val(x, depth + 1) for x in v[:12])
        return "[" + inner + (", …" if len(v) > 12 else "") + "]"
    if isinstance(v, dict):
        items = list(v.items())
        inner = ", ".join(f"{fmt_val(k) if not isinstance(k, int) else k} => {fmt_val(x, depth + 1)}"
                          for k, x in items[:10])
        return "[" + inner + (", …" if len(items) > 10 else "") + "]"
    return repr(v)


def plain(v):
    """JSON-friendly copy of a parsed value."""
    if isinstance(v, Cls):
        return str(v)
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    return repr(v)


def strs(v):
    """Flatten a value into the list of strings it holds (for middleware lists, $fillable etc.)."""
    if isinstance(v, str):
        return [str(v)]
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(strs(x))
        return out
    if isinstance(v, dict):
        out = []
        for x in v.values():
            out.extend(strs(x))
        return out
    return []


class ClassInfo:
    def __init__(self):
        self.name = None
        self.fqn = None
        self.kind = "class"
        self.abstract = False
        self.final = False
        self.extends = None
        self.implements = []
        self.traits = []
        self.attrs = []
        self.props = {}
        self.constants = {}
        self.cases = {}
        self.methods = {}
        self.doc = ""
        self.line = 0
        self.end_line = 0
        self.body = None
        self.file = None
        self.role = "other"
        self.refs = set()


class MethodInfo:
    def __init__(self, name):
        self.name = name
        self.visibility = "public"
        self.static = False
        self.abstract = False
        self.params = []
        self.returns = ""
        self.attrs = []
        self.line = 0
        self.end_line = 0
        self.body = None
        self.doc = ""
        self.rawdoc = ""
        self._scan = None


def doc_summary(doc):
    if not doc:
        return ""
    lines = []
    for ln in doc.strip("/*").splitlines():
        ln = ln.strip().lstrip("*").strip()
        if not ln:
            if lines:
                break
            continue
        if ln.startswith("@"):
            break
        lines.append(ln)
    return " ".join(lines)[:300]


class BodyScan:
    __slots__ = ("refs", "calls", "statics", "mcalls", "news")

    def __init__(self):
        self.refs = set()      # (fqn, how)
        self.calls = []        # (function, first_string_arg, line)
        self.statics = []      # (fqn, method, first_string_arg, line)
        self.mcalls = []       # (method, first_string_arg, line, receiver)
        self.news = []         # (fqn, line)


class PhpFile:
    """A parsed PHP file: namespace, imports, classes, plus an expression parser bound to it."""

    def __init__(self, path, rel, text, root):
        self.path, self.rel, self.root = path, rel, root
        self.dir = os.path.dirname(path)
        self.text = text
        self.lines = text.count("\n") + 1
        self.toks = tokenize(text)
        self.pair = bracket_map(self.toks)
        self.namespace = ""
        self.uses = {}
        self.classes = []
        self._cur = None
        self._cur_parent = None
        try:
            self._parse_structure()
        except (IndexError, KeyError, ParseError):
            pass

    # ---- names -----------------------------------------------------------------------------------
    def resolve(self, name):
        if not name:
            return name
        if name.startswith("\\"):
            return name[1:]
        low = name.lower()
        if low in ("self", "static") and self._cur:
            return self._cur
        if low == "parent" and self._cur_parent:
            return self._cur_parent
        if "\\" in name:
            first, rest = name.split("\\", 1)
            if first in self.uses:
                return self.uses[first] + "\\" + rest
            if first.lower() == "namespace":
                return f"{self.namespace}\\{rest}" if self.namespace else rest
        elif name in self.uses:
            return self.uses[name]
        return f"{self.namespace}\\{name}" if self.namespace else name

    def type_name(self, v):
        return v.lower() if v.lower() in BUILTIN_TYPES else self.resolve(v)

    # ---- structure -------------------------------------------------------------------------------
    def _skip_to(self, k, ch, e):
        T = self.toks
        while k < e:
            t = T[k]
            if t.k == "op":
                if t.v == ch:
                    return k
                if t.v in ("(", "[", "{", "#["):
                    k = self.pair.get(k, k) + 1
                    continue
            k += 1
        return e

    def _split(self, s, e, sep=","):
        out, a, k, T = [], s, s, self.toks
        while k < e:
            t = T[k]
            if t.k == "op":
                if t.v in ("(", "[", "{", "#["):
                    k = self.pair.get(k, k) + 1
                    continue
                if t.v == sep:
                    out.append((a, k))
                    a = k + 1
            k += 1
        if a < e:
            out.append((a, e))
        return out

    def _find(self, s, e, op):
        k, T = s, self.toks
        while k < e:
            t = T[k]
            if t.k == "op":
                if t.v == op:
                    return k
                if t.v in ("(", "[", "{", "#["):
                    k = self.pair.get(k, k) + 1
                    continue
            k += 1
        return None

    def _parse_structure(self):
        T, n, i = self.toks, len(self.toks), 0
        attrs, mods, start = [], [], None
        while i < n:
            t = T[i]
            if t.k == "name":
                low = t.v.lower()
                if low == "namespace" and i + 1 < n and T[i + 1].k == "name":
                    self.namespace = T[i + 1].v.lstrip("\\")
                    i += 2
                    continue
                if low == "use" and i + 1 < n and T[i + 1].k == "name" and not (i > 0 and T[i - 1].v == ")"):
                    i = self._parse_use(i + 1)
                    continue
                if low in ("abstract", "final", "readonly"):
                    mods.append(low)
                    start = i if start is None else start
                    i += 1
                    continue
                if low in ("class", "interface", "trait", "enum") and not (i > 0 and T[i - 1].v == "::"):
                    anon = (i > 0 and T[i - 1].k == "name" and T[i - 1].v.lower() == "new") or \
                           (start is not None and start > 0 and T[start - 1].k == "name" and T[start - 1].v.lower() == "new")
                    if anon or (i + 1 < n and T[i + 1].k == "name"):
                        i = self._parse_class(i, low, mods, attrs, i if start is None else start, anon)
                        attrs, mods, start = [], [], None
                        continue
            elif t.k == "op" and t.v == "#[":
                j = self.pair.get(i, i)
                attrs.extend(self._parse_attrs(i, j))
                start = i if start is None else start
                i = j + 1
                continue
            attrs, mods, start = [], [], None
            i += 1

    def _parse_use(self, i):
        T, n = self.toks, len(self.toks)
        if T[i].v.lower() in ("function", "const"):
            return self._skip_to(i, ";", n) + 1
        while i < n and T[i].k == "name":
            base = T[i].v.lstrip("\\")
            i += 1
            if i + 1 < n and T[i].v == "\\" and T[i + 1].v == "{":
                close = self.pair.get(i + 1, i + 1)
                j = i + 2
                while j < close:
                    if T[j].k == "name":
                        full, alias = f"{base}\\{T[j].v}", T[j].v.split("\\")[-1]
                        if j + 2 < close and T[j + 1].k == "name" and T[j + 1].v.lower() == "as":
                            alias = T[j + 2].v
                            j += 2
                        self.uses[alias] = full
                    j += 1
                i = close + 1
            else:
                alias = base.split("\\")[-1]
                if i + 1 < n and T[i].k == "name" and T[i].v.lower() == "as":
                    alias = T[i + 1].v
                    i += 2
                self.uses[alias] = base
            if i < n and T[i].v == ",":
                i += 1
                continue
            break
        return self._skip_to(i, ";", n) + 1

    def _parse_attrs(self, i, j):
        out, T, k = [], self.toks, i + 1
        while k < j:
            if T[k].k == "name":
                name = self.resolve(T[k].v)
                args, kw = [], {}
                if k + 1 < j and T[k + 1].v == "(":
                    close = self.pair.get(k + 1, k + 1)
                    args, kw = self.args(k + 2, close)
                    k = close
                out.append({"name": name, "args": args, "kw": kw})
            k += 1
        return out

    def _parse_class(self, i, kind, mods, attrs, start, anon):
        T, n = self.toks, len(self.toks)
        c = ClassInfo()
        c.kind, c.abstract, c.final, c.attrs = kind, "abstract" in mods, "final" in mods, attrs
        c.line, c.doc = T[start].line, doc_summary(T[start].doc or T[i].doc)
        j = i + 1
        if anon:
            if j < n and T[j].v == "(":
                j = self.pair.get(j, j) + 1
        else:
            c.name = T[j].v
            j += 1
            c.fqn = f"{self.namespace}\\{c.name}" if self.namespace else c.name
        while j < n and not (T[j].k == "op" and T[j].v == "{"):
            tv = T[j].v.lower() if T[j].k == "name" else T[j].v
            if tv == "extends":
                j += 1
                while j < n and T[j].k == "name" and T[j].v.lower() != "implements":
                    parent = self.resolve(T[j].v)
                    if c.extends is None:
                        c.extends = parent
                    else:
                        c.implements.append(parent)
                    j += 1
                    if j < n and T[j].v == ",":
                        j += 1
                continue
            if tv == "implements":
                j += 1
                while j < n and T[j].k == "name":
                    c.implements.append(self.resolve(T[j].v))
                    j += 1
                    if j < n and T[j].v == ",":
                        j += 1
                continue
            j += 1
        if j >= n:
            return n
        close = self.pair.get(j, n - 1)
        c.body, c.end_line, c.file = (j, close), T[close].line, self
        self._cur, self._cur_parent = c.fqn, c.extends
        try:
            self._parse_members(c, j + 1, close)
        finally:
            self._cur = self._cur_parent = None
        self.classes.append(c)
        return close + 1

    def _parse_members(self, c, s, e):
        T, k = self.toks, s
        attrs, mods, start = [], [], None
        while k < e:
            t = T[k]
            if t.k == "op" and t.v == "#[":
                close = self.pair.get(k, k)
                attrs += self._parse_attrs(k, close)
                start = k if start is None else start
                k = close + 1
                continue
            if t.k == "name":
                low = t.v.lower()
                if low == "use":
                    k += 1
                    while k < e and T[k].k == "name":
                        c.traits.append(self.resolve(T[k].v))
                        k += 1
                        if k < e and T[k].v == ",":
                            k += 1
                    k = self.pair.get(k, k) + 1 if k < e and T[k].v == "{" else self._skip_to(k, ";", e) + 1
                    attrs, mods, start = [], [], None
                    continue
                if low in ("public", "protected", "private", "static", "abstract", "final", "readonly", "var"):
                    mods.append(low)
                    start = k if start is None else start
                    k += 1
                    continue
                if low == "const":
                    k += 1
                    if k + 1 < e and T[k].k == "name" and T[k + 1].k == "name":
                        k += 1
                    while k < e and T[k].k == "name":
                        cname = T[k].v
                        k += 1
                        if k < e and T[k].v == "=":
                            val, k = self.value(k + 1, e)
                            c.constants[cname] = val
                        if k < e and T[k].v == ",":
                            k += 1
                            continue
                        break
                    k = self._skip_to(k, ";", e) + 1
                    attrs, mods, start = [], [], None
                    continue
                if low == "case" and c.kind == "enum" and k + 1 < e:
                    cname, val = T[k + 1].v, None
                    k += 2
                    if k < e and T[k].v == "=":
                        val, k = self.value(k + 1, e)
                    c.cases[cname] = val
                    k = self._skip_to(k, ";", e) + 1
                    continue
                if low == "function":
                    k = self._parse_method(c, k, e, mods, attrs, k if start is None else start)
                    attrs, mods, start = [], [], None
                    continue
            if t.k == "var":
                ptype = []
                b = k - 1
                while b >= s and T[b].k in ("name", "op") and T[b].v.lower() not in (
                        "public", "protected", "private", "static", "readonly", "var", ";", "}", "{"):
                    if T[b].k == "name":
                        ptype.insert(0, self.type_name(T[b].v))
                    b -= 1
                while k < e and T[k].k == "var":
                    pname, line = T[k].v[1:], T[k].line
                    k += 1
                    val, has = None, False
                    if k < e and T[k].v == "=":
                        val, k = self.value(k + 1, e)
                        has = True
                    c.props[pname] = {"value": val, "has_default": has, "static": "static" in mods,
                                      "visibility": next((m for m in mods if m in ("public", "protected", "private")), "public"),
                                      "type": "|".join(ptype), "line": line, "attrs": attrs,
                                      "doc": (T[start].doc if start is not None else T[k - 1].doc) or ""}
                    if k < e and T[k].v == ",":
                        k += 1
                        continue
                    break
                k = self._skip_to(k, ";", e) + 1
                attrs, mods, start = [], [], None
                continue
            k += 1

    def _parse_method(self, c, k, e, mods, attrs, start):
        T = self.toks
        k += 1
        if k < e and T[k].v == "&":
            k += 1
        m = MethodInfo(T[k].v)
        k += 1
        m.line, m.doc, m.attrs = T[start].line, doc_summary(T[start].doc), attrs
        m.rawdoc = T[start].doc or ""
        m.visibility = next((x for x in mods if x in ("public", "protected", "private")), "public")
        m.static, m.abstract = "static" in mods, "abstract" in mods
        if k < e and T[k].v == "(":
            pc = self.pair.get(k, k)
            m.params = self._parse_params(k + 1, pc)
            k = pc + 1
        if k < e and T[k].v == ":":
            k += 1
            rt = []
            while k < e and not (T[k].k == "op" and T[k].v in ("{", ";")):
                if T[k].k == "name":
                    rt.append(self.type_name(T[k].v))
                k += 1
            m.returns = "|".join(rt)
        if k < e and T[k].v == "{":
            bc = self.pair.get(k, k)
            m.body, m.end_line = (k + 1, bc), T[bc].line
            k = bc + 1
        else:
            m.end_line = m.line
            k = self._skip_to(k, ";", e) + 1
        c.methods[m.name] = m
        if m.name == "__construct":
            for p in m.params:
                if p["promoted"] and p["name"]:
                    c.props[p["name"]] = {"value": p["default"], "has_default": p["default"] is not None,
                                          "static": False, "visibility": p["promoted"], "type": p["type"],
                                          "line": m.line, "attrs": p["attrs"], "promoted": True}
        return k

    def _parse_params(self, s, e):
        T, params = self.toks, []
        for a, b in self._split(s, e, ","):
            p = {"name": None, "type": "", "types": [], "default": None, "promoted": None, "attrs": [],
                 "variadic": False}
            k = a
            while k < b:
                t = T[k]
                if t.k == "op" and t.v == "#[":
                    close = self.pair.get(k, k)
                    p["attrs"] += self._parse_attrs(k, close)
                    k = close + 1
                    continue
                if t.k == "name" and t.v.lower() in ("public", "protected", "private"):
                    p["promoted"] = t.v.lower()
                elif t.k == "name" and t.v.lower() == "readonly":
                    p["promoted"] = p["promoted"] or "public"
                elif t.k == "name":
                    p["types"].append(self.type_name(t.v))
                elif t.k == "op" and t.v == "...":
                    p["variadic"] = True
                elif t.k == "var":
                    p["name"] = t.v[1:]
                    if k + 1 < b and T[k + 1].v == "=":
                        p["default"], _ = self.value(k + 2, b)
                    break
                k += 1
            p["type"] = "|".join(p["types"])
            params.append(p)
        return params

    # ---- expressions -----------------------------------------------------------------------------
    def text_of(self, i, j):
        out, prev = [], None
        for t in self.toks[i:j]:
            v = repr(t.v) if t.k == "str" else t.v
            if prev is not None and not (t.v in ("->", "?->", "::", "(", ")", "[", "]", ",", ";") or
                                         prev in ("->", "?->", "::", "(", "[", "!", "#[")):
                out.append(" ")
            out.append(v)
            prev = t.v
        s = "".join(out)
        return s if len(s) <= 400 else s[:397] + "…"

    def value(self, i, e):
        """Parse the expression at token i (bounded by e). Returns (value, next_index)."""
        if i >= e:
            return None, i
        try:
            return self._binary(i, e)
        except (ParseError, IndexError, KeyError, TypeError, RecursionError):
            j = self._skip_expr(i, e)
            return Node("raw", text=self.text_of(i, j)), j

    def _skip_expr(self, i, e):
        k, T = i, self.toks
        while k < e:
            t = T[k]
            if t.k == "op":
                if t.v in EXPR_STOP:
                    return k
                if t.v in ("(", "[", "{", "#["):
                    k = self.pair.get(k, k) + 1
                    continue
            k += 1
        return e

    def _binary(self, i, e):
        T = self.toks
        left, j = self._unary(i, e)
        while j < e:
            t = T[j]
            op = t.v if t.k == "op" else (t.v.lower() if t.k == "name" and t.v.lower() in ("and", "or", "xor", "instanceof") else None)
            if op is None:
                break
            if op == "?":
                if j + 1 < e and T[j + 1].v == ":":
                    _, k = self._binary(j + 2, e)
                else:
                    _, k = self._binary(j + 1, e)
                    if k < e and T[k].v == ":":
                        _, k = self._binary(k + 1, e)
                left, j = Node("raw", text=self.text_of(i, k)), k
                continue
            if op in BINOPS:
                right, k = self._binary(j + 1, e)
                if op == "." and isinstance(left, (str, int, float)) and isinstance(right, (str, int, float)) \
                        and not isinstance(left, bool) and not isinstance(right, bool):
                    left = f"{left}{right}"
                else:
                    left = Node("raw", text=self.text_of(i, k))
                j = k
                continue
            break
        return left, j

    def _unary(self, i, e):
        T = self.toks
        t = T[i]
        if t.k == "op":
            if t.v == "-" and i + 1 < e and T[i + 1].k == "num":
                v, j = self._postfix(i + 1, e)
                return (-v if isinstance(v, (int, float)) else v), j
            if t.v in ("!", "-", "+", "~", "&"):
                _, j = self._unary(i + 1, e)
                return Node("raw", text=self.text_of(i, j)), j
            if t.v == "@":
                return self._unary(i + 1, e)
            if t.v == "(" and i + 2 < e and T[i + 1].k == "name" and T[i + 1].v.lower() in CASTS and T[i + 2].v == ")":
                return self._unary(i + 3, e)
        if t.k == "name" and t.v.lower() in ("clone", "print", "yield", "throw", "include", "require",
                                             "include_once", "require_once"):
            return self._unary(i + 1, e)
        return self._postfix(i, e)

    def _postfix(self, i, e):
        T = self.toks
        v, j = self._primary(i, e)
        calls = []
        while j < e:
            t = T[j]
            if t.k == "op" and t.v in ("->", "?->") and j + 1 < e:
                nx = T[j + 1]
                if nx.k == "name":
                    j += 2
                    if j < e and T[j].v == "(":
                        close = self.pair.get(j, j)
                        args, kw = self.args(j + 1, close)
                        calls.append(Call(nx.v, args, kw, nx.line))
                        j = close + 1
                    else:
                        calls.append(Call(nx.v, None, None, nx.line, prop=True))
                    continue
                if nx.v == "{":
                    j = self.pair.get(j + 1, j + 1) + 1
                    continue
                j += 2
                continue
            if t.k == "op" and t.v == "::" and j + 1 < e:
                j += 2
                if j < e and T[j].v == "(":
                    j = self.pair.get(j, j) + 1
                continue
            if t.k == "op" and t.v in ("[", "("):
                j = self.pair.get(j, j) + 1
                continue
            if t.k == "op" and t.v in ("++", "--"):
                j += 1
                continue
            break
        if calls:
            v = Node("chain", base=v, calls=calls)
        return v, j

    def _primary(self, i, e):
        T = self.toks
        t = T[i]
        if t.k == "str":
            return t.v, i + 1
        if t.k == "num":
            s = t.v.replace("_", "")
            try:
                return (int(s, 16) if s.lower().startswith("0x") else float(s) if ("." in s or "e" in s.lower()) else int(s)), i + 1
            except ValueError:
                return s, i + 1
        if t.k == "var":
            return Node("var", name=t.v), i + 1
        if t.k == "op":
            if t.v == "[":
                close = self.pair.get(i)
                if close is None:
                    raise ParseError
                return self._array(i + 1, close), close + 1
            if t.v == "(":
                close = self.pair.get(i)
                if close is None:
                    raise ParseError
                v, _ = self.value(i + 1, close)
                return v, close + 1
            if t.v == "#[":
                return self._primary(self.pair.get(i, i) + 1, e)
            raise ParseError
        if t.k != "name":
            raise ParseError
        low = t.v.lower()
        nxt = T[i + 1] if i + 1 < e else None
        if low in ("true", "false"):
            return low == "true", i + 1
        if low == "null":
            return None, i + 1
        if low == "__dir__":
            return self.dir, i + 1
        if low == "__file__":
            return self.path, i + 1
        if low == "static" and nxt is not None and nxt.k == "name" and nxt.v.lower() in ("function", "fn"):
            return self._primary(i + 1, e)
        if low in ("function", "fn") and nxt is not None and nxt.v in ("(", "&"):
            return self._closure(i, e)
        if low == "new" and nxt is not None:
            j = i + 1
            if nxt.k == "name" and nxt.v.lower() == "class":
                k = j + 1
                if k < e and T[k].v == "(":
                    k = self.pair.get(k, k) + 1
                while k < e and T[k].v != "{":
                    k += 1
                close = self.pair.get(k, k)
                return Node("new", cls="class@anonymous", args=[], kw={}, start=k + 1, end=close, line=t.line), close + 1
            cls = None
            if nxt.k == "name":
                cls = self.resolve(nxt.v)
                j += 1
            elif nxt.k == "var":
                j += 1
            else:
                raise ParseError
            args, kw = [], {}
            if j < e and T[j].v == "(":
                close = self.pair.get(j, j)
                args, kw = self.args(j + 1, close)
                j = close + 1
            return Node("new", cls=cls, args=args, kw=kw, line=t.line), j
        if low == "array" and nxt is not None and nxt.v == "(":
            close = self.pair.get(i + 1, i + 1)
            return self._array(i + 2, close), close + 1
        if low in ("match", "list", "isset", "empty") and nxt is not None and nxt.v == "(":
            close = self.pair.get(i + 1, i + 1)
            if low == "match" and close + 1 < e and T[close + 1].v == "{":
                close = self.pair.get(close + 1, close + 1)
            return Node("raw", text=self.text_of(i, close + 1)), close + 1
        if nxt is not None and nxt.k == "op" and nxt.v == "::":
            cls = self.resolve(t.v)
            if i + 2 < e:
                m = T[i + 2]
                if m.k == "name" and m.v.lower() == "class":
                    return Cls(cls), i + 3
                if m.k == "name" and i + 3 < e and T[i + 3].v == "(":
                    close = self.pair.get(i + 3, i + 3)
                    args, kw = self.args(i + 4, close)
                    return Node("static", cls=cls, name=m.v, args=args, kw=kw, line=m.line), close + 1
                if m.k == "name":
                    return Node("const", cls=cls, name=m.v), i + 3
                if m.k == "var":
                    return Node("const", cls=cls, name=m.v), i + 3
            raise ParseError
        if nxt is not None and nxt.v == "(":
            close = self.pair.get(i + 1, i + 1)
            args, kw = self.args(i + 2, close)
            node = Node("call", name=t.v.lstrip("\\"), args=args, kw=kw, line=t.line)
            folded = self._fold_call(node)
            return (node if folded is None else folded), close + 1
        return Node("const", cls=None, name=t.v), i + 1

    def _fold_call(self, node):
        name = node.name.lower()
        a = node.args
        if name == "dirname" and a and isinstance(a[0], str):
            levels = a[1] if len(a) > 1 and isinstance(a[1], int) else 1
            p = a[0]
            for _ in range(levels):
                p = os.path.dirname(p)
            return p
        bases = {"base_path": "", "app_path": "app", "resource_path": "resources", "database_path": "database",
                 "config_path": "config", "public_path": "public", "storage_path": "storage", "lang_path": "lang"}
        if name in bases and (not a or isinstance(a[0], str)):
            ps = PathStr(os.path.join(self.root, bases[name], a[0] if a else ""))
            ps.src = f"{node.name}(" + (repr(a[0]) if a else "") + ")"
            return ps
        return None

    def _closure(self, i, e):
        T = self.toks
        j = i + 1
        arrow = T[i].v.lower() == "fn"
        if j < e and T[j].v == "&":
            j += 1
        params = []
        if j < e and T[j].v == "(":
            pc = self.pair.get(j, j)
            params = self._parse_params(j + 1, pc)
            j = pc + 1
        if not arrow:
            if j < e and T[j].k == "name" and T[j].v.lower() == "use" and j + 1 < e:
                j = self.pair.get(j + 1, j + 1) + 1
            while j < e and T[j].v != "{":
                j += 1
            close = self.pair.get(j, j)
            return Node("closure", start=j + 1, end=close, params=params, line=T[i].line), close + 1
        while j < e and T[j].v != "=>":
            j += 1
        _, k = self.value(j + 1, e)
        return Node("closure", start=j + 1, end=k, params=params, line=T[i].line, arrow=True), k

    def args(self, s, e):
        args, kw, T = [], {}, self.toks
        for a, b in self._split(s, e, ","):
            if a >= b:
                continue
            if T[a].k == "name" and a + 1 < b and T[a + 1].k == "op" and T[a + 1].v == ":":
                kw[T[a].v], _ = self.value(a + 2, b)
                continue
            if T[a].v == "...":
                args.append(Node("raw", text=self.text_of(a, b)))
                continue
            v, _ = self.value(a, b)
            args.append(v)
        return args, kw

    def _array(self, s, e):
        items, keyed = [], False
        for a, b in self._split(s, e, ","):
            if a >= b:
                continue
            arrow = self._find(a, b, "=>")
            if arrow is not None:
                k, _ = self.value(a, arrow)
                v, _ = self.value(arrow + 1, b)
                items.append((k, v))
                keyed = True
            elif self.toks[a].v == "...":
                items.append((None, Node("raw", text=self.text_of(a, b))))
            else:
                v, _ = self.value(a, b)
                items.append((None, v))
        if not keyed:
            return [v for _, v in items]
        d, idx = {}, 0
        for k, v in items:
            if k is None:
                d[idx] = v
                idx += 1
            elif isinstance(k, (str, int)) and not isinstance(k, bool):
                d[k] = v
            else:
                d[repr(k)] = v
        return d

    # ---- body scanning ---------------------------------------------------------------------------
    def first_str(self, open_paren):
        T = self.toks
        if open_paren + 1 < len(T) and T[open_paren + 1].k == "str":
            return T[open_paren + 1].v
        if open_paren + 3 < len(T) and T[open_paren + 1].k == "name" and T[open_paren + 2].v == ":" and T[open_paren + 3].k == "str":
            return T[open_paren + 3].v
        return None

    def scan(self, s, e, cls_fqn=None, parent=None):
        """Collect class references, function calls, static calls, method calls and `new`s in a token range."""
        out = BodyScan()
        T = self.toks
        old = (self._cur, self._cur_parent)
        self._cur, self._cur_parent = cls_fqn, parent
        try:
            for k in range(s, min(e, len(T))):
                t = T[k]
                if t.k != "name":
                    continue
                nxt = T[k + 1] if k + 1 < len(T) else None
                prev = T[k - 1] if k > 0 else None
                low = t.v.lower()
                if nxt is not None and nxt.k == "op" and nxt.v == "::":
                    cls = self.resolve(t.v)
                    m = T[k + 2] if k + 2 < len(T) else None
                    if m is not None and m.k == "name":
                        if m.v.lower() == "class":
                            out.refs.add((cls, "class"))
                        elif k + 3 < len(T) and T[k + 3].v == "(":
                            out.statics.append((cls, m.v, self.first_str(k + 3), m.line))
                            out.refs.add((cls, "static"))
                        else:
                            out.refs.add((cls, "const"))
                    continue
                if prev is not None and prev.k == "name" and prev.v.lower() == "new":
                    if low != "class":
                        out.news.append((self.resolve(t.v), t.line))
                        out.refs.add((self.resolve(t.v), "new"))
                    continue
                if prev is not None and prev.k == "op" and prev.v in ("->", "?->"):
                    if nxt is not None and nxt.v == "(":
                        recv = T[k - 2].v if k >= 2 and T[k - 2].k == "var" else ""
                        out.mcalls.append((t.v, self.first_str(k + 1), t.line, recv))
                    continue
                if nxt is not None and nxt.v == "(":
                    if prev is not None and ((prev.k == "name" and prev.v.lower() in ("function", "fn")) or
                                             (prev.k == "op" and prev.v == "::")):
                        continue
                    if low not in PHP_KEYWORDS:
                        out.calls.append((t.v.lstrip("\\").split("\\")[-1].lower(), self.first_str(k + 1), t.line))
                    continue
                if low in PHP_KEYWORDS or low in BUILTIN_TYPES:
                    continue
                if (nxt is not None and (nxt.k == "var" or (nxt.k == "op" and nxt.v in ("|", "&") and k + 2 < len(T) and T[k + 2].k in ("var", "name")))) or \
                        (prev is not None and prev.k == "name" and prev.v.lower() == "instanceof") or \
                        (prev is not None and prev.k == "op" and prev.v in ("?", ":") and nxt is not None and nxt.v in ("{", "|")):
                    out.refs.add((self.resolve(t.v), "type"))
        finally:
            self._cur, self._cur_parent = old
        return out

    def method_scan(self, c, m):
        if m._scan is None:
            m._scan = self.scan(m.body[0], m.body[1], c.fqn, c.extends) if m.body else BodyScan()
        return m._scan


def parse_php(path, rel, root):
    text = read_text(path)
    if not text:
        return None
    try:
        return PhpFile(path, rel, text, root)
    except RecursionError:
        return None


# =====================================================================================================
# 3. A small YAML reader (compose files, CI workflows). PyYAML is used instead when it is installed.
# =====================================================================================================

def _yaml_strip_comment(s):
    q = None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            q = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


class MiniYaml:
    def __init__(self, text):
        self.anchors = {}
        self.lines = []
        for raw in text.replace("\t", "  ").splitlines():
            if raw.strip() in ("---", "...") or not raw.strip() or raw.lstrip().startswith("#"):
                self.lines.append(None)
                continue
            content = _yaml_strip_comment(raw)
            if not content.strip():
                self.lines.append(None)
                continue
            self.lines.append([len(content) - len(content.lstrip(" ")), content.strip()])
        self.lines = [ln for ln in self.lines if ln is not None] + [None]
        self.raw_text = text

    def parse(self):
        if not self.lines[0]:
            return None
        v, _ = self._block(0, self.lines[0][0])
        return v

    def _block(self, i, indent):
        ln = self.lines[i]
        if ln is None:
            return None, i
        if ln[1] == "-" or ln[1].startswith("- "):
            return self._seq(i, ln[0])
        return self._map(i, ln[0])

    @staticmethod
    def _split_key(s):
        if s and s[0] in ("'", '"'):
            q = s[0]
            end = s.find(q, 1)
            if end > 0 and s[end + 1:end + 2] == ":":
                return s[1:end], s[end + 2:].strip()
        m = re.match(r"^([^:]+?):(?:\s+(.*)|$)", s)
        if m and not s.startswith(("[", "{")):
            return m.group(1).strip(), (m.group(2) or "").strip()
        return None, None

    def _map(self, i, indent):
        out = {}
        while True:
            ln = self.lines[i]
            if ln is None or ln[0] < indent or (ln[0] == indent and (ln[1] == "-" or ln[1].startswith("- "))):
                break
            if ln[0] > indent:
                i += 1
                continue
            key, rest = self._split_key(ln[1])
            if key is None:
                i += 1
                continue
            anchor = None
            m = re.match(r"^&(\S+)\s*(.*)$", rest)
            if m:
                anchor, rest = m.group(1), m.group(2)
            i += 1
            if rest in ("", None):
                nxt = self.lines[i]
                if nxt is not None and (nxt[0] > indent or (nxt[0] == indent and (nxt[1] == "-" or nxt[1].startswith("- ")))):
                    val, i = self._block(i, nxt[0])
                else:
                    val = None
            elif rest[0] in "|>":
                parts = []
                while self.lines[i] is not None and self.lines[i][0] > indent:
                    parts.append(self.lines[i][1])
                    i += 1
                val = ("\n" if rest[0] == "|" else " ").join(parts)
            else:
                val = self._scalar(rest)
            if anchor:
                self.anchors[anchor] = val
            if key == "<<":
                for src in (val if isinstance(val, list) else [val]):
                    if isinstance(src, dict):
                        for k2, v2 in src.items():
                            out.setdefault(k2, v2)
                continue
            out[key] = val
        return out, i

    def _seq(self, i, indent):
        out = []
        while True:
            ln = self.lines[i]
            if ln is None or ln[0] != indent or not (ln[1] == "-" or ln[1].startswith("- ")):
                break
            content = ln[1][1:].strip()
            if not content:
                i += 1
                nxt = self.lines[i]
                if nxt is not None and nxt[0] > indent:
                    val, i = self._block(i, nxt[0])
                else:
                    val = None
                out.append(val)
                continue
            key, _ = self._split_key(content)
            if key is not None and not content.startswith(("'", '"')) or (key is not None and content[0] in "'\"" and ":" in content):
                off = ln[1].index(content)
                self.lines[i] = [indent + off, content]
                val, i = self._map(i, indent + off)
                out.append(val)
                continue
            out.append(self._scalar(content))
            i += 1
        return out, i

    def _scalar(self, s):
        s = s.strip()
        if not s:
            return None
        if s.startswith("*"):
            return self.anchors.get(s[1:].strip())
        if s.startswith("&"):
            parts = s.split(None, 1)
            v = self._scalar(parts[1]) if len(parts) > 1 else None
            self.anchors[parts[0][1:]] = v
            return v
        if s[0] in ("[", "{"):
            try:
                return self._flow(s)
            except (ValueError, IndexError):
                return s
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            return s[1:-1].replace("''", "'") if s[0] == "'" else s[1:-1].replace('\\"', '"')
        low = s.lower()
        if low in ("null", "~"):
            return None
        if low in ("true", "yes", "on"):
            return True
        if low in ("false", "no", "off"):
            return False
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        if re.fullmatch(r"-?\d+\.\d+", s):
            return float(s)
        return s

    def _flow(self, s):
        pos = 0

        def ws():
            nonlocal pos
            while pos < len(s) and s[pos] in " \t":
                pos += 1

        def item():
            nonlocal pos
            ws()
            if s[pos] == "[":
                pos += 1
                out = []
                ws()
                while s[pos] != "]":
                    out.append(item())
                    ws()
                    if s[pos] == ",":
                        pos += 1
                        ws()
                pos += 1
                return out
            if s[pos] == "{":
                pos += 1
                out = {}
                ws()
                while s[pos] != "}":
                    k = item()
                    ws()
                    v = None
                    if s[pos] == ":":
                        pos += 1
                        v = item()
                    out[str(k)] = v
                    ws()
                    if s[pos] == ",":
                        pos += 1
                        ws()
                pos += 1
                return out
            if s[pos] in ("'", '"'):
                q = s[pos]
                end = s.index(q, pos + 1)
                v = s[pos + 1:end]
                pos = end + 1
                return v
            start = pos
            while pos < len(s) and s[pos] not in ",]}" and not (s[pos] == ":" and pos + 1 < len(s) and s[pos + 1] in " ,]}"):
                pos += 1
            return self._scalar(s[start:pos])

        return item()


def yaml_load(text):
    try:
        import yaml  # type: ignore
        try:
            return yaml.safe_load(text)
        except Exception:  # noqa: BLE001 - fall back to the mini reader
            pass
    except ImportError:
        pass
    try:
        return MiniYaml(text).parse()
    except (IndexError, ValueError, RecursionError):
        return None


def parse_env_file(path):
    """Return OrderedDict key -> value for a dotenv file (values unquoted)."""
    out = {}
    text = read_text(path)
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            out[k] = v
    return out


def interpolate(s, env):
    """Resolve docker-compose style ${VAR:-default} using env dict; returns (resolved, [vars])."""
    if not isinstance(s, str):
        return s, []
    used = []

    def rep(m):
        name = m.group(1) or m.group(4)
        used.append(name)
        op, default = m.group(2), m.group(3)
        val = env.get(name)
        if op and op.startswith(":-") and not val:
            return default or ""
        if op and op.startswith("-") and val is None:
            return default or ""
        return val if val is not None else (default or "")

    out = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?+])([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)", rep, s)
    return out, used


# =====================================================================================================
# 4. Class roles: how we decide that a class is a model, controller, job, Livewire component, ...
# =====================================================================================================

ROLES = [
    # key, label, plural, what it does (plain English, shown on the pages)
    ("model", "Model", "Models", "Eloquent models: one class per database table, with relationships and casts."),
    ("controller", "Controller", "Controllers", "Receive HTTP requests from routes and return responses."),
    ("middleware", "Middleware", "Middleware", "Run before/after a request reaches a controller (auth, CSRF, locale…)."),
    ("request", "Form request", "Form requests", "Validate and authorise incoming request data before the controller runs."),
    ("resource", "API resource", "API resources", "Shape models into JSON for API responses."),
    ("livewire", "Livewire", "Livewire components", "Server-driven UI components: PHP state + Blade view, updated over AJAX."),
    ("filament", "Filament", "Filament classes", "Admin panel building blocks: resources (CRUD), pages, widgets, panels."),
    ("job", "Job", "Jobs", "Units of work pushed onto a queue and run by a worker in the background."),
    ("event", "Event", "Events", "Things that happened in the domain; listeners react to them."),
    ("listener", "Listener", "Listeners", "React to events (often queued)."),
    ("mail", "Mailable", "Mailables", "Email messages."),
    ("notification", "Notification", "Notifications", "Messages sent over mail, database, Slack, SMS… channels."),
    ("observer", "Observer", "Observers", "Hook into model lifecycle events (creating, updated, deleted…)."),
    ("policy", "Policy", "Policies", "Authorisation rules per model (can this user update this post?)."),
    ("command", "Command", "Console commands", "Artisan commands, run by hand or from the scheduler."),
    ("provider", "Provider", "Service providers", "Boot-time wiring: bindings, event listeners, gates, macros."),
    ("component", "View component", "View components", "Blade components backed by a PHP class."),
    ("enum", "Enum", "Enums", "Fixed sets of values (statuses, types), often used as model casts."),
    ("rule", "Rule", "Validation rules", "Custom validation rules."),
    ("cast", "Cast", "Custom casts", "Convert attributes between the database and PHP."),
    ("action", "Action", "Actions", "Single-purpose classes that perform one business operation."),
    ("service", "Service", "Services", "Business logic or integrations shared by several entry points."),
    ("repository", "Repository", "Repositories", "Data-access wrappers around models or APIs."),
    ("data", "Data object", "Data objects / DTOs", "Typed containers for passing data around."),
    ("scope", "Scope", "Query scopes", "Reusable global query constraints."),
    ("exception", "Exception", "Exceptions", "Custom exception types."),
    ("factory", "Factory", "Model factories", "Generate fake model data for tests and seeding."),
    ("seeder", "Seeder", "Seeders", "Fill the database with initial or demo data."),
    ("migration", "Migration", "Migrations", "Versioned database schema changes."),
    ("test", "Test", "Tests", "Automated tests."),
    ("trait", "Trait", "Traits / concerns", "Reusable chunks of class behaviour."),
    ("interface", "Interface", "Interfaces / contracts", "Contracts that classes implement."),
    ("other", "Other", "Other classes", "Everything else."),
]
ROLE_INFO = {r[0]: {"label": r[1], "plural": r[2], "desc": r[3]} for r in ROLES}
ROLE_ORDER = [r[0] for r in ROLES]

EXT_MODEL_PARENTS = ("Illuminate\\Database\\Eloquent\\Model", "Illuminate\\Foundation\\Auth\\User",
                     "Illuminate\\Database\\Eloquent\\Relations\\Pivot", "Illuminate\\Database\\Eloquent\\Relations\\MorphPivot",
                     "MongoDB\\Laravel\\Eloquent\\Model", "Jenssegers\\Mongodb\\Eloquent\\Model")


class ClassIndex:
    def __init__(self, files):
        self.files = files
        self.by_fqn = {}
        self.by_short = defaultdict(list)
        for pf in files.values():
            for c in pf.classes:
                if not c.fqn:
                    continue
                self.by_fqn.setdefault(c.fqn, c)
                self.by_short[c.name].append(c)

    def get(self, fqn):
        return self.by_fqn.get(fqn)

    def ancestors(self, c):
        """List of parent FQNs (project and external), nearest first."""
        out, seen, cur = [], set(), c
        while cur is not None and cur.extends and cur.extends not in seen:
            seen.add(cur.extends)
            out.append(cur.extends)
            cur = self.by_fqn.get(cur.extends)
        return out

    def all_interfaces(self, c):
        out, cur, seen = set(c.implements), c, set()
        while cur is not None and cur.extends and cur.extends not in seen:
            seen.add(cur.extends)
            cur = self.by_fqn.get(cur.extends)
            if cur is not None:
                out |= set(cur.implements)
        return out

    def all_traits(self, c):
        out, cur, seen = set(c.traits), c, set()
        while cur is not None and cur.extends and cur.extends not in seen:
            seen.add(cur.extends)
            cur = self.by_fqn.get(cur.extends)
            if cur is not None:
                out |= set(cur.traits)
        return out

    def has_method(self, c, name):
        cur, seen = c, set()
        while cur is not None:
            if name in cur.methods:
                return True
            if not cur.extends or cur.extends in seen:
                return False
            seen.add(cur.extends)
            cur = self.by_fqn.get(cur.extends)
        return False

    def is_a(self, c, *names):
        anc = self.ancestors(c)
        allx = set(anc) | self.all_interfaces(c)
        return any(any(a == n or a.endswith("\\" + n) for a in allx) for n in names)


def classify(c, idx, pf):
    """Return the role key for a class."""
    fqn = c.fqn or ""
    rel = pf.rel
    anc = idx.ancestors(c)
    ifs = idx.all_interfaces(c)
    traits = idx.all_traits(c)
    allp = set(anc) | ifs

    def has(*needles):
        shorts = {short(n) for n in needles}
        return any(p in needles or short(p) in shorts for p in allp)

    def ext(*prefixes):
        return any(any(p.startswith(x) for x in prefixes) for p in allp)

    if c.kind == "enum":
        return "enum"
    if rel.startswith("tests/") or has("PHPUnit\\Framework\\TestCase", "Tests\\TestCase") or (anc and short(anc[-1]) == "TestCase"):
        return "test"
    if rel.startswith("database/migrations/") or has("Illuminate\\Database\\Migrations\\Migration"):
        return "migration"
    if rel.startswith("database/factories/") or ext("Illuminate\\Database\\Eloquent\\Factories\\Factory"):
        return "factory"
    if rel.startswith("database/seeders/") or rel.startswith("database/seeds/") or ext("Illuminate\\Database\\Seeder"):
        return "seeder"
    if c.kind == "interface":
        return "interface"
    if c.kind == "trait":
        return "trait"
    anc_ext = lambda *px: any(any(a.startswith(x) for x in px) for a in anc)  # noqa: E731
    if any(p in EXT_MODEL_PARENTS for p in anc) or anc_ext("Illuminate\\Database\\Eloquent\\Model") or \
            ("\\Models\\" in fqn and not c.abstract and c.kind == "class" and not anc_ext("Illuminate\\", "Filament\\", "Livewire\\")
             and "Scope" not in c.name and not c.name.endswith(("Interface", "Contract"))):
        return "model"
    if anc_ext("Filament\\") or ("\\Filament\\" in fqn and (c.extends or c.name.endswith(("Resource", "Page", "Widget")))):
        return "filament"
    if anc_ext("Livewire\\Component", "Livewire\\Form", "Livewire\\Volt\\") or \
            (("\\Livewire\\" in fqn or "\\Http\\Livewire\\" in fqn) and c.extends and not anc_ext("Illuminate\\")):
        return "livewire"
    if "\\Http\\Controllers\\" in fqn or c.name.endswith("Controller"):
        return "controller"
    if "\\Http\\Middleware\\" in fqn:
        return "middleware"
    if ext("Illuminate\\Foundation\\Http\\FormRequest") or "\\Http\\Requests\\" in fqn:
        return "request"
    if ext("Illuminate\\Http\\Resources\\") or "\\Http\\Resources\\" in fqn:
        return "resource"
    if ext("Illuminate\\Mail\\Mailable") or "\\Mail\\" in fqn:
        return "mail"
    if ext("Illuminate\\Notifications\\Notification") or "\\Notifications\\" in fqn:
        return "notification"
    if "\\Listeners\\" in fqn:
        return "listener"
    if "\\Events\\" in fqn:
        return "event"
    if "\\Jobs\\" in fqn or ("Illuminate\\Contracts\\Queue\\ShouldQueue" in ifs and any(short(t) == "Dispatchable" for t in traits)):
        return "job"
    if "\\Observers\\" in fqn or c.name.endswith("Observer"):
        return "observer"
    if "\\Policies\\" in fqn or c.name.endswith("Policy"):
        return "policy"
    if ext("Illuminate\\Console\\Command") or "\\Console\\Commands\\" in fqn:
        return "command"
    if ext("Illuminate\\Support\\ServiceProvider") or "\\Providers\\" in fqn:
        return "provider"
    if ext("Illuminate\\View\\Component") or "\\View\\Components\\" in fqn:
        return "component"
    if has("Illuminate\\Contracts\\Validation\\ValidationRule", "Illuminate\\Contracts\\Validation\\Rule") or "\\Rules\\" in fqn:
        return "rule"
    if has("Illuminate\\Contracts\\Database\\Eloquent\\CastsAttributes") or "\\Casts\\" in fqn:
        return "cast"
    if has("Illuminate\\Database\\Eloquent\\Scope") or "\\Scopes\\" in fqn:
        return "scope"
    if any("Exception" in p or p.endswith("Throwable") for p in allp) or "\\Exceptions\\" in fqn:
        return "exception"
    if "\\Actions\\" in fqn or c.name.endswith("Action"):
        return "action"
    if "\\Repositories\\" in fqn or c.name.endswith("Repository"):
        return "repository"
    if "\\Services\\" in fqn or c.name.endswith("Service") or c.name.endswith("Gateway") or c.name.endswith("Client"):
        return "service"
    if any(x in fqn for x in ("\\Data\\", "\\DTO\\", "\\DTOs\\", "\\Dto\\")) or c.name.endswith(("Data", "DTO", "Dto")):
        return "data"
    return "other"


# =====================================================================================================
# 5. The project: files, composer/npm metadata, parsed PHP
# =====================================================================================================

class Project:
    def __init__(self, root, static_only=False):
        self.root = os.path.abspath(root)
        DISPLAY_ROOT["path"] = self.root
        self.composer = read_json(self.p("composer.json")) or {}
        self.lock = read_json(self.p("composer.lock")) or {}
        self.pkg = read_json(self.p("package.json")) or {}
        self.pkg_lock = read_json(self.p("package-lock.json")) or {}
        self.env_example = parse_env_file(self.p(".env.example")) if self.exists(".env.example") else {}
        self.env = parse_env_file(self.p(".env")) if self.exists(".env") else {}
        self.php = {}
        self.notes = []
        self.static_only = static_only
        self._load_php()
        self.idx = ClassIndex(self.php)
        self.roles = {}
        for fqn, c in self.idx.by_fqn.items():
            c.role = classify(c, self.idx, c.file)
            self.roles[fqn] = c.role

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def exists(self, *parts):
        return os.path.exists(self.p(*parts))

    def rel(self, ap):
        return os.path.relpath(os.path.abspath(ap), self.root).replace(os.sep, "/")

    def require(self):
        return {**(self.composer.get("require") or {})}

    def require_dev(self):
        return {**(self.composer.get("require-dev") or {})}

    def has_pkg(self, name):
        return name in self.require() or name in self.require_dev() or name in self.locked_versions()

    def has_npm(self, name):
        return name in (self.pkg.get("dependencies") or {}) or name in (self.pkg.get("devDependencies") or {})

    def locked_versions(self):
        if not hasattr(self, "_locked"):
            self._locked = {}
            for sec in ("packages", "packages-dev"):
                for p in self.lock.get(sec) or []:
                    if isinstance(p, dict) and p.get("name"):
                        self._locked[p["name"]] = {"version": p.get("version", ""), "dev": sec == "packages-dev",
                                                   "description": p.get("description", "")}
        return self._locked

    def npm_locked(self):
        out = {}
        for k, v in (self.pkg_lock.get("packages") or {}).items():
            if k.startswith("node_modules/") and isinstance(v, dict) and "/node_modules/" not in k[13:]:
                out[k[13:]] = v.get("version", "")
        if not out:
            for k, v in (self.pkg_lock.get("dependencies") or {}).items():
                if isinstance(v, dict):
                    out[k] = v.get("version", "")
        return out

    def php_dirs(self):
        dirs = {"app", "routes", "config", "database", "tests", "bootstrap"}
        for sec in ("autoload", "autoload-dev"):
            for _ns, d in ((self.composer.get(sec) or {}).get("psr-4") or {}).items():
                for x in (d if isinstance(d, list) else [d]):
                    x = str(x).strip().strip("/")
                    if x and x != "." and not x.startswith("vendor"):
                        dirs.add(x)
        return sorted(dirs)

    def _load_php(self):
        for d in self.php_dirs():
            for ap, rel in walk(self.root, d, exts=(".php",)):
                if rel.endswith(".blade.php") or rel in self.php:
                    continue
                if rel.startswith("bootstrap/") and rel not in ("bootstrap/app.php", "bootstrap/providers.php"):
                    continue
                pf = parse_php(ap, rel, self.root)
                if pf is not None:
                    self.php[rel] = pf

    def laravel_version(self):
        lv = self.locked_versions().get("laravel/framework", {}).get("version")
        if lv:
            return lv.lstrip("v")
        c = self.require().get("laravel/framework")
        return c or ""

    def laravel_major(self):
        m = re.search(r"(\d+)", self.laravel_version() or "")
        return int(m.group(1)) if m else None

    def name(self):
        n = self.env_example.get("APP_NAME") or self.env.get("APP_NAME")
        if n and n.lower() not in ("laravel", "${app_name}"):
            return n
        cn = self.composer.get("name", "")
        if cn and cn not in ("laravel/laravel",):
            return cn.split("/")[-1].replace("-", " ").title()
        return os.path.basename(self.root).replace("-", " ").replace("_", " ").title()

    def classes_by_role(self, role):
        return sorted((c for c in self.idx.by_fqn.values() if c.role == role), key=lambda c: c.fqn)


# =====================================================================================================
# 6. Routes (static parse of bootstrap/app.php or RouteServiceProvider -> route files -> groups)
# =====================================================================================================

ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "options", "any", "match", "view", "redirect",
               "permanentRedirect", "resource", "apiResource", "resources", "apiResources", "singleton",
               "apiSingleton", "fallback"}
ROUTE_FACADES = {"Route", "Illuminate\\Support\\Facades\\Route", "Livewire\\Volt\\Volt", "Volt",
                 "Illuminate\\Routing\\Route"}
RESOURCE_ACTIONS = [("index", ["GET", "HEAD"], ""), ("create", ["GET", "HEAD"], "/create"), ("store", ["POST"], ""),
                    ("show", ["GET", "HEAD"], "/{p}"), ("edit", ["GET", "HEAD"], "/{p}/edit"),
                    ("update", ["PUT", "PATCH"], "/{p}"), ("destroy", ["DELETE"], "/{p}")]


def join_uri(a, b):
    a = (a or "").strip("/")
    b = (b or "").strip("/")
    s = "/".join(x for x in (a, b) if x)
    return "/" + s if s else "/"


def new_ctx():
    return {"prefix": "", "name": "", "middleware": [], "without": [], "controller": None, "namespace": None,
            "domain": None, "group": "", "only": None, "except": None, "names": None, "parameters": None}


class RouteParser:
    def __init__(self, proj):
        self.proj = proj
        self.routes = []
        self.visited = set()
        self.stack = []
        self.console_files = []
        self.channel_files = []
        self.registration = []   # human description of how route files are wired up

    # -- helpers -------------------------------------------------------------------------------------
    def _pf(self, ap):
        rel = self.proj.rel(ap)
        pf = self.proj.php.get(rel)
        if pf is None and os.path.isfile(ap):
            pf = parse_php(ap, rel, self.proj.root)
            if pf is not None:
                self.proj.php[rel] = pf
        return pf

    def _abs(self, path):
        if not isinstance(path, str) or not path:
            return None
        ap = path if os.path.isabs(path) else os.path.join(self.proj.root, path)
        return os.path.normpath(ap)

    def _is_root(self, pf, k):
        T = pf.toks
        t = T[k]
        if t.k == "name" and k + 1 < len(T) and T[k + 1].v == "::":
            fq = pf.resolve(t.v)
            return fq in ROUTE_FACADES or short(fq) in ("Route", "Volt") and fq.split("\\")[0] in ("Illuminate", "Livewire", "Route", "Volt")
        if t.k == "var" and t.v in ("$router", "$route", "$routes", "$r") and k + 1 < len(T) and T[k + 1].v == "->":
            return True
        return False

    def parse_file(self, ap, ctx, label=""):
        ap = self._abs(ap)
        if not ap or not os.path.isfile(ap):
            if ap:
                self.proj.notes.append(f"Route file referenced but not found: {self.proj.rel(ap)}")
            return
        rel = self.proj.rel(ap)
        if rel in self.stack:
            return
        pf = self._pf(ap)
        if pf is None:
            return
        self.visited.add(rel)
        self.stack.append(rel)
        c2 = dict(ctx)
        if label and not c2.get("group"):
            c2["group"] = label
        try:
            self.parse_range(pf, 0, len(pf.toks), c2)
        finally:
            self.stack.pop()

    def parse_range(self, pf, s, e, ctx):
        T, k = pf.toks, s
        while k < e:
            t = T[k]
            if self._is_root(pf, k) and not (k > 0 and T[k - 1].v in ("->", "::", "new")):
                v, j = pf.value(k, e)
                try:
                    self.handle(pf, v, ctx)
                except (IndexError, KeyError, TypeError, AttributeError) as ex:
                    self.proj.notes.append(f"Could not read a route definition in {pf.rel}:{t.line} ({ex.__class__.__name__})")
                k = max(j, k + 1)
                continue
            if t.k == "name" and t.v.lower() in ("require", "require_once", "include", "include_once"):
                v, j = pf.value(k + 1, e)
                if isinstance(v, str):
                    self.parse_file(v, ctx)
                k = max(j, k + 1)
                continue
            k += 1

    def handle(self, pf, v, ctx):
        root, calls = chain_root(v)
        if not calls:
            return
        is_volt = isinstance(root, Node) and root.type == "static" and short(root.cls) == "Volt"
        verb = next((c for c in calls if c.name in ROUTE_VERBS or (is_volt and c.name == "route")), None)
        group = next((c for c in calls if c.name == "group"), None)
        if group is not None and verb is None:
            new = self.apply(pf, ctx, [c for c in calls if c is not group])
            args = group.args
            target = None
            if len(args) >= 2 and isinstance(args[0], dict):
                new = self.apply_array(pf, new, args[0])
                target = args[1]
            elif args:
                target = args[0]
            if isinstance(target, Node) and target.type == "closure":
                self.parse_range(pf, target.start, target.end, new)
            elif isinstance(target, str):
                self.parse_file(target, new)
            return
        if verb is not None:
            others = [c for c in calls if c is not verb]
            rctx = self.apply(pf, ctx, [c for c in others if c.name not in ("name", "as")])
            local = "".join(c.args[0] for c in others
                            if c.name in ("name", "as") and c.args and isinstance(c.args[0], str)) or None
            self.add_verb(pf, verb, rctx, is_volt, local)

    def _ns_value(self, pf, a):
        if isinstance(a, str):
            return a
        if isinstance(a, Node) and a.type == "chain" and isinstance(a.base, Node) and a.base.type == "var" \
                and a.base.name == "$this" and a.calls and a.calls[0].args == []:
            prop = a.calls[0].name
            for c in pf.classes:
                if prop in c.props and isinstance(c.props[prop]["value"], str):
                    return c.props[prop]["value"]
        return None

    def apply(self, pf, ctx, calls):
        new = {**ctx, "middleware": list(ctx["middleware"]), "without": list(ctx["without"]),
               "only": None, "except": None, "names": None, "parameters": None}
        for c in calls:
            a = c.args[0] if c.args else None
            nm = c.name
            if nm == "prefix" and isinstance(a, str):
                new["prefix"] = join_uri(new["prefix"], a).lstrip("/")
            elif nm in ("name", "as") and isinstance(a, str):
                new["name"] = new["name"] + a
            elif nm == "middleware":
                new["middleware"] += [m for m in strs(c.args) if m not in new["middleware"]]
            elif nm == "withoutMiddleware":
                new["without"] += strs(c.args)
            elif nm == "controller" and isinstance(a, str):
                new["controller"] = str(a)
            elif nm == "namespace":
                ns = self._ns_value(pf, a)
                if ns:
                    new["namespace"] = (new["namespace"] + "\\" + ns.strip("\\")) if new.get("namespace") and not ns.startswith("\\") else ns.strip("\\")
            elif nm == "domain" and isinstance(a, str):
                new["domain"] = a
            elif nm == "can" and c.args:
                new["middleware"].append("can:" + ",".join(str(x) for x in c.args if isinstance(x, str)))
            elif nm in ("only", "except"):
                new[nm] = strs(c.args)
            elif nm == "names":
                new["names"] = a
            elif nm == "parameters" and isinstance(a, dict):
                new["parameters"] = a
        return new

    def apply_array(self, pf, ctx, arr):
        calls = []
        for k, v in arr.items():
            if k in ("prefix", "as", "middleware", "namespace", "domain", "controller", "excluded_middleware"):
                calls.append(Call("withoutMiddleware" if k == "excluded_middleware" else k, [v], {}, 0))
        return self.apply(pf, ctx, calls)

    def _qualify(self, cname, ctx):
        if isinstance(cname, Cls):
            return str(cname)
        cname = str(cname)
        if cname.startswith("\\"):
            return cname[1:]
        if ctx.get("namespace"):
            return ctx["namespace"].strip("\\") + "\\" + cname
        if "\\" not in cname:
            for c in self.proj.idx.by_short.get(cname, []):
                if "\\Http\\Controllers" in c.fqn:
                    return c.fqn
            return "App\\Http\\Controllers\\" + cname
        if not cname.startswith("App\\") and self.proj.idx.get("App\\Http\\Controllers\\" + cname):
            return "App\\Http\\Controllers\\" + cname
        return cname

    def resolve_action(self, action, ctx):
        """-> dict(type, controller, method, label, extra_name, extra_mw)"""
        out = {"type": "unknown", "controller": None, "method": None, "label": "?", "name": None, "middleware": []}
        if isinstance(action, dict):
            uses = action.get("uses")
            out["name"] = action.get("as") if isinstance(action.get("as"), str) else None
            out["middleware"] = strs(action.get("middleware"))
            if uses is None:
                uses = next((v for v in action.values() if isinstance(v, Node) and v.type == "closure"), None)
            r = self.resolve_action(uses, ctx)
            r["name"], r["middleware"] = out["name"], out["middleware"]
            return r
        if isinstance(action, Node) and action.type == "closure":
            out.update(type="closure", label="Closure",
                       _closure=(action.start, action.end, [(p["name"], p["types"]) for p in (action.params or [])]))
            return out
        if isinstance(action, list) and action:
            cls = self._qualify(action[0], ctx) if isinstance(action[0], str) else None
            meth = action[1] if len(action) > 1 and isinstance(action[1], str) else "__invoke"
            if cls:
                out.update(type="controller", controller=cls, method=meth, label=f"{cls}@{meth}")
            return out
        if isinstance(action, Cls):
            cls = str(action)
            c = self.proj.idx.get(cls)
            role = c.role if c else ""
            if role == "livewire" or "\\Livewire\\" in cls:
                out.update(type="livewire", controller=cls, method="render", label=f"{cls} (Livewire)")
            else:
                out.update(type="controller", controller=cls, method="__invoke", label=f"{cls}@__invoke")
            return out
        if isinstance(action, str):
            if "@" in action:
                cname, meth = action.split("@", 1)
                cls = self._qualify(cname, ctx)
                out.update(type="controller", controller=cls, method=meth, label=f"{cls}@{meth}")
            elif ctx.get("controller"):
                cls = self._qualify(ctx["controller"], ctx)
                out.update(type="controller", controller=cls, method=action, label=f"{cls}@{action}")
            else:
                cls = self._qualify(action, ctx)
                out.update(type="controller", controller=cls, method="__invoke", label=f"{cls}@__invoke")
            return out
        if isinstance(action, Node):
            out["label"] = repr(action)
        return out

    def emit(self, pf, line, methods, uri, ctx, act, name=None, extra=None):
        name_full = None
        n = name if name is not None else act.get("name")
        if n:
            name_full = ctx["name"] + n
        mw = [m for m in ctx["middleware"] + (act.get("middleware") or []) if m not in ctx["without"]]
        r = {"methods": methods, "uri": join_uri(ctx["prefix"], uri), "name": name_full,
             "action": act.get("label"), "action_type": act.get("type"), "controller": act.get("controller"),
             "method": act.get("method"), "middleware": list(dict.fromkeys(mw)), "file": pf.rel, "line": line,
             "group": ctx.get("group") or "", "domain": ctx.get("domain"), "source": "static"}
        if act.get("_closure"):
            r["_closure"] = (pf.rel,) + tuple(act["_closure"])
        if extra:
            r.update(extra)
        self.routes.append(r)
        return r

    def add_verb(self, pf, c, ctx, is_volt, local_name=None):
        nm, args, line = c.name, c.args, c.line
        base_ctx = ctx
        if is_volt and nm == "route":
            uri = args[0] if args and isinstance(args[0], str) else "?"
            comp = args[1] if len(args) > 1 and isinstance(args[1], str) else None
            act = {"type": "volt", "label": f"Volt: {comp}", "controller": None, "method": None}
            self.emit(pf, line, ["GET", "HEAD"], uri, base_ctx, act, local_name, {"volt": comp})
            return
        if nm in ("get", "post", "put", "patch", "delete", "options", "any"):
            methods = {"get": ["GET", "HEAD"], "any": ["ANY"]}.get(nm, [nm.upper()])
            uri = args[0] if args and isinstance(args[0], str) else "?"
            act = self.resolve_action(args[1] if len(args) > 1 else c.kw.get("action"), base_ctx)
            self.emit(pf, line, methods, uri, base_ctx, act, local_name)
        elif nm == "match":
            methods = [m.upper() for m in strs(args[0])] if args else ["?"]
            uri = args[1] if len(args) > 1 and isinstance(args[1], str) else "?"
            act = self.resolve_action(args[2] if len(args) > 2 else None, base_ctx)
            self.emit(pf, line, methods, uri, base_ctx, act, local_name)
        elif nm == "view":
            uri = args[0] if args and isinstance(args[0], str) else "?"
            view = args[1] if len(args) > 1 and isinstance(args[1], str) else "?"
            act = {"type": "view", "label": f"view: {view}"}
            self.emit(pf, line, ["GET", "HEAD"], uri, base_ctx, act, local_name, {"view": view})
        elif nm in ("redirect", "permanentRedirect"):
            uri = args[0] if args and isinstance(args[0], str) else "?"
            target = args[1] if len(args) > 1 and isinstance(args[1], str) else "?"
            act = {"type": "redirect", "label": f"→ {target}" + (" (301)" if nm == "permanentRedirect" else "")}
            self.emit(pf, line, ["ANY"], uri, base_ctx, act, local_name, {"target": target})
        elif nm == "fallback":
            act = self.resolve_action(args[0] if args else None, base_ctx)
            self.emit(pf, line, ["GET", "HEAD"], "{fallbackPlaceholder}", base_ctx, act, local_name, {"fallback": True})
        elif nm in ("resource", "apiResource", "singleton", "apiSingleton"):
            if len(args) >= 2 and isinstance(args[0], str):
                self.expand_resource(pf, line, nm, args[0], args[1], ctx, local_name)
        elif nm in ("resources", "apiResources"):
            if args and isinstance(args[0], dict):
                for rname, ctrl in args[0].items():
                    if isinstance(rname, str):
                        self.expand_resource(pf, line, "resource" if nm == "resources" else "apiResource", rname, ctrl, ctx)

    def expand_resource(self, pf, line, kind, rname, ctrl, ctx, local_name=None):
        ctrl_fqn = self._qualify(ctrl, ctx) if isinstance(ctrl, str) else None
        parts = rname.split(".")
        uri = ""
        for p in parts[:-1]:
            uri += f"/{p}/{{{singular(p.split('/')[-1]).replace('-', '_')}}}"
        last = parts[-1]
        params = ctx.get("parameters") or {}
        param = params.get(last) if isinstance(params.get(last), str) else singular(last.split("/")[-1]).replace("-", "_")
        base = f"{uri}/{last}"
        if kind in ("singleton", "apiSingleton"):
            actions = [("show", ["GET", "HEAD"], ""), ("edit", ["GET", "HEAD"], "/edit"), ("update", ["PUT", "PATCH"], "")]
            if kind == "apiSingleton":
                actions = [a for a in actions if a[0] != "edit"]
        else:
            actions = RESOURCE_ACTIONS if kind == "resource" else [a for a in RESOURCE_ACTIONS if a[0] not in ("create", "edit")]
        only, except_ = ctx.get("only"), ctx.get("except")
        names = ctx.get("names")
        base_name = rname.replace("/", ".")
        gname = ctx["name"]
        for act_name, methods, suffix in actions:
            if only and act_name not in only:
                continue
            if except_ and act_name in except_:
                continue
            if isinstance(names, dict) and isinstance(names.get(act_name), str):
                rn = names[act_name]
            elif isinstance(names, str):
                rn = f"{names}.{act_name}"
            else:
                rn = f"{base_name}.{act_name}"
            act = {"type": "controller", "controller": ctrl_fqn, "method": act_name,
                   "label": f"{ctrl_fqn}@{act_name}" if ctrl_fqn else act_name}
            rctx = {**ctx, "name": gname}
            self.emit(pf, line, methods, base + suffix.replace("{p}", "{" + param + "}"), rctx, act, rn,
                      {"resource": rname})

    # -- discovery --------------------------------------------------------------------------------------
    def discover(self):
        proj = self.proj
        ctx0 = new_ctx()
        app = proj.php.get("bootstrap/app.php")
        found = False
        if app is not None:
            T = app.toks
            for k, t in enumerate(T):
                if t.k == "name" and t.v == "withRouting" and k + 1 < len(T) and T[k + 1].v == "(":
                    close = app.pair.get(k + 1, k + 1)
                    args, kw = app.args(k + 2, close)
                    found = True
                    api_prefix = kw.get("apiPrefix") if isinstance(kw.get("apiPrefix"), str) else "api"
                    self.registration.append("Routes are registered in bootstrap/app.php → withRouting() (Laravel 11+ style).")
                    for key, mw, prefix in (("web", ["web"], ""), ("api", ["api"], api_prefix)):
                        v = kw.get(key)
                        for f in (v if isinstance(v, list) else [v]):
                            if isinstance(f, str):
                                self.registration.append(f"{key}: {proj.rel(f)} (middleware group '{mw[0]}'" + (f", prefix /{prefix}" if prefix else "") + ")")
                                self.parse_file(f, {**ctx0, "prefix": prefix, "middleware": list(mw), "group": key}, key)
                    if isinstance(kw.get("commands"), str):
                        self.console_files.append(kw["commands"])
                    if isinstance(kw.get("channels"), str):
                        self.channel_files.append(kw["channels"])
                    if isinstance(kw.get("health"), str):
                        act = {"type": "framework", "label": "Health check (framework)"}
                        self.emit(app, t.line, ["GET", "HEAD"], kw["health"], {**ctx0, "group": "framework"}, act, None, {"source": "framework"})
                    for key in ("then", "using"):
                        cl = kw.get(key)
                        if isinstance(cl, Node) and cl.type == "closure":
                            self.registration.append(f"Extra routes registered in withRouting({key}: …) closure.")
                            self.parse_range(app, cl.start, cl.end, {**ctx0, "group": key})
                    break
        if not found:
            rsp = None
            for c in proj.idx.by_fqn.values():
                if c.name == "RouteServiceProvider" and c.role == "provider":
                    rsp = c
                    break
            if rsp is not None:
                before = len(self.visited)
                self.parse_range(rsp.file, rsp.body[0], rsp.body[1], {**ctx0, "group": ""})
                if len(self.visited) > before:
                    found = True
                    self.registration.append(f"Routes are registered in {rsp.file.rel} (RouteServiceProvider, Laravel ≤10 style).")
        if not found:
            self.registration.append("No route registration found; assuming Laravel defaults (web.php → 'web', api.php → /api + 'api').")
            if proj.exists("routes", "web.php"):
                self.parse_file(proj.p("routes", "web.php"), {**ctx0, "middleware": ["web"], "group": "web"}, "web")
            if proj.exists("routes", "api.php"):
                self.parse_file(proj.p("routes", "api.php"), {**ctx0, "prefix": "api", "middleware": ["api"], "group": "api"}, "api")
        if not self.console_files and proj.exists("routes", "console.php"):
            self.console_files.append(proj.p("routes", "console.php"))
        if not self.channel_files and proj.exists("routes", "channels.php"):
            self.channel_files.append(proj.p("routes", "channels.php"))
        skip = {proj.rel(f) for f in self.console_files + self.channel_files}
        for ap, rel in walk(proj.root, "routes", exts=(".php",)):
            if rel not in self.visited and rel not in skip and not rel.endswith(".blade.php"):
                self.registration.append(f"{rel} was not reached from the registration code; parsed on its own (it may be loaded some other way).")
                self.parse_file(ap, {**ctx0, "group": Path(rel).stem}, Path(rel).stem)
        return self.routes


def parse_routes(proj):
    rp = RouteParser(proj)
    routes = rp.discover()
    return rp, routes


# =====================================================================================================
# 7. Generic finders: static calls (Event::listen, Gate::policy …) and $var->method() chains
# =====================================================================================================

def find_statics(pf, s, e, facades, methods=None):
    """Yield (node, calls) for chains rooted at Facade::method(…) where short(facade) in facades."""
    T, k = pf.toks, s
    e = min(e, len(T))
    while k < e:
        t = T[k]
        if t.k == "name" and k + 3 < e and T[k + 1].v == "::" and T[k + 2].k == "name" and T[k + 3].v == "(" \
                and short(pf.resolve(t.v)) in facades and (methods is None or T[k + 2].v in methods) \
                and not (k > 0 and T[k - 1].v in ("->", "::", "new")):
            v, j = pf.value(k, e)
            root, calls = chain_root(v)
            if calls:
                yield root, calls
            k = max(j, k + 1)
            continue
        k += 1


def find_var_chains(pf, s, e, var_names):
    """Yield (calls) for chains like $schedule->command(…)->daily()."""
    T, k = pf.toks, s
    e = min(e, len(T))
    while k < e:
        t = T[k]
        if t.k == "var" and t.v in var_names and k + 1 < e and T[k + 1].v in ("->", "?->"):
            v, j = pf.value(k, e)
            if isinstance(v, Node) and v.type == "chain":
                yield v.calls
            k = max(j, k + 1)
            continue
        k += 1


def return_value(pf, m):
    """Value of the first `return …;` in a method body."""
    if not m or not m.body:
        return None
    T = pf.toks
    k, e = m.body
    while k < e:
        t = T[k]
        if t.k == "op" and t.v in ("{",) and k != m.body[0]:
            pass
        if t.k == "name" and t.v.lower() == "return":
            v, _ = pf.value(k + 1, e)
            return v
        k += 1
    return None


def prop_value(proj, c, name, default=None):
    """Property default, looked up through project parent classes."""
    cur, seen = c, set()
    while cur is not None:
        if name in cur.props and cur.props[name]["has_default"]:
            return cur.props[name]["value"]
        if not cur.extends or cur.extends in seen:
            break
        seen.add(cur.extends)
        cur = proj.idx.get(cur.extends)
    return default


def class_strs(v):
    """Class names held in a value (Cls or strings that look like FQNs)."""
    out = []
    for x in (v if isinstance(v, list) else [v]):
        if isinstance(x, Cls):
            out.append(str(x))
        elif isinstance(x, str) and "\\" in x:
            out.append(x.lstrip("\\"))
        elif isinstance(x, list):
            out.extend(class_strs(x))
    return out


# =====================================================================================================
# 8. Models
# =====================================================================================================

REL_TYPES = {"hasOne", "hasMany", "belongsTo", "belongsToMany", "morphTo", "morphOne", "morphMany", "morphToMany",
             "morphedByMany", "hasManyThrough", "hasOneThrough"}
REL_MANY = {"hasMany", "belongsToMany", "morphMany", "morphToMany", "morphedByMany", "hasManyThrough"}


def analyze_models(proj):
    models = {}
    for c in proj.classes_by_role("model"):
        pf = c.file
        table = prop_value(proj, c, "table")
        d = {"fqn": c.fqn, "name": c.name, "file": pf.rel, "line": c.line, "end_line": c.end_line,
             "abstract": c.abstract, "doc": c.doc,
             "table": table if isinstance(table, str) else table_for_model(c.name),
             "table_explicit": isinstance(table, str),
             "connection": prop_value(proj, c, "connection"),
             "primary_key": prop_value(proj, c, "primaryKey", "id"),
             "incrementing": prop_value(proj, c, "incrementing", True),
             "timestamps": prop_value(proj, c, "timestamps", True),
             "fillable": strs(prop_value(proj, c, "fillable", [])),
             "guarded": strs(prop_value(proj, c, "guarded", None)) if prop_value(proj, c, "guarded", None) is not None else None,
             "hidden": strs(prop_value(proj, c, "hidden", [])),
             "appends": strs(prop_value(proj, c, "appends", [])),
             "with": strs(prop_value(proj, c, "with", [])),
             "casts": {}, "traits": sorted({short(t) for t in proj.idx.all_traits(c)}),
             "parent": c.extends, "relations": [], "scopes": [], "accessors": [], "mutators": [],
             "observers": [], "dispatches_events": {}, "boot_hooks": [], "policy": None, "factory": None,
             "methods": len(c.methods), "loc": c.end_line - c.line + 1, "attrs": [short(a["name"]) for a in c.attrs]}
        casts = prop_value(proj, c, "casts", {})
        if isinstance(casts, dict):
            d["casts"].update({str(k): (fmt_val(v) if not isinstance(v, str) or isinstance(v, Cls) else v) for k, v in casts.items()})
        cm = c.methods.get("casts")
        if cm:
            rv = return_value(pf, cm)
            if isinstance(rv, dict):
                d["casts"].update({str(k): (fmt_val(v) if not isinstance(v, str) or isinstance(v, Cls) else v) for k, v in rv.items()})
        d["cast_classes"] = {}
        for src in (casts, return_value(pf, cm) if cm else None):
            if isinstance(src, dict):
                for k, v in src.items():
                    if isinstance(v, Cls):
                        d["cast_classes"][str(k)] = str(v)
        for a in c.attrs:
            if short(a["name"]) == "ObservedBy":
                d["observers"] += class_strs(a["args"])
            if short(a["name"]) == "UsePolicy":
                d["policy"] = (class_strs(a["args"]) or [None])[0]
        de = prop_value(proj, c, "dispatchesEvents", {})
        if isinstance(de, dict):
            d["dispatches_events"] = {str(k): str(v) for k, v in de.items() if isinstance(v, str)}
        for m in c.methods.values():
            if m.name.startswith("scope") and len(m.name) > 5 and m.name[5].isupper():
                d["scopes"].append(m.name[5].lower() + m.name[6:])
            elif any(short(a["name"]) == "Scope" for a in m.attrs):
                d["scopes"].append(m.name)
            gm = re.fullmatch(r"(get|set)([A-Z]\w*)Attribute", m.name)
            if gm:
                (d["accessors"] if gm.group(1) == "get" else d["mutators"]).append(snake(gm.group(2)))
            elif m.returns and short(m.returns) == "Attribute":
                d["accessors"].append(snake(m.name))
            if m.name in ("boot", "booted") and m.body:
                for root, calls in find_statics(pf, m.body[0], m.body[1], {"static", "self", c.name}):
                    d["boot_hooks"].append(calls[0].name)
            if not m.body or m.static:
                continue
            T = pf.toks
            for k in range(m.body[0], m.body[1]):
                t = T[k]
                if t.k == "var" and t.v == "$this" and k + 3 < len(T) and T[k + 1].v == "->" and \
                        T[k + 2].v in REL_TYPES and T[k + 3].v == "(":
                    v, _ = pf.value(k, m.body[1])
                    if not (isinstance(v, Node) and v.type == "chain"):
                        continue
                    call = v.calls[0]
                    a = call.args
                    rel = {"name": m.name, "type": call.name, "line": m.line, "related": None, "through": None,
                           "keys": [x for x in a[1:] if isinstance(x, str) and not isinstance(x, Cls)],
                           "pivot_table": None, "morph": None, "using": None,
                           "modifiers": [x.name for x in v.calls[1:]]}
                    if call.name == "morphTo":
                        rel["morph"] = a[0] if a and isinstance(a[0], str) else snake(m.name)
                    elif a:
                        rel["related"] = str(a[0]).lstrip("\\") if isinstance(a[0], str) else None
                        if rel["related"] and "\\" not in rel["related"]:
                            rel["related"] = pf.resolve(rel["related"])
                    if call.name in ("hasManyThrough", "hasOneThrough") and len(a) > 1 and isinstance(a[1], str):
                        rel["through"] = str(a[1])
                        rel["keys"] = [x for x in a[2:] if isinstance(x, str)]
                    if call.name == "belongsToMany":
                        rel["pivot_table"] = a[1] if len(a) > 1 and isinstance(a[1], str) and not isinstance(a[1], Cls) else None
                        if len(a) > 1 and isinstance(a[1], Cls):
                            rel["using"] = str(a[1])
                        rel["keys"] = [x for x in a[2:] if isinstance(x, str)]
                    if call.name in ("morphMany", "morphOne", "morphToMany", "morphedByMany"):
                        rel["morph"] = a[1] if len(a) > 1 and isinstance(a[1], str) else None
                        rel["keys"] = [x for x in a[2:] if isinstance(x, str)]
                    for x in v.calls[1:]:
                        if x.name == "using" and x.args and isinstance(x.args[0], Cls):
                            rel["using"] = str(x.args[0])
                    d["relations"].append(rel)
                    break
        fac = f"Database\\Factories\\{c.name}Factory"
        if proj.idx.get(fac):
            d["factory"] = fac
        models[c.fqn] = d
    # observers / policies registered in providers
    for prov in proj.classes_by_role("provider"):
        pf = prov.file
        if not prov.body:
            continue
        for root, calls in find_statics(pf, prov.body[0], prov.body[1], {r["name"] for r in models.values()} | {"Gate"}):
            call = calls[0]
            if call.name == "observe" and root.cls in models:
                models[root.cls]["observers"] += class_strs(call.args)
            if call.name == "policy" and short(root.cls) == "Gate" and len(call.args) >= 2:
                m, p = class_strs(call.args[0]), class_strs(call.args[1])
                if m and p and m[0] in models:
                    models[m[0]]["policy"] = p[0]
        pol = prop_value(proj, prov, "policies")
        if isinstance(pol, dict):
            for k, v in pol.items():
                if str(k) in models and isinstance(v, str):
                    models[str(k)]["policy"] = str(v)
        obs = prop_value(proj, prov, "observers")
        if isinstance(obs, dict):
            for k, v in obs.items():
                if str(k) in models:
                    models[str(k)]["observers"] += class_strs(v)
    for d in models.values():
        if not d["policy"]:
            guess = f"App\\Policies\\{d['name']}Policy"
            if proj.idx.get(guess):
                d["policy"] = guess
                d["policy_auto"] = True
        d["observers"] = sorted(set(d["observers"]))
    return models


# =====================================================================================================
# 9. Database schema from migrations (+ schema dumps)
# =====================================================================================================

COLUMN_TYPES = {
    "string": "string", "char": "char", "text": "text", "tinyText": "text", "mediumText": "text", "longText": "text",
    "integer": "int", "tinyInteger": "tinyint", "smallInteger": "smallint", "mediumInteger": "mediumint",
    "bigInteger": "bigint", "unsignedInteger": "int", "unsignedTinyInteger": "tinyint",
    "unsignedSmallInteger": "smallint", "unsignedMediumInteger": "mediumint", "unsignedBigInteger": "bigint",
    "decimal": "decimal", "unsignedDecimal": "decimal", "double": "double", "float": "float", "boolean": "boolean",
    "date": "date", "dateTime": "datetime", "dateTimeTz": "datetime", "time": "time", "timeTz": "time",
    "timestamp": "timestamp", "timestampTz": "timestamp", "year": "year", "json": "json", "jsonb": "jsonb",
    "binary": "binary", "enum": "enum", "set": "set", "ipAddress": "ip", "macAddress": "mac", "uuid": "uuid",
    "ulid": "ulid", "geometry": "geometry", "geography": "geography", "point": "point", "polygon": "polygon",
    "lineString": "linestring", "multiPolygon": "multipolygon", "vector": "vector", "rememberToken": "string",
    "foreignId": "bigint", "foreignUuid": "uuid", "foreignUlid": "ulid", "id": "bigint", "increments": "int",
    "bigIncrements": "bigint", "mediumIncrements": "mediumint", "smallIncrements": "smallint",
    "tinyIncrements": "tinyint", "foreignIdFor": "bigint", "computed": "computed",
}
FRAMEWORK_TABLES = {"migrations", "password_resets", "password_reset_tokens", "failed_jobs", "jobs", "job_batches",
                    "cache", "cache_locks", "sessions", "personal_access_tokens", "notifications",
                    "telescope_entries", "telescope_entries_tags", "telescope_monitoring", "pulse_values",
                    "pulse_entries", "pulse_aggregates", "oauth_access_tokens", "oauth_auth_codes", "oauth_clients",
                    "oauth_personal_access_clients", "oauth_refresh_tokens", "oauth_device_codes", "activity_log",
                    "media", "permissions", "roles", "model_has_permissions", "model_has_roles",
                    "role_has_permissions", "imports", "exports", "failed_import_rows", "action_events",
                    "nova_notifications", "nova_field_attachments", "nova_pending_field_attachments",
                    "websockets_statistics_entries", "health_check_result_history_items"}


def _guess_fk_table(col):
    base = col[:-3] if col.endswith("_id") else col
    return plural(base)


class SchemaBuilder:
    def __init__(self, proj):
        self.proj = proj
        self.tables = {}
        self.migrations = []
        self.raw_statements = []

    def table(self, name, rel, create=False):
        if create or name not in self.tables:
            self.tables[name] = {"name": name, "columns": {}, "fks": [], "indexes": [], "created_in": rel if create else None,
                                 "altered_in": [], "source": "migrations", "primary": None, "polymorphic": []}
        return self.tables[name]

    def col(self, t, name, typ, rel, **kw):
        c = {"name": name, "type": typ, "nullable": False, "default": None, "unique": False, "index": False,
             "primary": False, "unsigned": False, "auto": False, "comment": None, "fk": None, "detail": "",
             "source": rel, "model_fk": None}
        c.update(kw)
        t["columns"][name] = c
        return c

    def run(self):
        files = sorted(walk(self.proj.root, "database/migrations", exts=(".php",)), key=lambda x: os.path.basename(x[1]))
        for ap, rel in files:
            pf = self.proj.php.get(rel) or parse_php(ap, rel, self.proj.root)
            if pf is None:
                continue
            m = re.match(r"(\d{4})_(\d{2})_(\d{2})_(\d{6})_(.*)\.php$", os.path.basename(rel))
            mig = {"file": rel, "name": os.path.basename(rel)[:-4],
                   "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "", "ops": [], "has_down": False}
            rng = (0, len(pf.toks))
            for c in pf.classes:
                if "up" in c.methods and c.methods["up"].body:
                    rng = c.methods["up"].body
                    mig["has_down"] = "down" in c.methods and bool(c.methods["down"].body) and \
                        c.methods["down"].body[1] - c.methods["down"].body[0] > 1
                    break
            for root, calls in find_statics(pf, rng[0], rng[1], {"Schema"}):
                self.schema_call(pf, rel, calls, mig)
            for root, calls in find_statics(pf, rng[0], rng[1], {"DB"}, {"statement", "unprepared"}):
                mig["ops"].append({"op": "sql", "table": None, "detail": "raw SQL statement"})
            self.migrations.append(mig)
        self.load_schema_dumps()
        self.post_process()
        return self

    def schema_call(self, pf, rel, calls, mig):
        call = next((c for c in calls if c.name in ("create", "table", "drop", "dropIfExists", "rename", "dropColumns")), None)
        if call is None:
            return
        a = call.args
        tname = a[0] if a and isinstance(a[0], str) else None
        if tname is None:
            return
        if call.name in ("drop", "dropIfExists"):
            self.tables.pop(tname, None)
            mig["ops"].append({"op": "drop", "table": tname, "detail": ""})
            return
        if call.name == "rename":
            to = a[1] if len(a) > 1 and isinstance(a[1], str) else None
            if to and tname in self.tables:
                self.tables[to] = self.tables.pop(tname)
                self.tables[to]["name"] = to
            mig["ops"].append({"op": "rename", "table": tname, "detail": f"→ {to}"})
            return
        if call.name == "dropColumns":
            t = self.table(tname, rel)
            for cname in strs(a[1:]):
                t["columns"].pop(cname, None)
            mig["ops"].append({"op": "alter", "table": tname, "detail": "− " + ", ".join(strs(a[1:]))})
            return
        closure = next((x for x in a[1:] if isinstance(x, Node) and x.type == "closure"), None)
        create = call.name == "create"
        t = self.table(tname, rel, create=create)
        if not create:
            t["altered_in"].append(rel)
        op = {"op": "create" if create else "alter", "table": tname, "added": [], "dropped": [], "changed": [],
              "renamed": [], "detail": ""}
        if closure is not None:
            bp = "$" + (closure.params[0]["name"] if closure.params and closure.params[0]["name"] else "table")
            for chain in find_var_chains(pf, closure.start, closure.end, {bp}):
                try:
                    self.blueprint(t, chain, rel, op)
                except (IndexError, TypeError, AttributeError):
                    pass
        bits = []
        if op["added"]:
            bits.append("+ " + ", ".join(op["added"][:8]) + ("…" if len(op["added"]) > 8 else ""))
        if op["dropped"]:
            bits.append("− " + ", ".join(op["dropped"]))
        if op["changed"]:
            bits.append("~ " + ", ".join(op["changed"]))
        if op["renamed"]:
            bits.append("renamed " + ", ".join(op["renamed"]))
        op["detail"] = "; ".join(bits)
        mig["ops"].append(op)

    def blueprint(self, t, calls, rel, op):
        first, mods = calls[0], calls[1:]
        nm, a = first.name, first.args
        s0 = a[0] if a and isinstance(a[0], str) and not isinstance(a[0], Cls) else None
        added = []

        def add(name, typ, **kw):
            c = self.col(t, name, typ, rel, **kw)
            added.append(c)
            return c

        if nm == "id":
            add(s0 or "id", "bigint", primary=True, auto=True, unsigned=True)
        elif nm in ("increments", "bigIncrements", "mediumIncrements", "smallIncrements", "tinyIncrements"):
            add(s0 or "id", COLUMN_TYPES[nm], primary=True, auto=True, unsigned=True)
        elif nm in ("timestamps", "nullableTimestamps", "timestampsTz"):
            add("created_at", "timestamp", nullable=True)
            add("updated_at", "timestamp", nullable=True)
        elif nm in ("softDeletes", "softDeletesTz", "softDeletesDatetime"):
            add(s0 or "deleted_at", "timestamp", nullable=True)
        elif nm == "rememberToken":
            add("remember_token", "string", nullable=True, detail="100")
        elif nm in ("morphs", "nullableMorphs", "uuidMorphs", "nullableUuidMorphs", "ulidMorphs", "nullableUlidMorphs", "numericMorphs"):
            idtype = "uuid" if "Uuid" in nm else "ulid" if "Ulid" in nm else "bigint"
            nullable = nm.startswith("nullable")
            if s0:
                add(f"{s0}_type", "string", nullable=nullable)
                add(f"{s0}_id", idtype, nullable=nullable, unsigned=idtype == "bigint")
                t["polymorphic"].append(s0)
        elif nm == "foreignIdFor":
            model = str(a[0]) if a and isinstance(a[0], str) else None
            cname = a[1] if len(a) > 1 and isinstance(a[1], str) else (snake(short(model)) + "_id" if model else "?_id")
            add(cname, "bigint", unsigned=True, model_fk=model)
        elif nm in ("foreign",):
            cols = strs(a[0]) if a else []
            fk = {"columns": cols, "table": None, "column": "id", "on_delete": None}
            for m in mods:
                if m.name == "references" and m.args:
                    fk["column"] = ",".join(strs(m.args[0]))
                elif m.name == "on" and m.args and isinstance(m.args[0], str):
                    fk["table"] = m.args[0]
                elif m.name in ("onDelete",) and m.args:
                    fk["on_delete"] = str(m.args[0])
                elif m.name in ("cascadeOnDelete", "restrictOnDelete", "nullOnDelete", "noActionOnDelete"):
                    fk["on_delete"] = {"cascadeOnDelete": "cascade", "restrictOnDelete": "restrict",
                                       "nullOnDelete": "set null", "noActionOnDelete": "no action"}[m.name]
            for cn in cols:
                if cn in t["columns"]:
                    t["columns"][cn]["fk"] = {"table": fk["table"], "column": fk["column"], "on_delete": fk["on_delete"]}
            t["fks"].append(fk)
            return
        elif nm in ("primary", "unique", "index", "fullText", "spatialIndex") and a and isinstance(a[0], list):
            t["indexes"].append({"type": nm, "columns": strs(a[0])})
            if nm == "primary":
                t["primary"] = strs(a[0])
            return
        elif nm in ("primary", "unique", "index") and s0 and s0 in t["columns"]:
            t["columns"][s0][nm if nm != "index" else "index"] = True
            return
        elif nm == "dropColumn" or nm == "dropColumns":
            for cname in strs(a):
                t["columns"].pop(cname, None)
                op["dropped"].append(cname)
            return
        elif nm == "renameColumn" and len(a) >= 2 and isinstance(a[1], str):
            if s0 in t["columns"]:
                c = t["columns"].pop(s0)
                c["name"] = a[1]
                t["columns"][a[1]] = c
            op["renamed"].append(f"{s0}→{a[1]}")
            return
        elif nm in ("dropTimestamps", "dropTimestampsTz"):
            for cname in ("created_at", "updated_at"):
                t["columns"].pop(cname, None)
            op["dropped"].append("timestamps")
            return
        elif nm in ("dropSoftDeletes", "dropSoftDeletesTz"):
            t["columns"].pop(s0 or "deleted_at", None)
            op["dropped"].append("deleted_at")
            return
        elif nm == "dropRememberToken":
            t["columns"].pop("remember_token", None)
            op["dropped"].append("remember_token")
            return
        elif nm == "dropMorphs" and s0:
            t["columns"].pop(f"{s0}_type", None)
            t["columns"].pop(f"{s0}_id", None)
            op["dropped"].append(f"{s0}_type/_id")
            return
        elif nm in ("dropForeign", "dropConstrainedForeignId", "dropForeignIdFor"):
            cols = strs(a[0]) if a and isinstance(a[0], list) else []
            if s0 and not cols:
                m = re.match(rf"^{re.escape(t['name'])}_(.+)_foreign$", s0)
                cols = [m.group(1)] if m else [s0]
            for cn in cols:
                if cn in t["columns"]:
                    t["columns"][cn]["fk"] = None
                    if nm == "dropConstrainedForeignId":
                        t["columns"].pop(cn, None)
                        op["dropped"].append(cn)
            t["fks"] = [f for f in t["fks"] if not set(f["columns"]) & set(cols)]
            return
        elif nm in ("dropPrimary", "dropUnique", "dropIndex", "dropFullText", "engine", "charset", "collation",
                    "comment", "temporary", "after"):
            return
        elif nm in COLUMN_TYPES and s0:
            typ = COLUMN_TYPES[nm]
            detail = ""
            if nm in ("string", "char") and len(a) > 1 and isinstance(a[1], int):
                detail = str(a[1])
            elif nm in ("decimal", "unsignedDecimal", "double", "float") and len(a) > 1:
                detail = ",".join(str(x) for x in a[1:3] if isinstance(x, int))
            elif nm in ("enum", "set") and len(a) > 1:
                detail = ", ".join(strs(a[1]))
            add(s0, typ, unsigned=nm.startswith("unsigned") or nm.startswith("foreign"), detail=detail)
        else:
            return
        if not added:
            return
        c = added[-1]
        is_change = any(m.name == "change" for m in mods)
        for m in mods:
            ma = m.args
            if m.name == "nullable":
                c["nullable"] = not (ma and ma[0] is False)
            elif m.name == "default" and ma:
                c["default"] = fmt_val(ma[0])
            elif m.name in ("useCurrent",):
                c["default"] = "CURRENT_TIMESTAMP"
            elif m.name == "unique":
                c["unique"] = True
            elif m.name == "index":
                c["index"] = True
            elif m.name == "primary":
                c["primary"] = True
            elif m.name == "unsigned":
                c["unsigned"] = True
            elif m.name == "autoIncrement":
                c["auto"] = True
            elif m.name == "comment" and ma and isinstance(ma[0], str):
                c["comment"] = ma[0]
            elif m.name == "constrained":
                ft = ma[0] if ma and isinstance(ma[0], str) else (None if c.get("model_fk") else _guess_fk_table(c["name"]))
                fc = ma[1] if len(ma) > 1 and isinstance(ma[1], str) else "id"
                c["fk"] = {"table": ft, "column": fc, "on_delete": None}
            elif m.name == "references" and ma:
                c["fk"] = c["fk"] or {"table": None, "column": None, "on_delete": None}
                c["fk"]["column"] = ",".join(strs(ma[0]))
            elif m.name == "on" and ma and isinstance(ma[0], str):
                c["fk"] = c["fk"] or {"table": None, "column": "id", "on_delete": None}
                c["fk"]["table"] = ma[0]
            elif m.name in ("cascadeOnDelete", "restrictOnDelete", "nullOnDelete", "noActionOnDelete", "onDelete"):
                if c["fk"]:
                    c["fk"]["on_delete"] = str(ma[0]) if m.name == "onDelete" and ma else \
                        {"cascadeOnDelete": "cascade", "restrictOnDelete": "restrict", "nullOnDelete": "set null",
                         "noActionOnDelete": "no action"}.get(m.name)
        for c2 in added:
            (op["changed"] if is_change else op["added"]).append(c2["name"])

    def load_schema_dumps(self):
        for ap, rel in walk(self.proj.root, "database/schema", exts=(".sql", ".dump")):
            sql = read_text(ap)
            if not sql:
                continue
            for m in re.finditer(r"CREATE TABLE (?:IF NOT EXISTS )?([`\"\w.]+)\s*\((.*?)\)\s*(?:ENGINE|;|WITH|TABLESPACE|PARTITION)",
                                 sql, re.S | re.I):
                tname = m.group(1).strip('`"').split(".")[-1]
                if tname in self.tables:
                    continue
                t = self.table(tname, rel, create=True)
                t["source"] = "schema dump"
                depth, buf, parts = 0, "", []
                for ch in m.group(2):
                    depth += ch == "("
                    depth -= ch == ")"
                    if ch == "," and depth == 0:
                        parts.append(buf)
                        buf = ""
                    else:
                        buf += ch
                parts.append(buf)
                for part in parts:
                    p = part.strip()
                    up = p.upper()
                    fk = re.search(r"FOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+([`\"\w.]+)\s*\(([^)]+)\)(?:.*?ON DELETE (CASCADE|SET NULL|RESTRICT|NO ACTION))?", p, re.I)
                    if fk:
                        cols = [x.strip(' `"') for x in fk.group(1).split(",")]
                        ft = fk.group(2).strip('`"').split(".")[-1]
                        for cn in cols:
                            if cn in t["columns"]:
                                t["columns"][cn]["fk"] = {"table": ft, "column": fk.group(3).strip(' `"'),
                                                          "on_delete": (fk.group(4) or "").lower() or None}
                        continue
                    if up.startswith(("PRIMARY KEY", "UNIQUE", "KEY ", "INDEX", "CONSTRAINT", "CHECK", "FULLTEXT")):
                        pk = re.match(r"PRIMARY KEY\s*\(([^)]+)\)", p, re.I)
                        if pk:
                            for cn in [x.strip(' `"') for x in pk.group(1).split(",")]:
                                if cn in t["columns"]:
                                    t["columns"][cn]["primary"] = True
                        continue
                    cm = re.match(r"[`\"]?([\w]+)[`\"]?\s+([\w ]+?(?:\([^)]*\))?)(?:\s|$)", p)
                    if not cm:
                        continue
                    typ = cm.group(2).split("(")[0].strip().lower().replace("character varying", "varchar")
                    self.col(t, cm.group(1), typ.split()[0] if typ else "?", rel, nullable="NOT NULL" not in up,
                             primary="PRIMARY KEY" in up, auto="AUTO_INCREMENT" in up or "AUTOINCREMENT" in up,
                             unsigned="UNSIGNED" in up)
            for m in re.finditer(r"ALTER TABLE (?:ONLY )?([\w.\"]+)\s+ADD CONSTRAINT [\w\"]+ FOREIGN KEY \(([^)]+)\) REFERENCES ([\w.\"]+)\s*\(([^)]+)\)(?:\s+ON DELETE (CASCADE|SET NULL|RESTRICT))?", sql, re.I):
                tname = m.group(1).strip('"').split(".")[-1]
                if tname in self.tables:
                    for cn in [x.strip(' "') for x in m.group(2).split(",")]:
                        if cn in self.tables[tname]["columns"]:
                            self.tables[tname]["columns"][cn]["fk"] = {"table": m.group(3).strip('"').split(".")[-1],
                                                                       "column": m.group(4).strip(' "'),
                                                                       "on_delete": (m.group(5) or "").lower() or None}

    def post_process(self):
        for t in self.tables.values():
            for fk in t["fks"]:
                for cn in fk["columns"]:
                    if cn in t["columns"] and not t["columns"][cn]["fk"] and fk["table"]:
                        t["columns"][cn]["fk"] = {"table": fk["table"], "column": fk["column"], "on_delete": fk["on_delete"]}

    def resolve_model_fks(self, models):
        for t in self.tables.values():
            for c in t["columns"].values():
                if c.get("model_fk"):
                    md = models.get(c["model_fk"])
                    tbl = md["table"] if md else _guess_fk_table(c["name"])
                    if c["fk"] is None:
                        c["fk"] = {"table": tbl, "column": "id", "on_delete": None, "implicit": True}
                    elif c["fk"].get("table") is None:
                        c["fk"]["table"] = tbl

    def to_dict(self):
        out = {}
        for name, t in sorted(self.tables.items()):
            out[name] = {**t, "columns": list(t["columns"].values())}
        return out


def is_pivot(t, pivot_names):
    if t["name"] in pivot_names:
        return True
    cols = [c for c in t["columns"] if c["name"] not in ("id", "created_at", "updated_at")]
    fks = [c for c in cols if c.get("fk")]
    return len(fks) == 2 and len(cols) <= 4 and "_" in t["name"]


# =====================================================================================================
# 10. Events, listeners, jobs, mail, notifications
# =====================================================================================================

DISPATCH_STATICS = {"dispatch", "dispatchSync", "dispatchNow", "dispatchIf", "dispatchUnless", "dispatchAfterResponse",
                    "broadcast", "withChain"}


def analyze_async(proj, models):
    idx = proj.idx
    out = {"events": {}, "listeners": {}, "jobs": {}, "mail": {}, "notifications": {}, "edges": [], "subscribers": [],
           "wiring": []}
    discovered = []
    major = proj.laravel_major() or 11
    discovery_on = major >= 11 or any("shouldDiscoverEvents" in c.methods for c in proj.classes_by_role("provider"))

    def entry(c, extra=None):
        d = {"fqn": c.fqn, "name": c.name, "file": c.file.rel, "line": c.line, "doc": c.doc,
             "queued": "Illuminate\\Contracts\\Queue\\ShouldQueue" in idx.all_interfaces(c),
             "traits": sorted(short(t) for t in idx.all_traits(c))}
        if extra:
            d.update(extra)
        return d

    for c in proj.classes_by_role("event"):
        ifs = idx.all_interfaces(c)
        out["events"][c.fqn] = entry(c, {"broadcast": any("ShouldBroadcast" in i for i in ifs), "listeners": [],
                                          "dispatched_by": []})
    for c in proj.classes_by_role("listener"):
        handles = []
        for m in c.methods.values():
            if m.name == "handle" or m.name == "__invoke" or (m.name.startswith("handle") and m.visibility == "public"):
                if m.params and m.params[0]["types"]:
                    for t in m.params[0]["types"]:
                        if t not in BUILTIN_TYPES:
                            handles.append((t, m.name))
        out["listeners"][c.fqn] = entry(c, {"handles": [h[0] for h in handles], "events": []})
        discovered.extend((ev, c.fqn, meth) for ev, meth in handles)
    for c in proj.classes_by_role("job"):
        q = prop_value(proj, c, "queue")
        out["jobs"][c.fqn] = entry(c, {
            "queue": q if isinstance(q, str) else None,
            "tries": prop_value(proj, c, "tries"), "timeout": prop_value(proj, c, "timeout"),
            "unique": any("ShouldBeUnique" in i for i in idx.all_interfaces(c)),
            "batchable": "Batchable" in {short(t) for t in idx.all_traits(c)},
            "deps": [p["type"] for p in (c.methods["handle"].params if "handle" in c.methods else []) if p["type"]],
            "dispatched_by": []})
    for c in proj.classes_by_role("mail"):
        views = sorted(set(re.findall(r"(?:view|markdown|text|html)\s*:\s*['\"]([\w.\-:/]+)['\"]", c.file.text[:200000])))
        for m in c.methods.values():
            sc = c.file.method_scan(c, m)
            views += [s for (mn, s, _, r) in sc.mcalls if mn in ("view", "markdown", "text") and s]
        subject = re.search(r"subject\s*:\s*['\"]([^'\"]+)['\"]", c.file.text) or re.search(r"->subject\(\s*['\"]([^'\"]+)", c.file.text)
        out["mail"][c.fqn] = entry(c, {"views": sorted(set(views)), "subject": subject.group(1) if subject else None,
                                        "sent_by": []})
    for c in proj.classes_by_role("notification"):
        via = return_value(c.file, c.methods.get("via"))
        channels = strs(via) if via is not None else []
        channels += class_strs(via) if via is not None else []
        for m in c.methods:
            mm = re.fullmatch(r"to([A-Z]\w*)", m)
            if mm and mm.group(1) not in ("Array",):
                channels.append(mm.group(1).lower())
        out["notifications"][c.fqn] = entry(c, {"channels": sorted({short(x) for x in channels}), "sent_by": []})

    # explicit wiring in providers: $listen, $subscribe, Event::listen(), $observers
    for prov in proj.classes_by_role("provider"):
        pf = prov.file
        lst = prop_value(proj, prov, "listen")
        if isinstance(lst, dict):
            for ev, ls in lst.items():
                for l in class_strs(ls):
                    out["wiring"].append({"event": str(ev), "listener": l, "method": "handle", "source": f"{short(prov.fqn)}::$listen"})
        sub = prop_value(proj, prov, "subscribe")
        out["subscribers"] += class_strs(sub) if sub else []
        if prov.body:
            for root, calls in find_statics(pf, prov.body[0], prov.body[1], {"Event"}, {"listen", "subscribe"}):
                call = calls[0]
                if call.name == "subscribe":
                    out["subscribers"] += class_strs(call.args)
                    continue
                if not call.args:
                    continue
                evs = class_strs(call.args[0]) or ([call.args[0]] if isinstance(call.args[0], str) else [])
                target = call.args[1] if len(call.args) > 1 else None
                if isinstance(call.args[0], Node) and call.args[0].type == "closure":
                    # Event::listen(function (OrderShipped $e) {...})
                    cl = call.args[0]
                    evs = [t for p in (cl.params or [])[:1] for t in p["types"] if t not in BUILTIN_TYPES]
                    target = None
                ls = class_strs(target) if target is not None else []
                for ev in evs:
                    if ls:
                        for l in ls:
                            out["wiring"].append({"event": ev, "listener": l, "method": "handle", "source": f"Event::listen in {short(prov.fqn)}"})
                    else:
                        out["wiring"].append({"event": ev, "listener": None, "method": None, "source": f"closure in {short(prov.fqn)}", "line": call.line, "file": pf.rel})
    for ev, l, meth in discovered:
        out["wiring"].append({"event": ev, "listener": l, "method": meth,
                              "source": "auto-discovery (type-hint)" if discovery_on else "type-hint only (event discovery looks off)"})
    seen = set()
    wiring = []
    for w in out["wiring"]:
        key = (w["event"], w["listener"])
        if key in seen and w["listener"]:
            continue
        seen.add(key)
        wiring.append(w)
    out["wiring"] = wiring
    for w in wiring:
        if w["event"] in out["events"]:
            out["events"][w["event"]]["listeners"].append(w["listener"] or "Closure")
        if w["listener"] in out["listeners"]:
            out["listeners"][w["listener"]]["events"].append(w["event"])

    # who dispatches what: scan every method body in app code
    targets = {}
    for k in ("events", "jobs", "mail", "notifications"):
        for fqn in out[k]:
            targets[fqn] = k
    edge_seen = set()
    for c in idx.by_fqn.values():
        if c.role in ("test", "factory", "seeder", "migration"):
            continue
        for m in c.methods.values():
            sc = c.file.method_scan(c, m)
            hits = [(f, ln) for f, ln in sc.news if f in targets]
            hits += [(f, ln) for (f, meth, _s, ln) in sc.statics if f in targets and meth in DISPATCH_STATICS]
            for f, ln in hits:
                key = (c.fqn, f)
                if key in edge_seen or f == c.fqn:
                    continue
                edge_seen.add(key)
                kind = targets[f]
                out["edges"].append({"from": c.fqn, "from_role": c.role, "method": m.name, "to": f, "kind": kind,
                                     "file": c.file.rel, "line": ln})
                bucket = out[kind][f]
                bucket.setdefault("dispatched_by" if kind in ("events", "jobs") else "sent_by", []).append(f"{short(c.fqn)}::{m.name}")
    for md in models.values():
        for when, ev in md["dispatches_events"].items():
            out["edges"].append({"from": md["fqn"], "from_role": "model", "method": f"model {when}", "to": ev,
                                 "kind": "events", "file": md["file"], "line": md["line"]})
            if ev in out["events"]:
                out["events"][ev]["dispatched_by"].append(f"{md['name']} ({when})")
    return out


# =====================================================================================================
# 11. Console: commands, closure commands, schedule, broadcast channels
# =====================================================================================================

FREQ_TEXT = {
    "everySecond": "every second", "everyTwoSeconds": "every 2 s", "everyFiveSeconds": "every 5 s",
    "everyTenSeconds": "every 10 s", "everyFifteenSeconds": "every 15 s", "everyTwentySeconds": "every 20 s",
    "everyThirtySeconds": "every 30 s", "everyMinute": "every minute", "everyTwoMinutes": "every 2 min",
    "everyThreeMinutes": "every 3 min", "everyFourMinutes": "every 4 min", "everyFiveMinutes": "every 5 min",
    "everyTenMinutes": "every 10 min", "everyFifteenMinutes": "every 15 min", "everyThirtyMinutes": "every 30 min",
    "hourly": "hourly", "everyOddHour": "every odd hour", "everyTwoHours": "every 2 h", "everyThreeHours": "every 3 h",
    "everyFourHours": "every 4 h", "everySixHours": "every 6 h", "daily": "daily at 00:00", "weekly": "weekly (Sun 00:00)",
    "monthly": "monthly (1st, 00:00)", "quarterly": "quarterly", "yearly": "yearly", "weekdays": "on weekdays",
    "weekends": "at weekends", "mondays": "on Mondays", "tuesdays": "on Tuesdays", "wednesdays": "on Wednesdays",
    "thursdays": "on Thursdays", "fridays": "on Fridays", "saturdays": "on Saturdays", "sundays": "on Sundays",
    "lastDayOfMonth": "last day of month",
}
FREQ_ARG = {"dailyAt": "daily at {0}", "hourlyAt": "hourly at :{0}", "twiceDaily": "twice daily ({0}h & {1}h)",
            "twiceDailyAt": "twice daily ({0}h & {1}h at :{2})", "weeklyOn": "weekly on day {0} at {1}",
            "monthlyOn": "monthly on day {0} at {1}", "twiceMonthly": "twice monthly ({0} & {1})",
            "yearlyOn": "yearly on {0}/{1}", "cron": "cron “{0}”", "at": "at {0}", "between": "between {0} and {1}",
            "unlessBetween": "except {0}–{1}", "timezone": "TZ {0}", "environments": "only in {0}", "days": "on days {0}"}
SCHEDULE_FLAGS = {"withoutOverlapping", "onOneServer", "runInBackground", "evenInMaintenanceMode", "sendOutputTo",
                  "appendOutputTo", "emailOutputTo", "emailOutputOnFailure", "onSuccess", "onFailure", "before", "after",
                  "pingBefore", "thenPing", "when", "skip", "name", "description", "onQueue"}


def describe_schedule(calls):
    first = calls[0]
    a = first.args
    kind, target = first.name, "?"
    if kind == "command":
        target = str(a[0]) if a and isinstance(a[0], str) else repr(a[0]) if a else "?"
        if isinstance(a[0] if a else None, Cls):
            target = short(a[0])
    elif kind == "job":
        if a and isinstance(a[0], Node) and a[0].type == "new":
            target = short(a[0].cls)
        elif a and isinstance(a[0], Cls):
            target = short(a[0])
    elif kind in ("call", "exec"):
        target = "Closure" if kind == "call" else (a[0] if a and isinstance(a[0], str) else "?")
    freq, flags = [], []
    for c in calls[1:]:
        if c.name in FREQ_TEXT:
            freq.append(FREQ_TEXT[c.name])
        elif c.name in FREQ_ARG:
            vals = [fmt_val(x).strip("'") if not isinstance(x, list) else ", ".join(strs(x)) for x in c.args]
            try:
                freq.append(FREQ_ARG[c.name].format(*(vals + ["?"] * 3)))
            except (IndexError, KeyError):
                freq.append(c.name)
        elif c.name in SCHEDULE_FLAGS:
            flags.append(c.name)
    return {"type": kind, "target": target, "frequency": ", ".join(freq) or "(no frequency set)", "flags": flags,
            "line": first.line}


def analyze_console(proj, rp):
    out = {"commands": [], "closure_commands": [], "schedule": [], "channels": []}
    for c in proj.classes_by_role("command"):
        sig = prop_value(proj, c, "signature")
        name = prop_value(proj, c, "name")
        desc = prop_value(proj, c, "description")
        for a in c.attrs:
            if short(a["name"]) == "AsCommand":
                name = a["kw"].get("name") or (a["args"][0] if a["args"] else name)
                desc = a["kw"].get("description") or (a["args"][1] if len(a["args"]) > 1 else desc)
        cmd = (sig.split()[0] if isinstance(sig, str) and sig.split() else name if isinstance(name, str) else None)
        out["commands"].append({"fqn": c.fqn, "name": cmd or kebab(c.name), "signature": sig if isinstance(sig, str) else cmd,
                                "description": desc if isinstance(desc, str) else c.doc, "file": c.file.rel, "line": c.line})
    files = [proj.p(f) if not os.path.isabs(f) else f for f in rp.console_files]
    sources = []
    for f in files:
        rel = proj.rel(f)
        pf = proj.php.get(rel)
        if pf is not None:
            sources.append((pf, 0, len(pf.toks)))
    kern = proj.php.get("app/Console/Kernel.php")
    if kern is not None:
        for c in kern.classes:
            m = c.methods.get("schedule")
            if m and m.body:
                for calls in find_var_chains(kern, m.body[0], m.body[1], {"$schedule"}):
                    if calls[0].name in ("command", "job", "call", "exec"):
                        out["schedule"].append({**describe_schedule(calls), "file": kern.rel})
    app = proj.php.get("bootstrap/app.php")
    if app is not None:
        for k, t in enumerate(app.toks):
            if t.k == "name" and t.v == "withSchedule" and k + 1 < len(app.toks) and app.toks[k + 1].v == "(":
                close = app.pair.get(k + 1, k + 1)
                for calls in find_var_chains(app, k + 2, close, {"$schedule"}):
                    if calls[0].name in ("command", "job", "call", "exec"):
                        out["schedule"].append({**describe_schedule(calls), "file": app.rel})
    for pf, s, e in sources:
        for root, calls in find_statics(pf, s, e, {"Schedule"}):
            if calls[0].name in ("command", "job", "call", "exec"):
                out["schedule"].append({**describe_schedule(calls), "file": pf.rel})
        for root, calls in find_statics(pf, s, e, {"Artisan"}, {"command"}):
            a = calls[0].args
            sig = a[0] if a and isinstance(a[0], str) else "?"
            purpose = next((c.args[0] for c in calls[1:] if c.name in ("purpose", "describe") and c.args and isinstance(c.args[0], str)), "")
            sched = [c.name for c in calls[1:] if c.name in FREQ_TEXT or c.name in FREQ_ARG]
            out["closure_commands"].append({"name": sig.split()[0] if sig.split() else sig, "signature": sig,
                                            "description": purpose, "file": pf.rel, "line": calls[0].line})
            if sched:
                out["schedule"].append({**describe_schedule([Call("command", [sig.split()[0]], {}, calls[0].line)] + calls[1:]), "file": pf.rel})
    for f in rp.channel_files:
        ap = proj.p(f) if not os.path.isabs(f) else f
        pf = proj.php.get(proj.rel(ap))
        if pf is None:
            continue
        for root, calls in find_statics(pf, 0, len(pf.toks), {"Broadcast"}, {"channel"}):
            a = calls[0].args
            if a and isinstance(a[0], str):
                handler = short(a[1]) if len(a) > 1 and isinstance(a[1], Cls) else "Closure"
                out["channels"].append({"name": a[0], "handler": handler, "file": pf.rel, "line": calls[0].line,
                                        "private": True})
    return out


# =====================================================================================================
# 12. Views, Blade components, Livewire, Volt, Inertia, Filament, assets
# =====================================================================================================

def _directive_args(text, start):
    """Given index just after '(' return (args_text, end_index) honouring nesting and quotes."""
    depth, i, q = 1, start, None
    while i < len(text):
        ch = text[i]
        if q:
            if ch == "\\":
                i += 2
                continue
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[start:i], i
        i += 1
    return text[start:], len(text)


def _split_top(s):
    out, depth, q, buf = [], 0, None, ""
    for ch in s:
        if q:
            buf += ch
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


def _lit(s):
    s = (s or "").strip()
    m = re.fullmatch(r"""(['"])([^'"]+)\1""", s)
    return m.group(2) if m else None


BLADE_DIR_RE = re.compile(r"@(extends|include|includeIf|includeWhen|includeUnless|includeFirst|each|component|livewire|section|yield|push|stack|prepend|vite|props|aware|inertia|livewireStyles|livewireScripts|filamentStyles|filamentScripts)\b\s*(\()?")


def analyze_views(proj):
    views = {}
    base = "resources/views/"
    for ap, rel in walk(proj.root, "resources/views", exts=(".php", ".html")):
        if not rel.startswith(base):
            continue
        name = rel[len(base):]
        name = re.sub(r"(\.blade)?\.php$|\.html$", "", name).replace("/", ".")
        text = read_text(ap)
        v = {"name": name, "file": rel, "lines": text.count("\n") + 1, "extends": None, "includes": [], "components": [],
             "livewire": [], "sections": [], "yields": [], "stacks": [], "pushes": [], "vite": [], "inertia_root": False,
             "unescaped": [], "wire": Counter(), "alpine": "x-data" in text, "is_volt": False, "props": [],
             "kind": "view", "forms": len(re.findall(r"<form\b", text, re.I)), "used_by": []}
        if name.startswith("components."):
            v["kind"] = "component"
        elif name.startswith(("layouts.", "layout.")) or ".layouts." in name:
            v["kind"] = "layout"
        elif name.startswith("livewire.") or name.startswith("pages."):
            v["kind"] = "livewire"
        elif name.startswith(("emails.", "mail.", "vendor.mail")):
            v["kind"] = "email"
        if re.search(r"new\s+(?:#\[[^\]]*\]\s*)*class\s+extends\s+(?:\\?Livewire\\Volt\\)?Component|use\s+function\s+Livewire\\Volt\\|Livewire\\Volt\\Component", text):
            v["is_volt"] = True
            v["kind"] = "volt"
        for m in BLADE_DIR_RE.finditer(text):
            d = m.group(1)
            args = []
            if m.group(2):
                a_text, _ = _directive_args(text, m.end())
                args = _split_top(a_text)
            first = _lit(args[0]) if args else None
            line = text.count("\n", 0, m.start()) + 1
            if d == "extends" and first:
                v["extends"] = first
            elif d in ("include", "includeIf", "each") and first:
                v["includes"].append(first)
            elif d in ("includeWhen", "includeUnless") and len(args) > 1 and _lit(args[1]):
                v["includes"].append(_lit(args[1]))
            elif d == "includeFirst" and args:
                v["includes"] += re.findall(r"""['"]([\w.\-:/]+)['"]""", args[0])
            elif d == "component" and first:
                v["components"].append(first)
            elif d == "livewire" and first:
                v["livewire"].append(first)
            elif d == "section" and first:
                v["sections"].append(first)
            elif d == "yield" and first:
                v["yields"].append(first)
            elif d == "stack" and first:
                v["stacks"].append(first)
            elif d in ("push", "prepend") and first:
                v["pushes"].append(first)
            elif d == "vite" and args:
                v["vite"] += re.findall(r"""['"]([^'"]+)['"]""", args[0])
            elif d == "inertia":
                v["inertia_root"] = True
            elif d == "props" and args:
                v["props"] += re.findall(r"""['"]([\w\-]+)['"]\s*(?:=>|,|\])""", args[0])
            _ = line
        for m in re.finditer(r"<x-([\w\-.:]+)", text):
            tag = m.group(1)
            if tag.startswith("slot") or tag == "dynamic-component":
                continue
            v["components"].append(tag)
        v["livewire"] += re.findall(r"<livewire:([\w\-.:]+)", text)
        for m in re.finditer(r"\{!!(.*?)!!\}", text, re.S):
            v["unescaped"].append({"line": text.count("\n", 0, m.start()) + 1, "expr": m.group(1).strip()[:80]})
        for m in re.finditer(r"\bwire:(\w+)(?:\.[\w.]+)?=\"([^\"]*)\"", text):
            v["wire"][m.group(1)] += 1
        v["wire"] = dict(v["wire"])
        v["wire_actions"] = sorted(set(re.findall(r"wire:(?:click|submit)(?:\.[\w.]+)?=\"(\w+)", text)))
        v["components"] = sorted(set(v["components"]))
        v["livewire"] = sorted(set(v["livewire"]))
        v["includes"] = sorted(set(v["includes"]))
        views[name] = v
    return views


def component_targets(proj, tag, views):
    """Map an <x-tag> to (view name or None, class fqn or None, external?)."""
    if "::" in tag:
        return None, None, True
    parts = tag.split(".")
    cls = "App\\View\\Components\\" + "\\".join("".join(w.capitalize() for w in re.split(r"[-_]", p)) for p in parts)
    vname = "components." + tag
    for cand in (vname, vname + ".index", vname + "." + parts[-1]):
        if cand in views:
            return cand, cls if proj.idx.get(cls) else None, False
    if proj.idx.get(cls):
        c = proj.idx.get(cls)
        rv = return_value(c.file, c.methods.get("render")) if "render" in c.methods else None
        if isinstance(rv, Node) and rv.type == "call" and rv.name == "view" and rv.args and isinstance(rv.args[0], str):
            return rv.args[0], cls, False
        return None, cls, False
    return None, None, False


def view_renders(proj):
    """Who renders which view / Inertia page: list of dicts."""
    out = []
    for c in proj.idx.by_fqn.values():
        if c.role in ("test",):
            continue
        for m in c.methods.values():
            sc = c.file.method_scan(c, m)
            for fn, s, ln in sc.calls:
                if fn in ("view",) and s:
                    out.append({"kind": "view", "name": s, "by": c.fqn, "method": m.name, "line": ln, "file": c.file.rel})
                if fn == "inertia" and s:
                    out.append({"kind": "inertia", "name": s, "by": c.fqn, "method": m.name, "line": ln, "file": c.file.rel})
            for cls, meth, s, ln in sc.statics:
                if short(cls) == "View" and meth in ("make", "first") and s:
                    out.append({"kind": "view", "name": s, "by": c.fqn, "method": m.name, "line": ln, "file": c.file.rel})
                if short(cls) == "Inertia" and meth == "render" and s:
                    out.append({"kind": "inertia", "name": s, "by": c.fqn, "method": m.name, "line": ln, "file": c.file.rel})
                if short(cls) in ("PDF", "Pdf") and meth == "loadView" and s:
                    out.append({"kind": "view", "name": s, "by": c.fqn, "method": m.name, "line": ln, "file": c.file.rel})
            for meth, s, ln, recv in sc.mcalls:
                if meth in ("view", "markdown", "loadView") and s and "." in s or (meth in ("view", "markdown") and s):
                    out.append({"kind": "view", "name": s, "by": c.fqn, "method": m.name, "line": ln, "file": c.file.rel})
        if c.role == "mail":
            for s in re.findall(r"(?:view|markdown)\s*:\s*['\"]([\w.\-:/]+)['\"]", c.file.text):
                out.append({"kind": "view", "name": s, "by": c.fqn, "method": "content", "line": c.line, "file": c.file.rel})
    seen, uniq = set(), []
    for r in out:
        k = (r["kind"], r["name"], r["by"], r["method"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def inertia_pages(proj):
    pages = {}
    for d in ("resources/js/Pages", "resources/js/pages", "resources/ts/Pages", "resources/js/Views"):
        for ap, rel in walk(proj.root, d, exts=(".vue", ".jsx", ".tsx", ".svelte", ".js", ".ts")):
            name = rel[len(d) + 1:]
            name = re.sub(r"\.(vue|jsx|tsx|svelte|js|ts)$", "", name)
            if any(seg.startswith("_") or seg in ("Partials", "partials", "Components", "components") for seg in name.split("/")[:-1]):
                kind = "partial"
            else:
                kind = "page"
            pages[name] = {"name": name, "file": rel, "kind": kind, "rendered_by": []}
    return pages


LW_LIFECYCLE = {"mount", "render", "boot", "booted", "hydrate", "dehydrate", "rendering", "rendered", "exception", "with", "layoutData",
                "placeholder", "__construct", "rules", "messages", "validationAttributes", "getListeners",
                "updating", "updated"}


def livewire_alias(fqn):
    for base in ("App\\Livewire\\", "App\\Http\\Livewire\\"):
        if fqn.startswith(base):
            return ".".join(kebab(p) for p in fqn[len(base):].split("\\"))
    return kebab(short(fqn))


def analyze_livewire(proj, views, routes):
    idx = proj.idx
    comps, forms = [], []
    for c in proj.classes_by_role("livewire"):
        anc = idx.ancestors(c)
        if any(a.endswith("Livewire\\Form") for a in anc):
            forms.append({"fqn": c.fqn, "name": c.name, "file": c.file.rel, "line": c.line,
                          "props": [p for p, d in c.props.items() if d["visibility"] == "public"]})
            continue
        if not any(a.startswith("Livewire\\") or a in idx.by_fqn for a in anc) and "\\Livewire\\" not in c.fqn:
            continue
        alias = livewire_alias(c.fqn)
        d = {"fqn": c.fqn, "name": c.name, "alias": alias, "file": c.file.rel, "line": c.line, "view": None,
             "props": [], "actions": [], "computed": [], "listens": [], "dispatches": [], "layout": None, "title": None,
             "traits": sorted(short(t) for t in idx.all_traits(c)), "routes": [], "used_in": [], "forms": [],
             "volt": False, "abstract": c.abstract}
        for a in c.attrs:
            sn = short(a["name"])
            if sn == "Layout" and a["args"] and isinstance(a["args"][0], str):
                d["layout"] = a["args"][0]
            if sn == "Title" and a["args"] and isinstance(a["args"][0], str):
                d["title"] = a["args"][0]
            if sn == "Lazy":
                d["lazy"] = True
        for pname, pd in c.props.items():
            if pd["visibility"] != "public" or pd["static"]:
                continue
            attrs = [short(a["name"]) for a in pd.get("attrs") or []]
            d["props"].append({"name": pname, "type": short(pd["type"]) if pd["type"] else "", "attrs": attrs,
                               "default": fmt_val(pd["value"]) if pd["has_default"] else ""})
            if pd["type"] and idx.get(pd["type"]) and proj.roles.get(pd["type"]) == "livewire":
                d["forms"].append(pd["type"])
        for m in c.methods.values():
            attrs = [short(a["name"]) for a in m.attrs]
            for a in m.attrs:
                if short(a["name"]) == "On" and a["args"]:
                    d["listens"].append({"event": str(a["args"][0]), "method": m.name})
            if "Computed" in attrs:
                d["computed"].append(m.name)
            elif m.visibility == "public" and not m.static and m.name not in LW_LIFECYCLE and \
                    not re.match(r"^(updating|updated|hydrate|dehydrate|mount|boot)[A-Z]", m.name) and not m.name.startswith("get") or \
                    (m.visibility == "public" and m.name.startswith("get") and not m.name.endswith("Property") and m.name not in LW_LIFECYCLE and False):
                d["actions"].append(m.name)
            sc = c.file.method_scan(c, m)
            for meth, s, ln, recv in sc.mcalls:
                if meth in ("dispatch", "dispatchTo", "dispatchSelf", "emit", "emitTo", "emitUp", "emitSelf",
                            "dispatchBrowserEvent") and s:
                    d["dispatches"].append({"event": s, "method": m.name, "how": meth})
                if m.name == "render" and meth in ("layout", "extends") and s:
                    d["layout"] = s
                if m.name == "render" and meth == "title" and s:
                    d["title"] = s
            if m.name == "render":
                for fn, s, ln in sc.calls:
                    if fn == "view" and s:
                        d["view"] = s
                for cls, meth, s, ln in sc.statics:
                    if short(cls) == "View" and meth == "make" and s:
                        d["view"] = s
        lst = prop_value(proj, c, "listeners")
        if isinstance(lst, dict):
            for ev, meth in lst.items():
                d["listens"].append({"event": str(ev), "method": meth if isinstance(meth, str) else "?"})
        elif isinstance(lst, list):
            for ev in strs(lst):
                d["listens"].append({"event": ev, "method": ev})
        if not d["view"]:
            conv = "livewire." + alias
            d["view"] = conv if conv in views else None
            d["view_conventional"] = True
        comps.append(d)
    # Volt (single-file) components
    mounts = ["resources/views/livewire", "resources/views/pages"]
    vsp = proj.php.get("app/Providers/VoltServiceProvider.php")
    if vsp is not None:
        found = re.findall(r"resource_path\(\s*['\"]([^'\"]+)['\"]", vsp.text)
        if found:
            mounts = ["resources/" + f.strip("/") for f in found]
    for vname, v in views.items():
        if not v["is_volt"]:
            continue
        rel = v["file"]
        names = {vname}
        for mnt in mounts:
            if rel.startswith(mnt + "/"):
                names.add(re.sub(r"\.blade\.php$", "", rel[len(mnt) + 1:]).replace("/", "."))
        text = read_text(proj.p(rel))
        d = {"fqn": None, "name": vname, "alias": sorted(names, key=len)[0], "aliases": sorted(names), "file": rel, "line": 1,
             "view": vname, "props": [], "actions": [], "computed": [], "listens": [], "dispatches": [], "layout": None,
             "title": None, "traits": [], "routes": [], "used_in": [], "forms": [], "volt": True,
             "volt_style": "class" if re.search(r"new\s+(?:#\[[^\]]*\]\s*)*class\b", text) else "functional"}
        m = re.search(r"<\?php(.*?)\?>", text, re.S)
        php = m.group(1) if m else ""
        if d["volt_style"] == "class" and php:
            vf = PhpFile(proj.p(rel), rel, "<?php " + php, proj.root)
            for c in vf.classes:
                for pname, pd in c.props.items():
                    if pd["visibility"] == "public" and not pd["static"]:
                        d["props"].append({"name": pname, "type": short(pd["type"]) if pd["type"] else "",
                                           "attrs": [short(a["name"]) for a in pd.get("attrs") or []],
                                           "default": fmt_val(pd["value"]) if pd["has_default"] else ""})
                for mm in c.methods.values():
                    if mm.visibility == "public" and mm.name not in LW_LIFECYCLE and not mm.static:
                        if any(short(a["name"]) == "Computed" for a in mm.attrs):
                            d["computed"].append(mm.name)
                        else:
                            d["actions"].append(mm.name)
                    for a in mm.attrs:
                        if short(a["name"]) == "On" and a["args"]:
                            d["listens"].append({"event": str(a["args"][0]), "method": mm.name})
                    sc = vf.method_scan(c, mm)
                    for meth, s, ln, recv in sc.mcalls:
                        if meth in ("dispatch", "dispatchTo", "dispatchSelf") and s:
                            d["dispatches"].append({"event": s, "method": mm.name, "how": meth})
                for a in c.attrs:
                    if short(a["name"]) == "Layout" and a["args"] and isinstance(a["args"][0], str):
                        d["layout"] = a["args"][0]
                    if short(a["name"]) == "Title" and a["args"] and isinstance(a["args"][0], str):
                        d["title"] = a["args"][0]
        elif php:
            sm = re.search(r"\bstate\(\s*\[(.*?)\]\s*\)", php, re.S)
            if sm:
                d["props"] = [{"name": k, "type": "", "attrs": [], "default": ""} for k in re.findall(r"['\"](\w+)['\"]\s*=>", sm.group(1))]
            sm2 = re.findall(r"\bstate\(\s*(?:['\"](\w+)['\"]|(\w+)\s*:)", php)
            d["props"] += [{"name": a or b, "type": "", "attrs": [], "default": ""} for a, b in sm2]
            d["actions"] = re.findall(r"\$(\w+)\s*=\s*(?:function|fn)\b", php)
            d["computed"] = re.findall(r"\$(\w+)\s*=\s*computed\(", php)
            for ev, fn in re.findall(r"on\(\s*\[\s*['\"]([\w\-.:]+)['\"]\s*=>\s*(?:function|fn)?\s*\(?\$?(\w*)", php):
                d["listens"].append({"event": ev, "method": fn or "closure"})
            layout = re.search(r"\blayout\(\s*['\"]([^'\"]+)", php)
            d["layout"] = layout.group(1) if layout else None
            d["dispatches"] += [{"event": e, "method": "?", "how": "dispatch"} for e in re.findall(r"->dispatch\(\s*['\"]([\w\-.:]+)", php)]
        comps.append(d)
    # where are they used / routed
    by_alias = {}
    for d in comps:
        for a in d.get("aliases") or [d["alias"]]:
            by_alias[a] = d
    for v in views.values():
        for tag in v["livewire"]:
            if tag in by_alias:
                by_alias[tag]["used_in"].append(v["name"])
    for r in routes:
        if r.get("action_type") == "livewire":
            for d in comps:
                if d["fqn"] == r.get("controller"):
                    d["routes"].append(f"{'|'.join(r['methods'][:1])} {r['uri']}")
        if r.get("action_type") == "volt" and r.get("volt") in by_alias:
            by_alias[r["volt"]]["routes"].append(f"GET {r['uri']}")
    # event graph
    listeners = defaultdict(list)
    for d in comps:
        for l in d["listens"]:
            listeners[l["event"]].append(d["alias"])
    edges = []
    for d in comps:
        for ds in d["dispatches"]:
            for target in listeners.get(ds["event"], []) or [None]:
                edges.append({"from": d["alias"], "event": ds["event"], "to": target})
    return {"components": comps, "forms": forms, "edges": edges, "mounts": mounts,
            "version": proj.locked_versions().get("livewire/livewire", {}).get("version") or proj.require().get("livewire/livewire")}


FILAMENT_LAYOUT = {"Section", "Grid", "Fieldset", "Tabs", "Tab", "Wizard", "Step", "Split", "Group", "Card",
                   "Actions", "Placeholder", "View", "Livewire"}


def analyze_filament(proj, models):
    idx = proj.idx
    out = {"panels": [], "resources": [], "pages": [], "widgets": [], "relation_managers": [], "routes": [],
           "clusters": [], "version": proj.locked_versions().get("filament/filament", {}).get("version") or proj.require().get("filament/filament")}
    if not proj.has_pkg("filament/filament") and not any(c.role == "filament" for c in idx.by_fqn.values()):
        return out
    for c in proj.classes_by_role("filament"):
        anc = idx.ancestors(c)
        anc_s = " ".join(anc)
        if "Filament\\PanelProvider" in anc:
            m = c.methods.get("panel")
            p = {"fqn": c.fqn, "file": c.file.rel, "id": None, "path": None, "default": False, "features": [],
                 "discover": {}, "resources": [], "pages": [], "widgets": [], "middleware": [], "auth_middleware": [],
                 "plugins": [], "colors": {}, "brand": None, "tenant": None, "domain": None}
            if m and m.body:
                for calls in find_var_chains(c.file, m.body[0], m.body[1], {"$panel"}):
                    for call in calls:
                        a = call.args
                        n = call.name
                        if n == "id" and a and isinstance(a[0], str):
                            p["id"] = a[0]
                        elif n == "path" and a and isinstance(a[0], str):
                            p["path"] = a[0]
                        elif n == "default":
                            p["default"] = True
                        elif n in ("login", "registration", "passwordReset", "emailVerification", "profile", "spa",
                                   "topNavigation", "databaseNotifications", "sidebarCollapsibleOnDesktop", "darkMode",
                                   "unsavedChangesAlerts", "globalSearch", "multiFactorAuthentication"):
                            p["features"].append(n)
                        elif n.startswith("discover") and (call.kw or a):
                            p["discover"][n[8:].lower()] = {"in": proj.rel(call.kw.get("in")) if isinstance(call.kw.get("in"), str) else None,
                                                            "for": call.kw.get("for") if isinstance(call.kw.get("for"), str) else (a[1] if len(a) > 1 and isinstance(a[1], str) else None)}
                        elif n in ("resources", "pages", "widgets") and a:
                            p[n] += class_strs(a[0])
                        elif n == "middleware" and a:
                            p["middleware"] += [short(x) for x in class_strs(a[0])]
                        elif n == "authMiddleware" and a:
                            p["auth_middleware"] += [short(x) for x in class_strs(a[0])]
                        elif n in ("plugins", "plugin") and a:
                            vals = a[0] if isinstance(a[0], list) else a
                            for x in vals:
                                if isinstance(x, Node) and x.type in ("static", "new", "chain"):
                                    base = x.base if x.type == "chain" else x
                                    p["plugins"].append(short(base.cls) if getattr(base, "cls", None) else repr(x))
                        elif n == "colors" and a and isinstance(a[0], dict):
                            p["colors"] = {k: fmt_val(v) for k, v in a[0].items()}
                        elif n == "brandName" and a and isinstance(a[0], str):
                            p["brand"] = a[0]
                        elif n == "tenant" and a:
                            p["tenant"] = short(str(a[0]))
                        elif n == "domain" and a and isinstance(a[0], str):
                            p["domain"] = a[0]
            p["id"] = p["id"] or kebab(c.name.replace("PanelProvider", "")) or "admin"
            p["path"] = p["path"] if p["path"] is not None else p["id"]
            out["panels"].append(p)
        elif "Filament\\Resources\\Resource" in anc:
            model = prop_value(proj, c, "model")
            r = {"fqn": c.fqn, "name": c.name, "file": c.file.rel, "line": c.line, "model": str(model) if isinstance(model, str) else None,
                 "slug": None, "icon": prop_value(proj, c, "navigationIcon"), "group": prop_value(proj, c, "navigationGroup"),
                 "label": prop_value(proj, c, "navigationLabel") or prop_value(proj, c, "label"),
                 "title_attribute": prop_value(proj, c, "recordTitleAttribute"), "fields": [], "columns": [], "filters": [],
                 "actions": [], "relations": [], "pages": [], "panel": None, "cluster": None}
            slug = prop_value(proj, c, "slug")
            if isinstance(slug, str):
                r["slug"] = slug
            else:
                tail = c.fqn.split("\\Resources\\", 1)[1] if "\\Resources\\" in c.fqn else c.name
                tail = re.sub(r"Resource$", "", tail)
                parts = tail.split("\\")
                parts[-1] = plural_studly(parts[-1])
                r["slug"] = "/".join(kebab(x) for x in parts)
            cl = prop_value(proj, c, "cluster")
            r["cluster"] = short(cl) if isinstance(cl, str) else None
            for meth, bucket_fn in (("form", "fields"), ("table", "columns"), ("infolist", "fields")):
                m = c.methods.get(meth)
                if not (m and m.body):
                    continue
                sc = c.file.method_scan(c, m)
                for cls, mn, s, ln in sc.statics:
                    if mn != "make":
                        continue
                    if "\\Forms\\Components\\" in cls or "\\Infolists\\Components\\" in cls or "\\Schemas\\Components\\" in cls:
                        r["fields"].append({"type": short(cls), "name": s, "layout": short(cls) in FILAMENT_LAYOUT})
                    elif "\\Tables\\Columns\\" in cls:
                        r["columns"].append({"type": short(cls), "name": s})
                    elif "\\Tables\\Filters\\" in cls:
                        r["filters"].append({"type": short(cls), "name": s})
                    elif "\\Actions\\" in cls:
                        r["actions"].append(short(cls))
            rv = return_value(c.file, c.methods.get("getRelations"))
            r["relations"] = class_strs(rv) if rv else []
            pv = return_value(c.file, c.methods.get("getPages"))
            if isinstance(pv, dict):
                for key, node in pv.items():
                    if isinstance(node, Node) and node.type == "static":
                        path = node.args[0] if node.args and isinstance(node.args[0], str) else "/"
                        r["pages"].append({"key": str(key), "class": node.cls, "path": path})
            r["actions"] = sorted(set(r["actions"]))
            out["resources"].append(r)
        elif "Filament\\Resources\\RelationManagers\\RelationManager" in anc:
            out["relation_managers"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel,
                                             "relationship": prop_value(proj, c, "relationship")})
        elif "Filament\\Resources\\Pages\\" in anc_s:
            continue
        elif any(a.startswith("Filament\\Pages\\") for a in anc) or "Filament\\Pages\\Page" in anc:
            slug = prop_value(proj, c, "slug")
            out["pages"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel,
                                 "slug": slug if isinstance(slug, str) else kebab(c.name),
                                 "view": prop_value(proj, c, "view"), "icon": prop_value(proj, c, "navigationIcon"),
                                 "group": prop_value(proj, c, "navigationGroup"), "panel": None,
                                 "dashboard": any(a.endswith("Pages\\Dashboard") for a in anc) or c.name == "Dashboard"})
        elif any(a.startswith("Filament\\Widgets\\") for a in anc):
            base = next((short(a) for a in anc if a.startswith("Filament\\Widgets\\")), "Widget")
            out["widgets"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel, "type": base, "panel": None})
        elif any(a.startswith("Filament\\Clusters\\") for a in anc):
            out["clusters"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel})
    if not out["panels"] and (out["resources"] or out["pages"]):
        out["panels"].append({"fqn": None, "file": None, "id": "admin", "path": "admin", "default": True, "features": ["login"],
                              "discover": {"resources": {"in": "app/Filament/Resources", "for": "App\\Filament\\Resources"},
                                           "pages": {"in": "app/Filament/Pages", "for": "App\\Filament\\Pages"},
                                           "widgets": {"in": "app/Filament/Widgets", "for": "App\\Filament\\Widgets"}},
                              "resources": [], "pages": [], "widgets": [], "middleware": [], "auth_middleware": [],
                              "plugins": [], "colors": {}, "brand": None, "tenant": None, "domain": None, "assumed": True})

    def panel_for(fqn, kind):
        best = None
        for p in out["panels"]:
            if fqn in p.get(kind, []):
                return p
            disc = (p["discover"].get(kind) or {}).get("for")
            if disc and fqn.startswith(disc.strip("\\") + "\\"):
                if best is None or len(disc) > len((best["discover"].get(kind) or {}).get("for") or ""):
                    best = p
        return best

    for r in out["resources"]:
        p = panel_for(r["fqn"], "resources")
        r["panel"] = p["id"] if p else None
        base = join_uri(p["path"] if p else "admin", r["slug"])
        for pg in r["pages"]:
            uri = join_uri(base, pg["path"])
            name = f"filament.{r['panel'] or 'admin'}.resources.{r['slug'].replace('/', '.')}.{pg['key']}"
            out["routes"].append({"methods": ["GET", "HEAD"], "uri": uri, "name": name, "action": pg["class"],
                                  "action_type": "filament", "controller": pg["class"], "method": None,
                                  "middleware": (p["middleware"] + p["auth_middleware"]) if p else [], "file": r["file"],
                                  "line": r["line"], "group": f"filament:{r['panel'] or 'admin'}", "source": "filament"})
            pg["uri"] = uri
    for pg in out["pages"]:
        p = panel_for(pg["fqn"], "pages")
        pg["panel"] = p["id"] if p else None
        uri = join_uri(p["path"] if p else "admin", "" if pg["dashboard"] else pg["slug"])
        pg["uri"] = uri
        out["routes"].append({"methods": ["GET", "HEAD"], "uri": uri, "name": f"filament.{pg['panel'] or 'admin'}.pages.{pg['slug']}",
                              "action": pg["fqn"], "action_type": "filament", "controller": pg["fqn"], "method": None,
                              "middleware": (p["middleware"] + p["auth_middleware"]) if p else [], "file": pg["file"],
                              "line": 1, "group": f"filament:{pg['panel'] or 'admin'}", "source": "filament"})
    for w in out["widgets"]:
        p = panel_for(w["fqn"], "widgets")
        w["panel"] = p["id"] if p else None
    for p in out["panels"]:
        has_dash = any(pg["dashboard"] and pg["panel"] == p["id"] for pg in out["pages"])
        if not has_dash:
            out["routes"].append({"methods": ["GET", "HEAD"], "uri": join_uri(p["path"], ""), "name": f"filament.{p['id']}.pages.dashboard",
                                  "action": "Filament\\Pages\\Dashboard", "action_type": "filament", "controller": None,
                                  "method": None, "middleware": p["middleware"] + p["auth_middleware"], "file": p["file"],
                                  "line": 1, "group": f"filament:{p['id']}", "source": "filament"})
        for feat, path in (("login", "login"), ("registration", "register"), ("passwordReset", "password-reset/request"),
                           ("profile", "profile"), ("emailVerification", "email-verification/prompt")):
            if feat in p["features"]:
                out["routes"].append({"methods": ["GET", "HEAD"], "uri": join_uri(p["path"], path),
                                      "name": f"filament.{p['id']}.auth.{path.split('/')[0].replace('-', '.')}",
                                      "action": f"Filament {feat}", "action_type": "filament", "controller": None,
                                      "method": None, "middleware": p["middleware"], "file": p["file"], "line": 1,
                                      "group": f"filament:{p['id']}", "source": "filament"})
    return out


def analyze_assets(proj):
    out = {"bundler": None, "entries": [], "plugins": [], "css": None, "js_components": Counter(), "spa": None,
           "config_file": None}
    for f in ("vite.config.js", "vite.config.ts", "vite.config.mjs", "vite.config.mts"):
        if proj.exists(f):
            t = read_text(proj.p(f))
            out["bundler"], out["config_file"] = "Vite", f
            m = re.search(r"input\s*:\s*(\[[^\]]*\]|['\"][^'\"]+['\"])", t, re.S)
            if m:
                out["entries"] = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
            out["plugins"] = sorted(set(re.findall(r"\b(laravel|vue|react|svelte|tailwindcss|livewire|inertia|i18n|vuetify|eslint|legacy)\s*\(", t)))
            break
    if not out["bundler"] and proj.exists("webpack.mix.js"):
        t = read_text(proj.p("webpack.mix.js"))
        out["bundler"], out["config_file"] = "Laravel Mix (webpack)", "webpack.mix.js"
        out["entries"] = re.findall(r"\.(?:js|ts|sass|scss|less|postCss|css|react|vue)\(\s*['\"]([^'\"]+)['\"]", t)
        out["plugins"] = sorted(set(re.findall(r"\.(vue|react|sass|postCss|less|version|sourceMaps)\(", t)))
    for f in ("tailwind.config.js", "tailwind.config.ts", "tailwind.config.cjs"):
        if proj.exists(f):
            out["css"] = "Tailwind CSS"
    if not out["css"] and proj.has_npm("tailwindcss"):
        out["css"] = "Tailwind CSS"
    if not out["css"] and proj.has_npm("bootstrap"):
        out["css"] = "Bootstrap"
    for ap, rel in walk(proj.root, "resources", exts=(".vue", ".jsx", ".tsx", ".svelte", ".ts", ".js")):
        if "/views/" in rel:
            continue
        out["js_components"][os.path.splitext(rel)[1][1:]] += 1
    out["js_components"] = dict(out["js_components"])
    if proj.has_pkg("inertiajs/inertia-laravel") or proj.has_npm("@inertiajs/vue3") or proj.has_npm("@inertiajs/react"):
        fw = "Vue" if proj.has_npm("vue") else "React" if proj.has_npm("react") else "Svelte" if proj.has_npm("svelte") else "JS"
        out["spa"] = f"Inertia + {fw}"
    return out


# =====================================================================================================
# 13. Docker dev environment
# =====================================================================================================

COMPOSE_BASE = ["compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"]
COMPOSE_OVERRIDE = ["compose.override.yaml", "compose.override.yml", "docker-compose.override.yaml", "docker-compose.override.yml"]
SERVICE_ROLES = {
    "app": ("Application", "Runs the Laravel PHP code (php-fpm, the built-in server or Octane)."),
    "web": ("Web server", "Receives HTTP requests and hands PHP requests to the app container."),
    "proxy": ("Reverse proxy", "Routes traffic to other containers (TLS, hostnames)."),
    "database": ("Database", "Stores the application's data."),
    "cache": ("Cache / Redis", "Cache, sessions, queues and locks."),
    "queue": ("Queue worker", "Runs queued jobs and listeners in the background."),
    "scheduler": ("Scheduler", "Runs the Laravel task scheduler every minute."),
    "websockets": ("WebSockets", "Real-time broadcasting server (Reverb, Soketi, …)."),
    "mail": ("Mail catcher", "Catches outgoing email so you can read it in a browser instead of sending it."),
    "search": ("Search engine", "Full-text search (Laravel Scout driver)."),
    "storage": ("Object storage", "S3-compatible file storage for local development."),
    "assets": ("Frontend build", "Runs Node: Vite / Mix dev server or asset builds."),
    "db-ui": ("Database UI", "Browser UI for inspecting the database or cache."),
    "browser": ("Browser testing", "Headless browser for Dusk / end-to-end tests."),
    "broker": ("Message broker", "Message queue / event streaming."),
    "other": ("Other", "Supporting service."),
}
WEB_PORTS = {80: "app", 443: "app (https)", 8000: "app", 8080: "web UI", 8025: "Mailpit/MailHog UI", 7700: "Meilisearch",
             5173: "Vite dev server", 3000: "Node dev server", 9001: "MinIO console", 8081: "web UI", 8888: "web UI",
             15672: "RabbitMQ UI", 1080: "MailDev UI", 8108: "Typesense", 9200: "Elasticsearch", 8001: "web UI"}
DB_PORTS = {3306: "MySQL/MariaDB", 5432: "PostgreSQL", 6379: "Redis", 1025: "SMTP", 27017: "MongoDB", 1433: "SQL Server",
            11211: "Memcached", 9000: "php-fpm / MinIO", 4444: "Selenium", 5672: "AMQP"}


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _cmd_str(v):
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v) if v is not None else ""


def service_role(name, svc, image, cmd, build_text=""):
    t = f"{name} {image}".lower()
    c = cmd.lower()
    if "horizon" in c or "queue:work" in c or "queue:listen" in c:
        return "queue"
    if "schedule:work" in c or "schedule:run" in c or re.search(r"\bcron\b", c):
        return "scheduler"
    if "reverb:start" in c or "websockets:serve" in c or "soketi" in t:
        return "websockets"
    if re.search(r"(mysql|mariadb|postgres|postgis|pgsql|mssql|sqlserver|mongo|percona|timescale|cockroach)", t) and "admin" not in t:
        return "database"
    if re.search(r"(redis|valkey|keydb|memcached|dragonfly)", t) and not re.search(r"(commander|insight|ui)", t):
        return "cache"
    if re.search(r"(mailpit|mailhog|maildev|mailcatcher|papercut|smtp4dev)", t):
        return "mail"
    if re.search(r"(meilisearch|typesense|elasticsearch|opensearch|solr|manticore)", t):
        return "search"
    if re.search(r"(minio|localstack|s3mock|fake-gcs)", t):
        return "storage"
    if re.search(r"(selenium|chrome|playwright|chromium)", t):
        return "browser"
    if re.search(r"(phpmyadmin|adminer|pgadmin|redis-commander|redisinsight|dbgate)", t):
        return "db-ui"
    if re.search(r"(rabbitmq|kafka|nats|activemq|zookeeper)", t):
        return "broker"
    if re.search(r"\btraefik|haproxy|nginx-proxy|caddy-docker-proxy", t):
        return "proxy"
    if re.search(r"(nginx|caddy|httpd|apache|openresty|frankenphp-web)", t) and "php" not in t:
        return "web"
    if re.search(r"(^|\W)(node|vite|npm|yarn|pnpm|bun)(\W|$)", t) or re.search(r"\b(npm|yarn|pnpm|bun) (run|dev|install)|\bvite\b", c):
        return "assets"
    if re.search(r"(php|laravel|sail|app|frankenphp|octane|fpm|workspace)", t) or "artisan" in c or svc.get("build") or "php" in build_text.lower():
        return "app"
    return "other"


def parse_ports(svc, env):
    out = []
    for p in _as_list(svc.get("ports")):
        if isinstance(p, dict):
            host = p.get("published")
            out.append({"raw": json.dumps(p), "host": str(host) if host else None, "container": str(p.get("target")),
                        "proto": p.get("protocol", "tcp"), "ip": p.get("host_ip"), "vars": []})
            continue
        raw = str(p)
        res, used = interpolate(raw, env)
        proto = "tcp"
        if "/" in res:
            res, proto = res.rsplit("/", 1)
        parts = res.split(":")
        ip = None
        if len(parts) == 3:
            ip, host, cont = parts
        elif len(parts) == 2:
            host, cont = parts
        else:
            host, cont = None, parts[0]
        out.append({"raw": raw, "host": host or None, "container": cont, "proto": proto, "ip": ip, "vars": used})
    return out


def parse_dockerfile(path):
    text = read_text(path)
    if not text:
        return None
    joined = re.sub(r"\\\r?\n", " ", text)
    lines = [ln.strip() for ln in joined.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    d = {"stages": [], "apt": [], "apk": [], "php_ext": [], "pecl": [], "expose": [], "workdir": None, "user": None,
         "cmd": None, "entrypoint": None, "env": [], "args": [], "copies_from": [], "php_version": None,
         "xdebug": "xdebug" in text.lower(), "composer": "composer" in text.lower(), "node": bool(re.search(r"\b(node|npm|nodesource|nvm)\b", text, re.I)),
         "lines": text.count("\n") + 1}
    for ln in lines:
        m = re.match(r"(\w+)\s+(.*)", ln)
        if not m:
            continue
        ins, rest = m.group(1).upper(), m.group(2)
        if ins == "FROM":
            fm = re.match(r"(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", rest, re.I)
            if fm:
                d["stages"].append({"image": fm.group(1), "as": fm.group(2)})
                pv = re.search(r"php:?(\d\.\d)", fm.group(1)) or re.search(r"(\d\.\d)[-\w]*fpm", fm.group(1))
                if pv:
                    d["php_version"] = pv.group(1)
        elif ins == "RUN":
            for seg in re.split(r"&&|;|\|\|", rest):
                seg = seg.strip()
                am = re.search(r"apt-get\s+(?:-\S+\s+)*install\s+(.*)", seg)
                if am:
                    d["apt"] += [x for x in am.group(1).split() if not x.startswith("-") and "=" not in x]
                am = re.search(r"apk\s+(?:-\S+\s+)*add\s+(.*)", seg)
                if am:
                    d["apk"] += [x for x in am.group(1).split() if not x.startswith("-")]
                am = re.search(r"docker-php-ext-install\s+(.*)", seg)
                if am:
                    d["php_ext"] += [x for x in am.group(1).split() if not x.startswith("-")]
                am = re.search(r"install-php-extensions\s+(.*)", seg)
                if am:
                    d["php_ext"] += [x for x in am.group(1).split() if not x.startswith("-")]
                am = re.search(r"pecl\s+install\s+(.*)", seg)
                if am:
                    d["pecl"] += [x for x in am.group(1).split() if not x.startswith("-")]
        elif ins == "EXPOSE":
            d["expose"] += rest.split()
        elif ins == "WORKDIR":
            d["workdir"] = rest
        elif ins == "USER":
            d["user"] = rest
        elif ins == "CMD":
            d["cmd"] = rest
        elif ins == "ENTRYPOINT":
            d["entrypoint"] = rest
        elif ins == "ENV":
            d["env"] += re.findall(r"([A-Za-z_][A-Za-z0-9_]*)[= ]", rest)[:20]
        elif ins == "ARG":
            d["args"].append(rest.split("=")[0])
        elif ins == "COPY":
            cm = re.search(r"--from=(\S+)", rest)
            if cm:
                d["copies_from"].append(cm.group(1))
    if not d["php_version"]:
        pv = re.search(r"php(\d\.\d)-(?:cli|fpm|common|mysql)", text)
        if pv:
            d["php_version"] = pv.group(1)
    d["apt"] = sorted(set(d["apt"]))
    d["php_ext"] = sorted(set(d["php_ext"] + d["pecl"] + [x.split("-", 1)[1] for x in d["apt"] if re.match(r"php\d\.\d-", x)]))
    return d


def _merge_compose(base, over):
    out = json.loads(json.dumps(base or {}, default=str))
    for k, v in (over or {}).items():
        if k == "services" and isinstance(v, dict):
            svcs = out.setdefault("services", {}) or {}
            for sn, sv in v.items():
                if sn in svcs and isinstance(svcs[sn], dict) and isinstance(sv, dict):
                    for kk, vv in sv.items():
                        if kk in ("ports", "expose", "volumes") and isinstance(svcs[sn].get(kk), list) and isinstance(vv, list):
                            svcs[sn][kk] = svcs[sn][kk] + [x for x in vv if x not in svcs[sn][kk]]
                        elif kk == "environment" and isinstance(svcs[sn].get(kk), dict) and isinstance(vv, dict):
                            svcs[sn][kk] = {**svcs[sn][kk], **vv}
                        else:
                            svcs[sn][kk] = vv
                else:
                    svcs[sn] = sv
            out["services"] = svcs
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def analyze_docker(proj):
    env = {**proj.env_example, **proj.env}
    d = {"files": [], "services": [], "edges": [], "dockerfiles": {}, "config_files": [], "sail": False,
         "compose_cmd": "docker compose", "app_service": None, "node_service": None, "networks": [], "volumes": [],
         "supervisor": [], "php_ini": {}, "env_used": [], "devcontainer": proj.exists(".devcontainer")}
    base = next((f for f in COMPOSE_BASE if proj.exists(f)), None)
    if base is None:
        for f in ("docker/docker-compose.yml", "docker/compose.yml", ".docker/docker-compose.yml", "docker/docker-compose.yaml"):
            if proj.exists(f):
                base = f
                d["compose_cmd"] = f"docker compose -f {f}"
                break
    overrides = [f for f in COMPOSE_OVERRIDE if proj.exists(f)]
    extra = sorted({rel for ap, rel in walk(proj.root, "", exts=(".yml", ".yaml"), max_depth=1)
                    if re.match(r"(docker-)?compose[.\-][\w.\-]+\.ya?ml$", os.path.basename(rel)) and rel != base and rel not in overrides})
    parsed = {}
    for f in [base] + overrides + extra:
        if not f:
            continue
        data = yaml_load(read_text(proj.p(f)))
        if not isinstance(data, dict):
            proj.notes.append(f"Could not read {f} as YAML.")
            continue
        parsed[f] = data
        d["files"].append({"file": f, "kind": "base" if f == base else "override" if f in overrides else "extra",
                           "services": sorted((data.get("services") or {}).keys()), "version": data.get("version")})
    merged = {}
    if base in parsed:
        merged = parsed[base]
        for f in overrides:
            if f in parsed:
                merged = _merge_compose(merged, parsed[f])
    service_origin = {}
    for f, data in parsed.items():
        for sn in (data.get("services") or {}):
            service_origin.setdefault(sn, []).append(f)
    services = dict(merged.get("services") or {})
    for f in extra:
        for sn, sv in ((parsed.get(f) or {}).get("services") or {}).items():
            if sn not in services:
                services[sn] = {**(sv or {}), "_only_in": f}
    names = set(services)
    for sn, sv in services.items():
        sv = sv or {}
        image = str(sv.get("image") or "")
        build = sv.get("build")
        bctx, bdf, btarget = None, None, None
        if isinstance(build, str):
            bctx = build
        elif isinstance(build, dict):
            bctx, bdf, btarget = build.get("context", "."), build.get("dockerfile"), build.get("target")
        build_text = ""
        df_rel = None
        if bctx is not None:
            ctx_res, _ = interpolate(str(bctx), env)
            df_path = os.path.normpath(os.path.join(proj.root, ctx_res, bdf or "Dockerfile"))
            if os.path.isfile(df_path):
                df_rel = proj.rel(df_path)
                if df_rel not in d["dockerfiles"]:
                    d["dockerfiles"][df_rel] = parse_dockerfile(df_path)
                build_text = read_text(df_path)
        cmd = _cmd_str(sv.get("command"))
        role = service_role(sn, sv, image, cmd, build_text)
        envs = sv.get("environment")
        envd = {}
        if isinstance(envs, dict):
            envd = {str(k): ("" if v is None else str(v)) for k, v in envs.items()}
        elif isinstance(envs, list):
            for e in envs:
                k, _, v = str(e).partition("=")
                envd[k] = v
        vols = []
        for v in _as_list(sv.get("volumes")):
            if isinstance(v, dict):
                vols.append({"src": str(v.get("source", "")), "dst": str(v.get("target", "")), "type": v.get("type", "volume")})
                continue
            parts = str(v).split(":")
            src = parts[0] if len(parts) > 1 else ""
            dst = parts[1] if len(parts) > 1 else parts[0]
            kind = "bind" if src.startswith((".", "/", "~", "$")) else ("named" if src else "anonymous")
            vols.append({"src": src, "dst": dst, "type": kind, "mode": parts[2] if len(parts) > 2 else ""})
        deps = sv.get("depends_on")
        dep_list = list(deps.keys()) if isinstance(deps, dict) else [str(x) for x in _as_list(deps)]
        hc = sv.get("healthcheck")
        s = {"name": sn, "role": role, "role_label": SERVICE_ROLES[role][0], "image": image or None,
             "build": {"context": bctx, "dockerfile": bdf, "target": btarget, "file": df_rel} if bctx is not None else None,
             "command": cmd or None, "entrypoint": _cmd_str(sv.get("entrypoint")) or None,
             "ports": parse_ports(sv, env), "expose": [str(x) for x in _as_list(sv.get("expose"))],
             "environment": {k: mask(k, v) for k, v in envd.items()},
             "env_file": [str(x) for x in _as_list(sv.get("env_file"))], "volumes": vols, "depends_on": dep_list,
             "networks": list(sv["networks"].keys()) if isinstance(sv.get("networks"), dict) else [str(x) for x in _as_list(sv.get("networks"))],
             "healthcheck": bool(hc) and not (isinstance(hc, dict) and hc.get("disable")),
             "restart": sv.get("restart"), "profiles": [str(x) for x in _as_list(sv.get("profiles"))],
             "working_dir": sv.get("working_dir"), "container_name": sv.get("container_name"),
             "files": service_origin.get(sn, []), "only_in": sv.get("_only_in"),
             "php_version": (d["dockerfiles"].get(df_rel) or {}).get("php_version") if df_rel else None}
        if not s["php_version"]:
            pv = re.search(r"(?:php|sail)[-:]?(\d\.\d)", image)
            s["php_version"] = pv.group(1) if pv else None
        tag = image.split(":")[-1] if ":" in image.split("/")[-1] else ("latest" if image else None)
        s["tag"] = tag
        d["services"].append(s)
        for dep in dep_list:
            d["edges"].append({"from": sn, "to": dep, "kind": "depends_on", "label": "depends on"})
        if sn == "laravel.test" or "sail" in image or (bctx and "vendor/laravel/sail" in str(bctx)):
            d["sail"] = True
    if proj.has_pkg("laravel/sail") and any(s["name"] == "laravel.test" for s in d["services"]):
        d["sail"] = True
    apps = [s for s in d["services"] if s["role"] == "app" and not s["only_in"]]
    if apps:
        pref = sorted(apps, key=lambda s: (s["name"] not in ("laravel.test", "app", "php", "laravel", "php-fpm", "web"),
                                          not any(v["dst"].rstrip("/") in ("/var/www/html", "/var/www", "/app", "/srv/app") for v in s["volumes"]),
                                          s["name"]))
        d["app_service"] = pref[0]["name"]
    nodes = [s for s in d["services"] if s["role"] == "assets"]
    d["node_service"] = nodes[0]["name"] if nodes else None
    # web server -> app via nginx/caddy config
    conf_files = []
    for sub in ("docker", ".docker", "nginx", "caddy", "deploy", "infra", ".devcontainer", "build"):
        for ap, rel in walk(proj.root, sub, max_depth=4):
            conf_files.append((ap, rel))
    for f in ("Caddyfile", "nginx.conf", "supervisord.conf", "Dockerfile", ".dockerignore"):
        if proj.exists(f):
            conf_files.append((proj.p(f), f))
    for ap, rel in conf_files:
        base_name = os.path.basename(rel).lower()
        kind = ("nginx config" if base_name.endswith(".conf") and "nginx" in rel.lower() else
                "Caddyfile" if "caddyfile" in base_name else
                "supervisor config" if "supervisor" in base_name else
                "PHP ini" if base_name.endswith(".ini") else
                "Dockerfile" if base_name.startswith("dockerfile") or base_name.endswith(".dockerfile") else
                "shell script" if base_name.endswith(".sh") or "entrypoint" in base_name or base_name.startswith("start-") else
                "config")
        d["config_files"].append({"file": rel, "kind": kind})
        if os.path.getsize(ap) > 300_000:
            continue
        text = read_text(ap)
        if kind == "Dockerfile" and rel not in d["dockerfiles"]:
            d["dockerfiles"][rel] = parse_dockerfile(ap)
        for m in re.finditer(r"(?:fastcgi_pass|php_fastcgi|reverse_proxy|proxy_pass)\s+(?:https?://)?([\w.\-]+):(\d+)", text):
            target = m.group(1)
            if target in names:
                src = next((s["name"] for s in d["services"] if s["role"] in ("web", "proxy") and
                            any(rel.startswith(v["src"].lstrip("./").rstrip("/")) or os.path.basename(v["src"]) == os.path.basename(rel)
                                for v in s["volumes"] if v["type"] == "bind")), None)
                src = src or next((s["name"] for s in d["services"] if s["role"] in ("web", "proxy")), None)
                if src and src != target:
                    d["edges"].append({"from": src, "to": target, "kind": "fastcgi" if "fastcgi" in m.group(0) else "proxy",
                                       "label": f"{'FastCGI' if 'fastcgi' in m.group(0) else 'proxy'} :{m.group(2)}"})
        if kind == "supervisor config":
            for pm in re.finditer(r"\[program:([^\]]+)\][^\[]*?command\s*=\s*([^\n]+)", text):
                d["supervisor"].append({"file": rel, "program": pm.group(1), "command": pm.group(2).strip()})
        if kind == "PHP ini":
            for im in re.finditer(r"^\s*([\w.]+)\s*=\s*([^\n;]+)", text, re.M):
                if im.group(1) in ("memory_limit", "upload_max_filesize", "post_max_size", "max_execution_time",
                                   "xdebug.mode", "xdebug.client_host", "opcache.enable", "display_errors",
                                   "pcov.enabled", "date.timezone", "opcache.validate_timestamps"):
                    d["php_ini"][im.group(1)] = im.group(2).strip()
    # app -> backing services through env (DB_HOST=mysql …)
    app_env = dict(env)
    if d["app_service"]:
        app_svc = next(s for s in d["services"] if s["name"] == d["app_service"])
        for k, v in app_svc["environment"].items():
            if v and v != "•••":
                app_env[k] = v
    seen = set()
    for k, v in app_env.items():
        v2 = interpolate(str(v), env)[0] if v else ""
        host = v2.split("://", 1)[1].split("/")[0].split(":")[0].split("@")[-1] if "://" in v2 else v2.split(":")[0]
        if host in names and d["app_service"] and host != d["app_service"]:
            key = (d["app_service"], host)
            d["env_used"].append({"key": k, "service": host})
            if key not in seen:
                seen.add(key)
                d["edges"].append({"from": d["app_service"], "to": host, "kind": "env", "label": k})
            else:
                for e in d["edges"]:
                    if (e["from"], e["to"]) == key and e["kind"] == "env" and k not in e["label"]:
                        e["label"] += ", " + k
    for s in d["services"]:
        if s["role"] in ("queue", "scheduler", "websockets") and d["app_service"]:
            for e in list(d["edges"]):
                if e["from"] == d["app_service"] and e["kind"] == "env":
                    pass
    d["networks"] = list((merged.get("networks") or {}).keys()) if isinstance(merged.get("networks"), dict) else []
    d["volumes"] = list((merged.get("volumes") or {}).keys()) if isinstance(merged.get("volumes"), dict) else []
    d["present"] = bool(d["services"]) or bool(d["dockerfiles"])
    return d


def command_prefixes(docker, proj):
    """How to run artisan/composer/npm in this project's dev environment."""
    if docker.get("sail"):
        s = "./vendor/bin/sail"
        return {"mode": "Laravel Sail", "artisan": f"{s} artisan", "composer": f"{s} composer", "npm": f"{s} npm",
                "php": f"{s} php", "shell": f"{s} shell", "up": f"{s} up -d", "down": f"{s} down",
                "build": f"{s} build --no-cache && {s} up -d", "logs": f"{s} logs -f", "test": f"{s} test",
                "tinker": f"{s} tinker", "ps": f"{s} ps"}
    if docker.get("app_service"):
        dc, svc = docker["compose_cmd"], docker["app_service"]
        node = docker.get("node_service")
        npm = f"{dc} run --rm {node} npm" if node else "npm"
        return {"mode": "docker compose", "artisan": f"{dc} exec {svc} php artisan", "composer": f"{dc} exec {svc} composer",
                "npm": npm, "php": f"{dc} exec {svc} php", "shell": f"{dc} exec {svc} sh", "up": f"{dc} up -d",
                "down": f"{dc} down", "build": f"{dc} up -d --build", "logs": f"{dc} logs -f",
                "test": f"{dc} exec {svc} php artisan test", "tinker": f"{dc} exec {svc} php artisan tinker",
                "ps": f"{dc} ps"}
    return {"mode": "local PHP", "artisan": "php artisan", "composer": "composer", "npm": "npm", "php": "php",
            "shell": "", "up": "php artisan serve", "down": "", "build": "", "logs": "tail -f storage/logs/laravel.log",
            "test": "php artisan test", "tinker": "php artisan tinker", "ps": ""}


# =====================================================================================================
# 14. Config & environment variables
# =====================================================================================================

ENV_CALL_RE = re.compile(r"""\benv\(\s*['"]([A-Za-z0-9_]+)['"]\s*(?:,\s*([^)]*?))?\)""")


def analyze_config(proj):
    out = {"files": [], "env_refs": defaultdict(list), "env_outside_config": [], "config_reads": Counter()}
    for ap, rel in walk(proj.root, "config", exts=(".php",)):
        pf = proj.php.get(rel)
        if pf is None:
            continue
        keyname = rel[len("config/"):-4].replace("/", ".")
        tree = None
        for k, t in enumerate(pf.toks):
            if t.k == "name" and t.v.lower() == "return":
                tree, _ = pf.value(k + 1, len(pf.toks))
                break
        top = list(tree.keys()) if isinstance(tree, dict) else []
        n_env = 0

        def walk_tree(node, path):
            nonlocal n_env
            if isinstance(node, dict):
                for k, v in node.items():
                    walk_tree(v, f"{path}.{k}")
                return
            if isinstance(node, list):
                for i, v in enumerate(node):
                    walk_tree(v, f"{path}.{i}")
                return
            if isinstance(node, Node):
                if node.type == "call" and node.name == "env" and node.args and isinstance(node.args[0], str):
                    dflt = node.args[1] if len(node.args) > 1 else None
                    out["env_refs"][node.args[0]].append({"config": path, "default": fmt_val(dflt) if len(node.args) > 1 else "",
                                                          "file": rel, "line": node.line or 0})
                    n_env += 1
                    return
                txt = repr(node)
                for m in ENV_CALL_RE.finditer(txt):
                    out["env_refs"][m.group(1)].append({"config": path, "default": (m.group(2) or "").strip(), "file": rel, "line": 0})
                    n_env += 1

        if tree is not None:
            walk_tree(tree, keyname)
        known = {r["config"] for refs in out["env_refs"].values() for r in refs if r["file"] == rel}
        for i, ln in enumerate(pf.text.splitlines(), 1):
            for m in ENV_CALL_RE.finditer(ln):
                if not any(r["file"] == rel and r["line"] == i for r in out["env_refs"][m.group(1)]):
                    refs = [r for r in out["env_refs"][m.group(1)] if r["file"] == rel and r["line"] == 0]
                    if refs:
                        refs[0]["line"] = i
                    elif not known or True:
                        if not any(r["file"] == rel for r in out["env_refs"][m.group(1)]):
                            out["env_refs"][m.group(1)].append({"config": keyname + ".?", "default": (m.group(2) or "").strip(),
                                                                "file": rel, "line": i})
        out["files"].append({"file": rel, "key": keyname, "top_keys": [str(x) for x in top], "env_count": n_env,
                             "lines": pf.lines, "custom": keyname not in STOCK_CONFIG})
    for rel, pf in proj.php.items():
        if rel.startswith("config/") or rel.startswith("tests/"):
            continue
        for i, ln in enumerate(pf.text.splitlines(), 1):
            for m in ENV_CALL_RE.finditer(ln):
                out["env_outside_config"].append({"key": m.group(1), "file": rel, "line": i})
    for c in proj.idx.by_fqn.values():
        for m in c.methods.values():
            for fn, s, ln in c.file.method_scan(c, m).calls:
                if fn == "config" and s:
                    out["config_reads"][s.split(".")[0]] += 1
    out["env_refs"] = dict(out["env_refs"])
    out["config_reads"] = dict(out["config_reads"])
    return out


STOCK_CONFIG = {"app", "auth", "broadcasting", "cache", "cors", "database", "filesystems", "hashing", "logging", "mail",
                "queue", "sanctum", "services", "session", "view", "concurrency", "horizon", "telescope", "livewire",
                "filament", "permission", "reverb", "scout", "octane", "pulse", "debugbar", "dompdf", "ide-helper",
                "activitylog", "media-library", "excel", "trustedproxy", "fortify", "jetstream", "passport", "cashier",
                "inertia", "sail", "pennant", "nightwatch", "sentry", "backup", "data", "query-builder"}


def env_matrix(proj, config, docker):
    keys = set(proj.env_example) | set(proj.env) | set(config["env_refs"]) | {e["key"] for e in config["env_outside_config"]}
    compose_vars = defaultdict(set)
    for s in docker.get("services", []):
        for p in s["ports"]:
            for v in p["vars"]:
                compose_vars[v].add(s["name"])
        for k in s["environment"]:
            compose_vars[k].add(s["name"])
    for f in docker.get("files", []):
        for m in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", read_text(proj.p(f["file"]))):
            compose_vars[m.group(1)].add("(compose)")
    keys |= {k for k in compose_vars if k in proj.env_example or k in proj.env}
    rows = []
    for k in sorted(keys):
        refs = config["env_refs"].get(k, [])
        rows.append({"key": k, "group": k.split("_")[0], "example": mask(k, proj.env_example.get(k)) if k in proj.env_example else None,
                     "in_example": k in proj.env_example, "in_env": k in proj.env if proj.env else None,
                     "env_empty": (k in proj.env and proj.env.get(k) == ""),
                     "config": [r["config"] for r in refs], "defaults": [r["default"] for r in refs if r["default"]],
                     "code": [f"{e['file']}:{e['line']}" for e in config["env_outside_config"] if e["key"] == k],
                     "compose": sorted(compose_vars.get(k, []))})
    return rows


KNOWN_PACKAGES = {
    "laravel/framework": "The Laravel framework itself.",
    "laravel/sanctum": "API tokens and SPA cookie authentication.",
    "laravel/passport": "Full OAuth2 server for API authentication.",
    "laravel/horizon": "Dashboard and supervisor for Redis queues (/horizon).",
    "laravel/telescope": "Debug assistant: requests, queries, jobs, mail… (/telescope).",
    "laravel/pulse": "Production performance dashboard (/pulse).",
    "laravel/octane": "Keeps the app in memory (Swoole/RoadRunner/FrankenPHP) for speed.",
    "laravel/reverb": "First-party WebSocket server for broadcasting.",
    "laravel/scout": "Full-text search on models (Meilisearch, Algolia, Typesense…).",
    "laravel/cashier": "Stripe subscriptions and billing.", "laravel/cashier-paddle": "Paddle subscriptions and billing.",
    "laravel/socialite": "Log in with Google, GitHub, Facebook… (OAuth).",
    "laravel/fortify": "Headless authentication backend (login, 2FA, password reset).",
    "laravel/jetstream": "Starter kit: auth, teams, profile, API tokens.",
    "laravel/breeze": "Minimal auth starter kit (scaffolding).", "laravel/ui": "Legacy auth scaffolding (Bootstrap/Vue).",
    "laravel/sail": "Docker dev environment wrapper (./vendor/bin/sail).", "laravel/pint": "Code style fixer (PSR-12 / Laravel preset).",
    "laravel/dusk": "Browser tests with ChromeDriver.", "laravel/pennant": "Feature flags.",
    "laravel/folio": "File-based page routing.", "laravel/prompts": "Pretty CLI prompts for commands.",
    "laravel/tinker": "REPL: php artisan tinker.", "laravel/vapor-core": "Runtime for Laravel Vapor (AWS Lambda).",
    "laravel/nightwatch": "Hosted monitoring agent.", "laravel/pail": "Tail application logs in the terminal.",
    "laravel/boost": "AI coding assistant context for Laravel.", "laravel/mcp": "Expose MCP servers from Laravel.",
    "livewire/livewire": "Server-driven reactive UI components.", "livewire/volt": "Single-file Livewire components.",
    "livewire/flux": "Official Livewire UI component library.",
    "filament/filament": "Admin panel framework (resources, forms, tables) built on Livewire.",
    "inertiajs/inertia-laravel": "Build a Vue/React/Svelte SPA with server-side routing.",
    "tightenco/ziggy": "Use Laravel named routes in JavaScript.",
    "spatie/laravel-permission": "Roles and permissions for users.", "spatie/laravel-medialibrary": "Attach files/images to models, with conversions.",
    "spatie/laravel-activitylog": "Log model changes and user activity.", "spatie/laravel-backup": "Backups of files and database.",
    "spatie/laravel-query-builder": "Filter/sort/include API queries from the URL.", "spatie/laravel-data": "Typed data objects (DTOs) with validation.",
    "spatie/laravel-settings": "Strongly typed application settings.", "spatie/laravel-translatable": "Translatable model attributes (JSON).",
    "spatie/laravel-sluggable": "Generate slugs for models.", "spatie/laravel-tags": "Tagging for models.",
    "spatie/laravel-ray": "Debug with the Ray desktop app.", "spatie/laravel-ignition": "Error page for local development.",
    "spatie/laravel-webhook-client": "Receive and process webhooks.", "spatie/laravel-health": "Health checks for the app.",
    "barryvdh/laravel-debugbar": "Debug toolbar in the browser (dev only).", "barryvdh/laravel-ide-helper": "IDE autocompletion helpers.",
    "barryvdh/laravel-dompdf": "Generate PDFs from Blade views.", "maatwebsite/excel": "Excel/CSV import and export.",
    "league/flysystem-aws-s3-v3": "Store files on Amazon S3.", "predis/predis": "Redis client written in PHP.",
    "guzzlehttp/guzzle": "HTTP client (used by Http:: facade).", "pestphp/pest": "Testing framework (expressive syntax on PHPUnit).",
    "phpunit/phpunit": "Testing framework.", "larastan/larastan": "Static analysis (PHPStan for Laravel).",
    "nunomaduro/larastan": "Static analysis (PHPStan for Laravel).", "nunomaduro/collision": "Readable CLI errors in tests.",
    "fakerphp/faker": "Fake data for factories.", "mockery/mockery": "Mocking for tests.",
    "sentry/sentry-laravel": "Error tracking with Sentry.", "bugsnag/bugsnag-laravel": "Error tracking with Bugsnag.",
    "stripe/stripe-php": "Stripe API client.", "intervention/image": "Image manipulation.",
    "lorisleiva/laravel-actions": "Action classes usable as controllers, jobs, listeners.",
    "owen-it/laravel-auditing": "Audit trail of model changes.", "doctrine/dbal": "Schema introspection (needed for column changes on old Laravel).",
    "fruitcake/laravel-cors": "CORS headers (built into Laravel 9+).", "nwidart/laravel-modules": "Organise the app into modules.",
    "stancl/tenancy": "Multi-tenancy.", "spatie/laravel-multitenancy": "Multi-tenancy.", "opcodesio/log-viewer": "Browse logs at /log-viewer.",
    "rap2hpoutre/laravel-log-viewer": "Browse logs in the browser.", "aws/aws-sdk-php": "AWS SDK.",
    "pusher/pusher-php-server": "Pusher broadcasting driver.", "beyondcode/laravel-websockets": "Self-hosted WebSockets (legacy).",
    "dedoc/scramble": "Automatic OpenAPI docs (/docs/api).", "knuckleswtf/scribe": "API documentation generator.",
    "darkaonline/l5-swagger": "Swagger/OpenAPI docs.", "laravel-notification-channels/telegram": "Telegram notifications.",
    "kreait/laravel-firebase": "Firebase SDK.", "bezhansalleh/filament-shield": "Roles & permissions UI for Filament.",
    "pxlrbt/filament-excel": "Excel export for Filament tables.", "openai-php/laravel": "OpenAI API client.",
    "anthropic-ai/sdk": "Anthropic API client.", "echolabsdev/prism": "LLM integration toolkit.", "prism-php/prism": "LLM integration toolkit.",
    "wire-elements/modal": "Livewire modals.", "rappasoft/laravel-livewire-tables": "Datatables for Livewire.",
    "power-components/livewire-powergrid": "Datatables for Livewire.", "blade-ui-kit/blade-heroicons": "Heroicons as Blade components.",
    "itsgoingd/clockwork": "Dev profiler.", "enlightn/enlightn": "Performance & security checks.",
}
KNOWN_NPM = {
    "vue": "Vue.js UI framework.", "react": "React UI library.", "svelte": "Svelte UI framework.",
    "@inertiajs/vue3": "Inertia adapter for Vue 3.", "@inertiajs/react": "Inertia adapter for React.",
    "@inertiajs/svelte": "Inertia adapter for Svelte.", "alpinejs": "Lightweight JS sprinkles in Blade (x-data).",
    "tailwindcss": "Utility-first CSS framework.", "bootstrap": "Bootstrap CSS framework.", "jquery": "jQuery.",
    "axios": "HTTP client for the browser.", "laravel-echo": "Listen to broadcast events in JS.",
    "pusher-js": "Pusher/Reverb WebSocket client.", "vite": "Frontend build tool / dev server.",
    "laravel-vite-plugin": "Connects Vite with Laravel (@vite directive).", "laravel-mix": "Webpack wrapper (older asset pipeline).",
    "typescript": "TypeScript compiler.", "@vitejs/plugin-vue": "Vue support for Vite.", "@vitejs/plugin-react": "React support for Vite.",
    "ziggy-js": "Laravel routes in JS.", "chart.js": "Charts.", "lodash": "Utility functions.", "sass": "Sass/SCSS compiler.",
    "postcss": "CSS transforms.", "autoprefixer": "Vendor prefixes for CSS.", "eslint": "JS linter.", "prettier": "Code formatter.",
    "vitest": "Unit test runner for JS.", "@playwright/test": "End-to-end browser tests.", "cypress": "End-to-end browser tests.",
    "@tailwindcss/vite": "Tailwind v4 Vite plugin.", "@tailwindcss/forms": "Tailwind form styles.", "concurrently": "Run several dev processes together.",
    "@headlessui/vue": "Accessible UI primitives for Vue.", "@headlessui/react": "Accessible UI primitives for React.",
    "vue-router": "Client-side routing for Vue.", "pinia": "State management for Vue.", "@tanstack/react-query": "Server-state caching for React.",
}


# =====================================================================================================
# 15. Tooling, CI, docs
# =====================================================================================================

def analyze_tooling(proj):
    out = {"composer_scripts": {}, "npm_scripts": {}, "make": [], "quality": [], "ci": [], "deploy": [], "docs": [],
           "readme": None, "phpunit": {}, "tests": {}}
    for k, v in (proj.composer.get("scripts") or {}).items():
        if k.startswith(("pre-", "post-")):
            continue
        out["composer_scripts"][k] = [str(x) for x in _as_list(v)]
    out["npm_scripts"] = {k: str(v) for k, v in (proj.pkg.get("scripts") or {}).items()}
    for mf in ("Makefile", "makefile", "GNUmakefile"):
        if proj.exists(mf):
            lines = read_text(proj.p(mf)).splitlines()
            for i, ln in enumerate(lines):
                m = re.match(r"^([A-Za-z0-9][\w.\-/]*)\s*:(?!=)([^#\n]*)(?:##\s*(.*))?$", ln)
                if m and m.group(1) not in (".PHONY", ".DEFAULT_GOAL"):
                    recipe = lines[i + 1].strip() if i + 1 < len(lines) and lines[i + 1].startswith(("\t", "    ")) else ""
                    out["make"].append({"target": m.group(1), "desc": (m.group(3) or "").strip(), "recipe": recipe.lstrip("@")})
            break
    checks = [
        ("pint.json", "Laravel Pint", "Code style", "./vendor/bin/pint"),
        (".php-cs-fixer.php", "PHP CS Fixer", "Code style", "./vendor/bin/php-cs-fixer fix"),
        (".php-cs-fixer.dist.php", "PHP CS Fixer", "Code style", "./vendor/bin/php-cs-fixer fix"),
        ("phpstan.neon", "PHPStan / Larastan", "Static analysis", "./vendor/bin/phpstan analyse"),
        ("phpstan.neon.dist", "PHPStan / Larastan", "Static analysis", "./vendor/bin/phpstan analyse"),
        ("psalm.xml", "Psalm", "Static analysis", "./vendor/bin/psalm"),
        ("rector.php", "Rector", "Automated refactoring", "./vendor/bin/rector --dry-run"),
        ("phpunit.xml", "PHPUnit config", "Tests", "php artisan test"),
        ("phpunit.xml.dist", "PHPUnit config", "Tests", "php artisan test"),
        ("tests/Pest.php", "Pest", "Tests", "./vendor/bin/pest"),
        ("infection.json5", "Infection", "Mutation testing", "./vendor/bin/infection"),
        ("deptrac.yaml", "Deptrac", "Architecture rules", "./vendor/bin/deptrac"),
        (".editorconfig", "EditorConfig", "Editor settings", ""),
        ("eslint.config.js", "ESLint", "JS lint", "npx eslint ."), (".eslintrc.js", "ESLint", "JS lint", "npx eslint ."),
        (".eslintrc.json", "ESLint", "JS lint", "npx eslint ."), (".eslintrc.cjs", "ESLint", "JS lint", "npx eslint ."),
        (".prettierrc", "Prettier", "Formatting", "npx prettier --check ."), (".prettierrc.json", "Prettier", "Formatting", "npx prettier --check ."),
        ("prettier.config.js", "Prettier", "Formatting", "npx prettier --check ."), ("tsconfig.json", "TypeScript", "Types", "npx tsc --noEmit"),
        (".husky", "Husky", "Git hooks", ""), ("captainhook.json", "CaptainHook", "Git hooks", ""),
        ("grumphp.yml", "GrumPHP", "Git hooks", ""), ("lefthook.yml", "Lefthook", "Git hooks", ""),
        (".pre-commit-config.yaml", "pre-commit", "Git hooks", ""), (".styleci.yml", "StyleCI", "Code style (hosted)", ""),
    ]
    seen = set()
    for f, name, kind, cmd in checks:
        if proj.exists(f) and name not in seen:
            seen.add(name)
            extra = ""
            if "phpstan" in f:
                m = re.search(r"level:\s*(\w+)", read_text(proj.p(f)))
                extra = f"level {m.group(1)}" if m else ""
            out["quality"].append({"file": f, "tool": name, "kind": kind, "command": cmd, "extra": extra})
    if "Laravel Pint" not in seen and proj.has_pkg("laravel/pint"):
        out["quality"].append({"file": "(composer)", "tool": "Laravel Pint", "kind": "Code style", "command": "./vendor/bin/pint", "extra": "default preset"})
    for f in ("phpunit.xml", "phpunit.xml.dist"):
        if proj.exists(f):
            t = read_text(proj.p(f))
            out["phpunit"] = {"file": f, "suites": re.findall(r"<testsuite\s+name=\"([^\"]+)\"", t),
                              "env": {m.group(1): mask(m.group(1), m.group(2)) for m in re.finditer(r"<(?:env|server)\s+name=\"([^\"]+)\"\s+value=\"([^\"]*)\"", t)}}
            break
    # CI
    for ap, rel in walk(proj.root, ".github/workflows", exts=(".yml", ".yaml")):
        data = yaml_load(read_text(ap)) or {}
        if not isinstance(data, dict):
            continue
        on = data.get("on", data.get(True))
        triggers = list(on.keys()) if isinstance(on, dict) else [str(x) for x in _as_list(on)]
        jobs = []
        for jid, j in (data.get("jobs") or {}).items():
            if not isinstance(j, dict):
                continue
            steps = []
            for st in j.get("steps") or []:
                if not isinstance(st, dict):
                    continue
                if st.get("run"):
                    steps.append({"name": st.get("name") or "", "run": str(st["run"]).strip().splitlines()[0][:160]})
                elif st.get("uses"):
                    steps.append({"name": st.get("name") or "", "uses": str(st["uses"])})
            jobs.append({"id": jid, "name": j.get("name") or jid, "runs_on": str(j.get("runs-on", "")),
                         "services": list((j.get("services") or {}).keys()) if isinstance(j.get("services"), dict) else [],
                         "steps": steps, "needs": [str(x) for x in _as_list(j.get("needs"))]})
        out["ci"].append({"system": "GitHub Actions", "file": rel, "name": data.get("name") or rel, "triggers": triggers, "jobs": jobs})
    if proj.exists(".gitlab-ci.yml"):
        data = yaml_load(read_text(proj.p(".gitlab-ci.yml"))) or {}
        jobs = []
        reserved = {"stages", "variables", "default", "include", "image", "services", "cache", "before_script", "after_script", "workflow"}
        for k, v in (data.items() if isinstance(data, dict) else []):
            if k in reserved or str(k).startswith(".") or not isinstance(v, dict):
                continue
            jobs.append({"id": k, "name": k, "runs_on": str(v.get("image", "")), "services": [],
                         "steps": [{"name": "", "run": str(x)[:160]} for x in _as_list(v.get("script"))], "needs": [str(v.get("stage", ""))]})
        out["ci"].append({"system": "GitLab CI", "file": ".gitlab-ci.yml", "name": "GitLab CI", "triggers": [], "jobs": jobs})
    if proj.exists("bitbucket-pipelines.yml"):
        out["ci"].append({"system": "Bitbucket Pipelines", "file": "bitbucket-pipelines.yml", "name": "Bitbucket Pipelines", "triggers": [], "jobs": []})
    if proj.exists(".circleci/config.yml"):
        out["ci"].append({"system": "CircleCI", "file": ".circleci/config.yml", "name": "CircleCI", "triggers": [], "jobs": []})
    if proj.exists("Jenkinsfile"):
        out["ci"].append({"system": "Jenkins", "file": "Jenkinsfile", "name": "Jenkins", "triggers": [], "jobs": []})
    for f, what in (("Envoy.blade.php", "Laravel Envoy tasks"), ("deploy.php", "Deployer"), ("vapor.yml", "Laravel Vapor"),
                    ("fly.toml", "Fly.io"), ("Procfile", "Procfile (Heroku-style)"), ("render.yaml", "Render"),
                    (".platform.app.yaml", "Platform.sh"), ("app.yaml", "Google App Engine"), ("serverless.yml", "Serverless / Bref"),
                    ("kustomization.yaml", "Kubernetes (kustomize)"), ("helm", "Helm chart"), ("k8s", "Kubernetes manifests"),
                    ("terraform", "Terraform"), ("forge-deploy.sh", "Laravel Forge"), ("cloud.yaml", "Laravel Cloud"),
                    (".do/app.yaml", "DigitalOcean App Platform"), ("ploi.sh", "Ploi")):
        if proj.exists(f):
            out["deploy"].append({"file": f, "what": what})
    # docs
    doc_files = []
    for f in sorted(os.listdir(proj.root)):
        if re.match(r"(README|CONTRIBUTING|CHANGELOG|UPGRADE|SECURITY|ARCHITECTURE|DEVELOPMENT|SETUP|INSTALL|NOTES|CLAUDE|AGENTS)(\.\w+)?$", f, re.I):
            doc_files.append(f)
    for d in ("docs", "doc", "documentation", ".github"):
        for ap, rel in walk(proj.root, d, exts=(".md", ".markdown", ".rst", ".txt"), max_depth=3):
            doc_files.append(rel)
    for rel in doc_files:
        t = read_text(proj.p(rel))
        h = re.search(r"^#\s+(.+)$", t, re.M)
        out["docs"].append({"file": rel, "title": h.group(1).strip() if h else "", "lines": t.count("\n") + 1})
    readme = next((f for f in doc_files if re.match(r"README(\.md)?$", f, re.I)), None)
    if readme:
        out["readme"] = {"file": readme, "text": read_text(proj.p(readme))[:60000]}
    # tests
    tests = {"pest": proj.exists("tests", "Pest.php") or proj.has_pkg("pestphp/pest"), "files": 0, "cases": 0, "by_dir": Counter(), "list": []}
    for ap, rel in walk(proj.root, "tests", exts=(".php",)):
        t = read_text(ap)
        names = re.findall(r"^\s*(?:it|test)\(\s*['\"]([^'\"]+)", t, re.M)
        names += [snake(n).replace("_", " ") for n in re.findall(r"function\s+test_?(\w+)\s*\(", t)]
        names += re.findall(r"@test\s*\*/\s*public function (\w+)", t)
        names += re.findall(r"#\[Test\][^\n]*\n\s*public function (\w+)", t)
        if names or "TestCase" in t:
            tests["files"] += 1
            tests["cases"] += len(names)
            seg = rel.split("/")[1] if rel.count("/") >= 2 else "(root)"
            tests["by_dir"][seg] += len(names)
            tests["list"].append({"file": rel, "cases": names[:40]})
    tests["by_dir"] = dict(tests["by_dir"])
    out["tests"] = tests
    return out


# =====================================================================================================
# 16. Git, local machine status, live artisan data
# =====================================================================================================

def git(root, *args, timeout=30):
    rc, out, err = run(["git", "-C", root, *args], timeout=timeout)
    return out if rc == 0 else None


def is_git(root):
    return git(root, "rev-parse", "--is-inside-work-tree") is not None


def clean_remote(url):
    return re.sub(r"//[^@/]+@", "//", url or "").strip()


def git_info(root):
    if not is_git(root):
        return None
    info = {"head": (git(root, "rev-parse", "HEAD") or "").strip(), "branch": (git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip(),
            "remote": clean_remote((git(root, "config", "--get", "remote.origin.url") or "").strip()), "upstream": None,
            "ahead": 0, "behind": 0, "dirty": [], "stashes": 0, "last_commit": None, "last_fetch": None, "recent": [],
            "churn": [], "owners": {}, "commits_total": 0, "first_commit": None, "contributors": 0}
    up = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up:
        info["upstream"] = up.strip()
        lr = git(root, "rev-list", "--left-right", "--count", "@{u}...HEAD")
        if lr and len(lr.split()) == 2:
            info["behind"], info["ahead"] = (int(x) for x in lr.split())
    st = git(root, "status", "--porcelain=v1", "--untracked-files=all") or ""
    info["dirty"] = [{"status": ln[:2].strip() or "?", "file": ln[3:]} for ln in st.splitlines()[:400] if ln.strip()]
    info["stashes"] = len((git(root, "stash", "list") or "").splitlines())
    lc = git(root, "log", "-1", "--format=%h%x1f%an%x1f%aI%x1f%s")
    if lc and "\x1f" in lc:
        h, a, d, s = lc.strip().split("\x1f", 3)
        info["last_commit"] = {"sha": h, "author": a, "date": d, "subject": s}
    fh = os.path.join(root, ".git", "FETCH_HEAD")
    if os.path.exists(fh):
        info["last_fetch"] = dt.datetime.fromtimestamp(os.path.getmtime(fh), dt.timezone.utc).isoformat()
    info["commits_total"] = int((git(root, "rev-list", "--count", "HEAD") or "0").strip() or 0)
    fc = git(root, "log", "--reverse", "--format=%aI", "--max-parents=0")
    info["first_commit"] = fc.strip().splitlines()[0] if fc and fc.strip() else None
    rec = git(root, "log", "-15", "--format=%h%x1f%an%x1f%aI%x1f%s") or ""
    info["recent"] = [dict(zip(("sha", "author", "date", "subject"), ln.split("\x1f", 3))) for ln in rec.splitlines() if ln.count("\x1f") == 3]
    log = git(root, "log", "--since=12 months ago", "--no-merges", "--name-only", "--format=%x00%an", timeout=60) or ""
    per_file, per_file_auth, area_auth, contributors = Counter(), defaultdict(Counter), defaultdict(Counter), set()
    for block in log.split("\x00")[1:]:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        author = lines[0]
        contributors.add(author)
        for f in lines[1:]:
            per_file[f] += 1
            per_file_auth[f][author] += 1
            area_auth[file_area(f)][author] += 1
    info["contributors"] = len(contributors)
    info["churn"] = [{"file": f, "commits": n, "authors": [a for a, _ in per_file_auth[f].most_common(3)]}
                     for f, n in per_file.most_common(30) if os.path.exists(os.path.join(root, f))]
    info["owners"] = {area: [{"author": a, "commits": n} for a, n in c.most_common(3)] for area, c in area_auth.items()}
    return info


AREAS = [
    ("Routes", r"^routes/"), ("Migrations", r"^database/migrations/"), ("Seeders & factories", r"^database/(seeders|factories|seeds)/"),
    ("Models", r"^app/Models/"), ("Controllers", r"^app/Http/Controllers/"), ("Middleware", r"^app/Http/Middleware/"),
    ("Requests & resources", r"^app/Http/(Requests|Resources)/"), ("Livewire", r"^(app/(Http/)?Livewire/|resources/views/livewire/)"),
    ("Filament", r"^app/Filament/|^app/Providers/Filament/"), ("Jobs, events & listeners", r"^app/(Jobs|Events|Listeners|Observers)/"),
    ("Mail & notifications", r"^app/(Mail|Notifications)/"), ("Console", r"^app/Console/"), ("Providers & bootstrap", r"^(app/Providers/|bootstrap/)"),
    ("Blade views", r"^resources/views/"), ("Frontend JS/CSS", r"^resources/(js|css|ts|sass|scss)/|^(vite|webpack|tailwind|postcss)\."),
    ("Config", r"^config/"), ("Docker", r"(^|/)(docker|\.docker)/|(^|/)Dockerfile|compose[\w.\-]*\.ya?ml$|^\.devcontainer/"),
    ("PHP dependencies", r"^composer\.(json|lock)$"), ("JS dependencies", r"^(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?)$"),
    ("Environment template", r"^\.env\.example$"), ("Tests", r"^tests/"), ("CI / deploy", r"^\.github/|^\.gitlab-ci|^Envoy|^deploy"),
    ("Docs", r"\.md$"), ("Other app code", r"^app/"),
]


def file_area(f):
    for name, rx in AREAS:
        if re.search(rx, f):
            return name
    return "Other"


def local_status(proj, docker, prefixes):
    st = {"env_exists": proj.exists(".env"), "env_missing": [], "env_extra": [], "app_key": None, "vendor": proj.exists("vendor"),
          "node_modules": proj.exists("node_modules"), "composer_out_of_sync": [], "npm_out_of_sync": [], "containers": None,
          "docker_cli": bool(shutil.which("docker"))}
    if st["env_exists"]:
        st["env_missing"] = [k for k in proj.env_example if k not in proj.env]
        st["env_extra"] = [k for k in proj.env if k not in proj.env_example]
        st["app_key"] = bool(proj.env.get("APP_KEY"))
    inst = read_json(proj.p("vendor", "composer", "installed.json"))
    if inst is not None:
        pk = inst.get("packages", inst) if isinstance(inst, dict) else inst
        installed = {p.get("name"): p.get("version") for p in pk if isinstance(p, dict)}
        for name, info in proj.locked_versions().items():
            if installed.get(name) != info["version"]:
                st["composer_out_of_sync"].append({"name": name, "locked": info["version"], "installed": installed.get(name)})
    nl = read_json(proj.p("node_modules", ".package-lock.json"))
    if nl is not None:
        installed = {k[13:]: v.get("version") for k, v in (nl.get("packages") or {}).items() if k.startswith("node_modules/")}
        for name, ver in proj.npm_locked().items():
            if name in (proj.pkg.get("dependencies") or {}) or name in (proj.pkg.get("devDependencies") or {}):
                if installed.get(name) != ver:
                    st["npm_out_of_sync"].append({"name": name, "locked": ver, "installed": installed.get(name)})
    if st["docker_cli"] and docker.get("services"):
        rc, out, err = run(f"{docker['compose_cmd']} ps --all --format json", cwd=proj.root, timeout=20)
        if rc == 0 and out.strip():
            rows = []
            try:
                data = json.loads(out)
                rows = data if isinstance(data, list) else [data]
            except ValueError:
                for ln in out.splitlines():
                    try:
                        rows.append(json.loads(ln))
                    except ValueError:
                        pass
            st["containers"] = [{"service": r.get("Service"), "state": r.get("State"), "status": r.get("Status"),
                                 "health": r.get("Health")} for r in rows if isinstance(r, dict)]
        elif rc == 0:
            st["containers"] = []
    return st


def detect_artisan(proj, docker, arg):
    if not arg:
        return None
    if arg != "auto":
        return arg
    if docker.get("app_service") and shutil.which("docker"):
        rc, out, _ = run(f"{docker['compose_cmd']} ps --services --status running", cwd=proj.root, timeout=20)
        if rc == 0 and docker["app_service"] in out.split():
            return f"{docker['compose_cmd']} exec -T {docker['app_service']} php artisan"
    if shutil.which("php") and proj.exists("artisan") and proj.exists("vendor", "autoload.php"):
        return "php artisan"
    return None


def runtime_data(proj, prefix, want_db, models):
    rt = {"command": prefix, "routes": None, "about": None, "migrations": None, "models": {}, "errors": []}

    def art(args, timeout=120):
        rc, out, err = run(f"{prefix} {args}", cwd=proj.root, timeout=timeout)
        if rc != 0:
            rt["errors"].append(f"`{prefix} {args}` failed: {(err or out).strip()[:300]}")
            return None
        return out

    out = art("route:list --json")
    if out:
        try:
            data = json.loads(out[out.find("["):])
            routes = []
            for r in data:
                m = r.get("method", "")
                act = r.get("action", "")
                ctrl, meth = (act.split("@", 1) + [None])[:2] if "@" in act else (act if "\\" in act else None, None)
                routes.append({"methods": [x for x in m.split("|") if x], "uri": "/" + r.get("uri", "").lstrip("/"),
                               "name": r.get("name"), "action": act, "action_type": "closure" if act == "Closure" else "controller",
                               "controller": ctrl, "method": meth,
                               "middleware": r.get("middleware") if isinstance(r.get("middleware"), list) else [x for x in str(r.get("middleware") or "").split("\n") if x],
                               "file": None, "line": None, "group": "", "domain": r.get("domain"), "source": "artisan"})
            rt["routes"] = routes
        except (ValueError, AttributeError) as ex:
            rt["errors"].append(f"Could not parse route:list output ({ex}).")
    out = art("about --json")
    if out:
        try:
            rt["about"] = json.loads(out[out.find("{"):])
        except ValueError:
            pass
    out = art("migrate:status")
    if out:
        mig = []
        for ln in out.splitlines():
            m = re.match(r"^\s*(\S+?)\s+\.{2,}\s+(?:\[(\d+)\]\s+)?(Ran|Pending)", ln)
            if m:
                mig.append({"name": m.group(1), "status": m.group(3), "batch": m.group(2)})
                continue
            m = re.match(r"^\|\s*(Yes|No|Y|N)\s*\|\s*(\S+)\s*\|", ln)
            if m:
                mig.append({"name": m.group(2), "status": "Ran" if m.group(1).startswith("Y") else "Pending", "batch": None})
        rt["migrations"] = mig
    if want_db:
        for fqn in list(models)[:80]:
            out = art(f"model:show {shlex.quote(fqn)} --json", timeout=60)
            if out:
                try:
                    rt["models"][fqn] = json.loads(out[out.find("{"):])
                except ValueError:
                    pass
    return rt


# =====================================================================================================
# 17. Middleware
# =====================================================================================================

L11_GLOBAL = ["Illuminate\\Foundation\\Http\\Middleware\\InvokeDeferredCallbacks", "Illuminate\\Http\\Middleware\\TrustProxies",
              "Illuminate\\Http\\Middleware\\HandleCors", "Illuminate\\Foundation\\Http\\Middleware\\PreventRequestsDuringMaintenance",
              "Illuminate\\Http\\Middleware\\ValidatePostSize", "Illuminate\\Foundation\\Http\\Middleware\\TrimStrings",
              "Illuminate\\Foundation\\Http\\Middleware\\ConvertEmptyStringsToNull"]
L11_WEB = ["Illuminate\\Cookie\\Middleware\\EncryptCookies", "Illuminate\\Cookie\\Middleware\\AddQueuedCookiesToResponse",
           "Illuminate\\Session\\Middleware\\StartSession", "Illuminate\\View\\Middleware\\ShareErrorsFromSession",
           "Illuminate\\Foundation\\Http\\Middleware\\ValidateCsrfToken", "Illuminate\\Routing\\Middleware\\SubstituteBindings"]
L11_API = ["Illuminate\\Routing\\Middleware\\SubstituteBindings"]
L11_ALIASES = {"auth": "Illuminate\\Auth\\Middleware\\Authenticate", "auth.basic": "Illuminate\\Auth\\Middleware\\AuthenticateWithBasicAuth",
               "auth.session": "Illuminate\\Session\\Middleware\\AuthenticateSession", "cache.headers": "Illuminate\\Http\\Middleware\\SetCacheHeaders",
               "can": "Illuminate\\Auth\\Middleware\\Authorize", "guest": "Illuminate\\Auth\\Middleware\\RedirectIfAuthenticated",
               "password.confirm": "Illuminate\\Auth\\Middleware\\RequirePassword", "precognitive": "Illuminate\\Foundation\\Http\\Middleware\\HandlePrecognitiveRequests",
               "signed": "Illuminate\\Routing\\Middleware\\ValidateSignature", "throttle": "Illuminate\\Routing\\Middleware\\ThrottleRequests",
               "verified": "Illuminate\\Auth\\Middleware\\EnsureEmailIsVerified"}


def analyze_middleware(proj):
    out = {"style": None, "global": [], "groups": {}, "aliases": {}, "notes": [], "framework_defaults": False}
    kernel = proj.php.get("app/Http/Kernel.php")
    kc = next((c for c in kernel.classes if c.name == "Kernel"), None) if kernel else None
    if kc is not None:
        out["style"] = "app/Http/Kernel.php"
        out["global"] = class_strs(prop_value(proj, kc, "middleware", []))
        groups = prop_value(proj, kc, "middlewareGroups", {})
        if isinstance(groups, dict):
            out["groups"] = {str(k): class_strs(v) + [s for s in strs(v) if "\\" not in s] for k, v in groups.items()}
        al = prop_value(proj, kc, "middlewareAliases") or prop_value(proj, kc, "routeMiddleware") or {}
        if isinstance(al, dict):
            out["aliases"] = {str(k): str(v) for k, v in al.items() if isinstance(v, str)}
        return out
    app = proj.php.get("bootstrap/app.php")
    if app is None:
        return out
    T = app.toks
    for k, t in enumerate(T):
        if t.k == "name" and t.v == "withMiddleware" and k + 1 < len(T) and T[k + 1].v == "(":
            out["style"] = "bootstrap/app.php"
            out["framework_defaults"] = True
            out["global"] = list(L11_GLOBAL)
            out["groups"] = {"web": list(L11_WEB), "api": list(L11_API)}
            out["aliases"] = dict(L11_ALIASES)
            close = app.pair.get(k + 1, k + 1)
            for calls in find_var_chains(app, k + 2, close, {"$middleware"}):
                for call in calls:
                    n, a, kw = call.name, call.args, call.kw
                    if n == "alias" and a and isinstance(a[0], dict):
                        out["aliases"].update({str(x): str(y) for x, y in a[0].items() if isinstance(y, str)})
                    elif n in ("web", "api"):
                        g = out["groups"].setdefault(n, [])
                        for x in class_strs(kw.get("prepend")):
                            g.insert(0, x)
                        g += class_strs(kw.get("append"))
                        for x in class_strs(kw.get("remove")):
                            if x in g:
                                g.remove(x)
                        rep = kw.get("replace")
                        if isinstance(rep, dict):
                            for old, new in rep.items():
                                if old in g:
                                    g[g.index(old)] = str(new)
                    elif n == "append":
                        out["global"] += class_strs(a)
                    elif n == "prepend":
                        out["global"] = class_strs(a) + out["global"]
                    elif n == "use" and a:
                        out["global"] = class_strs(a[0])
                    elif n == "group" and len(a) >= 2 and isinstance(a[0], str):
                        out["groups"][a[0]] = class_strs(a[1])
                    elif n == "appendToGroup" and len(a) >= 2 and isinstance(a[0], str):
                        out["groups"].setdefault(a[0], []).extend(class_strs(a[1]))
                    elif n == "statefulApi":
                        out["groups"]["api"].insert(0, "Laravel\\Sanctum\\Http\\Middleware\\EnsureFrontendRequestsAreStateful")
                        out["notes"].append("statefulApi(): SPA cookie authentication (Sanctum) is enabled for API routes.")
                    elif n == "throttleApi":
                        out["groups"]["api"].insert(0, "throttle:" + (a[0] if a and isinstance(a[0], str) else "api"))
                    elif n == "validateCsrfTokens":
                        out["notes"].append("CSRF checks skipped for: " + ", ".join(strs(kw.get("except") or a)))
                    elif n == "encryptCookies":
                        out["notes"].append("Cookies not encrypted: " + ", ".join(strs(kw.get("except") or a)))
                    elif n == "trustProxies":
                        out["notes"].append("Trusted proxies configured: " + fmt_val(kw.get("at") or (a[0] if a else "")))
                    elif n == "redirectGuestsTo":
                        out["notes"].append("Guests are redirected to " + (fmt_val(a[0]) if a else "?"))
                    elif n == "redirectUsersTo":
                        out["notes"].append("Logged-in users hitting guest pages go to " + (fmt_val(a[0]) if a else "?"))
                    elif n in ("trustHosts", "preventRequestsDuringMaintenance", "convertEmptyStringsToNull", "trimStrings"):
                        out["notes"].append(f"{n}() customised.")
            break
    return out


# =====================================================================================================
# 18. Package routes we can infer (only shown when `artisan route:list` was not available)
# =====================================================================================================

PACKAGE_ROUTES = {
    "laravel/horizon": [(["GET"], "/horizon", "horizon.index", "Horizon dashboard")],
    "laravel/telescope": [(["GET"], "/telescope", "telescope", "Telescope dashboard")],
    "laravel/pulse": [(["GET"], "/pulse", "pulse", "Pulse dashboard")],
    "laravel/sanctum": [(["GET"], "/sanctum/csrf-cookie", "sanctum.csrf-cookie", "SPA CSRF cookie")],
    "laravel/passport": [(["POST"], "/oauth/token", "passport.token", "OAuth token endpoint"),
                         (["GET"], "/oauth/authorize", "passport.authorizations.authorize", "OAuth authorise screen")],
    "livewire/livewire": [(["POST"], "/livewire/update", "livewire.update", "Livewire component updates (AJAX)"),
                          (["GET"], "/livewire/livewire.js", None, "Livewire JS asset")],
    "opcodesio/log-viewer": [(["GET"], "/log-viewer", "log-viewer.index", "Log viewer")],
    "dedoc/scramble": [(["GET"], "/docs/api", "scramble.docs.ui", "API documentation UI")],
    "barryvdh/laravel-debugbar": [(["GET"], "/_debugbar/open", "debugbar.openhandler", "Debugbar (dev only)")],
    "laravel/fortify": [(["GET", "POST"], "/login", "login", "Fortify login"), (["POST"], "/logout", "logout", "Fortify logout"),
                        (["GET", "POST"], "/register", "register", "Fortify registration")],
    "spatie/laravel-health": [(["GET"], "/health", None, "Health check (if registered)")],
}


def package_routes(proj, existing):
    have = {(tuple(r["methods"]), r["uri"]) for r in existing}
    uris = {r["uri"] for r in existing}
    out = []
    for pkg, rows in PACKAGE_ROUTES.items():
        if not proj.has_pkg(pkg):
            continue
        for methods, uri, name, label in rows:
            if uri in uris and pkg == "laravel/fortify":
                continue
            ms = methods + (["HEAD"] if methods == ["GET"] else [])
            if (tuple(ms), uri) in have:
                continue
            out.append({"methods": ms, "uri": uri, "name": name, "action": f"{pkg} — {label}", "action_type": "package",
                        "controller": None, "method": None, "middleware": [], "file": None, "line": None,
                        "group": "package", "source": "package (inferred)"})
    return out


# =====================================================================================================
# 19. Classes & dependency graph
# =====================================================================================================

def class_records(proj):
    idx = proj.idx
    out = []
    for fqn, c in sorted(idx.by_fqn.items()):
        refs = set()
        for x in [c.extends] + c.implements + c.traits + [a["name"] for a in c.attrs]:
            if x:
                refs.add(x)
        for p in c.props.values():
            for t in (p["type"] or "").split("|"):
                refs.add(t)
            refs |= set(class_strs(p["value"])) if isinstance(p["value"], (list, Cls)) else set()
            if isinstance(p["value"], dict):
                refs |= set(class_strs(list(p["value"].values()))) | {str(k) for k in p["value"] if isinstance(k, str) and "\\" in k}
        for m in c.methods.values():
            for p in m.params:
                refs |= set(p["types"])
            refs |= set((m.returns or "").split("|"))
            sc = c.file.method_scan(c, m)
            refs |= {r for r, _ in sc.refs}
        deps = sorted(r for r in refs if r and r != fqn and r in idx.by_fqn)
        pub = [m.name for m in c.methods.values() if m.visibility == "public" and not m.name.startswith("__")]
        out.append({"fqn": fqn, "name": c.name, "role": c.role, "kind": c.kind, "file": c.file.rel, "line": c.line,
                    "loc": max(1, c.end_line - c.line + 1), "methods": len(c.methods), "public": pub, "deps": deps,
                    "extends": c.extends, "implements": c.implements, "traits": [short(t) for t in c.traits],
                    "doc": c.doc, "abstract": c.abstract,
                    "long_methods": [{"name": m.name, "lines": m.end_line - m.line + 1} for m in c.methods.values() if m.end_line - m.line + 1 > 80]})
    return out


# =====================================================================================================
# 20. Snapshots & structural diff ("what changed")
# =====================================================================================================

def col_sig(c):
    s = c["type"] + (f"({c['detail']})" if c.get("detail") else "")
    if c.get("nullable"):
        s += " null"
    if c.get("fk") and c["fk"].get("table"):
        s += f" → {c['fk']['table']}"
    return s


def make_snapshot(data):
    snap = {"meta": {"generated": data["meta"]["generated"], "git_sha": (data.get("git") or {}).get("head"),
                     "git_branch": (data.get("git") or {}).get("branch"), "version": VERSION, "root": data["meta"]["root"]}}
    snap["routes"] = {f"{'|'.join(r['methods'])} {r['uri']}": {"name": r["name"], "action": r["action"],
                                                               "middleware": sorted(r["middleware"])}
                      for r in data["routes_static"] if r.get("source") in ("static", "framework", "filament")}
    snap["models"] = {fqn: {"table": m["table"], "relations": sorted(f"{x['type']} {x['name']} → {short(x['related'] or x.get('morph') or '?')}" for x in m["relations"]),
                            "fillable": sorted(m["fillable"]), "casts": m["casts"]} for fqn, m in data["models"].items()}
    snap["tables"] = {t: {c["name"]: col_sig(c) for c in d["columns"]} for t, d in data["schema"].items()}
    snap["migrations"] = [m["name"] for m in data["migrations"]]
    snap["classes"] = {c["fqn"]: {"role": c["role"], "file": c["file"]} for c in data["classes"]}
    snap["files"] = data.get("file_hashes", {})
    snap["env_example"] = sorted(data["env"]["example_keys"])
    snap["composer"] = {k: v["version"] for k, v in data["packages"]["locked"].items()} or dict(data["packages"]["require"], **data["packages"]["require_dev"])
    snap["npm"] = data["packages"]["npm_locked"] or dict(data["packages"]["npm"], **data["packages"]["npm_dev"])
    snap["docker"] = {"services": {s["name"]: {"image": s["image"], "build": (s["build"] or {}).get("file"),
                                               "ports": sorted(p["raw"] for p in s["ports"]), "command": s["command"]}
                                   for s in data["docker"]["services"]},
                      "dockerfiles": {f: sha1(read_text(os.path.join(data["meta"]["root"], f))) for f in data["docker"]["dockerfiles"]}}
    snap["schedule"] = sorted(f"{s['target']} — {s['frequency']}" for s in data["console"]["schedule"])
    snap["commands"] = sorted(c["name"] for c in data["console"]["commands"] + data["console"]["closure_commands"])
    snap["listeners"] = sorted(f"{short(w['event'])} → {short(w['listener'] or 'Closure')}" for w in data["async"]["wiring"])
    snap["livewire"] = sorted(c["alias"] for c in data["livewire"]["components"])
    snap["filament"] = sorted(f"{r['panel']}:{r['slug']}" for r in data["filament"]["resources"])
    snap["middleware_aliases"] = data["middleware"]["aliases"]
    snap["inertia_pages"] = sorted(data["inertia_pages"])
    snap["views"] = sorted(data["views"])
    return snap


def _dict_diff(old, new):
    old, new = old or {}, new or {}
    added = sorted(k for k in new if k not in old)
    removed = sorted(k for k in old if k not in new)
    changed = sorted(k for k in new if k in old and new[k] != old[k])
    return added, removed, changed


def _list_diff(old, new):
    o, n = set(old or []), set(new or [])
    return sorted(n - o), sorted(o - n)


def diff_snapshots(old, new):
    d = {}
    a, r, c = _dict_diff(old.get("routes"), new.get("routes"))
    d["routes"] = {"added": [{"key": k, **new["routes"][k]} for k in a], "removed": [{"key": k, **old["routes"][k]} for k in r],
                   "changed": [{"key": k, "old": old["routes"][k], "new": new["routes"][k]} for k in c]}
    a, r, c = _dict_diff(old.get("models"), new.get("models"))
    ch = []
    for k in c:
        o, n = old["models"][k], new["models"][k]
        ra, rr = _list_diff(o["relations"], n["relations"])
        fa, fr = _list_diff(o["fillable"], n["fillable"])
        ca, cr, cc = _dict_diff(o["casts"], n["casts"])
        ch.append({"model": k, "relations_added": ra, "relations_removed": rr, "fillable_added": fa, "fillable_removed": fr,
                   "casts_changed": ca + cr + cc, "table": (o["table"], n["table"]) if o["table"] != n["table"] else None})
    d["models"] = {"added": a, "removed": r, "changed": ch}
    a, r, c = _dict_diff(old.get("tables"), new.get("tables"))
    ch = []
    for k in c:
        ca, cr, cc = _dict_diff(old["tables"][k], new["tables"][k])
        ch.append({"table": k, "added": [f"{x} {new['tables'][k][x]}" for x in ca], "removed": cr,
                   "changed": [f"{x}: {old['tables'][k][x]} → {new['tables'][k][x]}" for x in cc]})
    d["tables"] = {"added": [{"table": k, "columns": list(new["tables"][k].keys())} for k in a], "removed": r, "changed": ch}
    ma, mr = _list_diff(old.get("migrations"), new.get("migrations"))
    d["migrations"] = {"added": ma, "removed": mr}
    a, r, c = _dict_diff(old.get("classes"), new.get("classes"))
    d["classes"] = {"added": [{"fqn": k, **new["classes"][k]} for k in a], "removed": [{"fqn": k, **old["classes"][k]} for k in r]}
    fa, fr, fc = _dict_diff(old.get("files"), new.get("files"))
    d["files"] = {"added": fa, "removed": fr, "changed": fc}
    ea, er = _list_diff(old.get("env_example"), new.get("env_example"))
    d["env"] = {"added": ea, "removed": er}
    for key in ("composer", "npm"):
        a, r, c = _dict_diff(old.get(key), new.get(key))
        d[key] = {"added": [{"name": k, "version": new[key][k]} for k in a], "removed": r,
                  "changed": [{"name": k, "old": old[key][k], "new": new[key][k]} for k in c]}
    od, nd = old.get("docker") or {}, new.get("docker") or {}
    a, r, c = _dict_diff(od.get("services"), nd.get("services"))
    d["docker"] = {"added": a, "removed": r, "changed": [{"service": k, "old": od["services"][k], "new": nd["services"][k]} for k in c]}
    da, dr, dc = _dict_diff(od.get("dockerfiles"), nd.get("dockerfiles"))
    d["dockerfiles"] = {"added": da, "removed": dr, "changed": dc}
    for key in ("schedule", "commands", "listeners", "livewire", "filament", "inertia_pages", "views"):
        a, r = _list_diff(old.get(key), new.get(key))
        d[key] = {"added": a, "removed": r}
    a, r, c = _dict_diff(old.get("middleware_aliases"), new.get("middleware_aliases"))
    d["middleware"] = {"added": a, "removed": r, "changed": c}
    d["total"] = sum(len(v.get("added", [])) + len(v.get("removed", [])) + len(v.get("changed", [])) for v in d.values() if isinstance(v, dict))
    return d


def extract_commit(root, sha):
    """git archive <sha> into a temp dir (only the source parts we analyse). Returns the dir or None."""
    try:
        p = subprocess.run(["git", "-C", root, "archive", "--format=tar", sha], capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    import io
    tmp = tempfile.mkdtemp(prefix="laravel-map-")
    keep = re.compile(r"^(app|routes|config|database|bootstrap|resources|tests|docker|\.docker|\.github|Modules|modules|src|domain)/|"
                      r"^(composer\.(json|lock)|package(-lock)?\.json|\.env\.example|Makefile|vite\.config\.\w+|webpack\.mix\.js|"
                      r"(docker-)?compose[\w.\-]*\.ya?ml|Dockerfile[\w.\-]*|phpunit\.xml(\.dist)?|artisan)$")
    with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
        members = []
        for m in tf.getmembers():
            name = m.name
            if name.startswith("/") or ".." in name.split("/") or not (m.isfile() or m.isdir()):
                continue
            if m.isfile() and (m.size > MAX_FILE_BYTES or not keep.search(name)):
                continue
            members.append(m)
        try:
            tf.extractall(tmp, members=members, filter="data")
        except TypeError:
            tf.extractall(tmp, members=members)
    return tmp


DATE_LIKE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|\bago\b|yesterday|today|\blast\s+\w+|"
                       r"\d+\s*\.?\s*(second|minute|hour|day|week|month|year)s?\b", re.I)


def resolve_since(root, since):
    """A ref, tag, branch, sha or date -> (sha, description) or (None, error)."""
    sha = git(root, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}")
    if sha:
        sha = sha.strip()
        rc, _, _ = run(["git", "-C", root, "merge-base", "--is-ancestor", sha, "HEAD"], timeout=30)
        if rc == 1:
            mb = git(root, "merge-base", sha, "HEAD")
            if mb and mb.strip():
                return mb.strip(), f"the point where this branch forked from “{since}”"
        return sha, f"“{since}”"
    if DATE_LIKE.search(since):
        sha = git(root, "rev-list", "-1", f"--before={since}", "HEAD")
        if sha and sha.strip():
            return sha.strip(), f"{since}"
        return None, f"No commit exists before “{since}”; nothing to compare with."
    return None, f"--since “{since}” is neither a git ref (branch, tag, sha) nor a date like 2026-09-01 or “3 weeks ago”. Showing changes since your previous map instead."


def git_activity(root, base_sha):
    if not is_git(root):
        return None
    rng = f"{base_sha}..HEAD" if base_sha else "HEAD"
    log = git(root, "log", rng, "--format=%h%x1f%an%x1f%aI%x1f%s%x1f%P", "-n", "2000", timeout=60) or ""
    commits = []
    for ln in log.splitlines():
        parts = ln.split("\x1f")
        if len(parts) == 5:
            commits.append({"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3],
                            "merge": len(parts[4].split()) > 1,
                            "prs": re.findall(r"(?:pull request #|\(#|!)(\d+)", parts[3])})
    files = []
    if base_sha:
        ns = git(root, "diff", "--name-status", "-M", base_sha, "HEAD", timeout=60) or ""
        num = git(root, "diff", "--numstat", "-M", base_sha, "HEAD", timeout=60) or ""
        stats = {}
        for ln in num.splitlines():
            p = ln.split("\t")
            if len(p) >= 3:
                stats[p[-1]] = (p[0], p[1])
        for ln in ns.splitlines():
            p = ln.split("\t")
            if len(p) >= 2:
                f = p[-1]
                plus, minus = stats.get(f, stats.get(next((k for k in stats if k.endswith(f)), ""), ("", "")))
                files.append({"status": p[0][0], "file": f, "old": p[1] if p[0].startswith("R") and len(p) > 2 else None,
                              "plus": plus, "minus": minus, "area": file_area(f)})
    return {"base": base_sha, "commits": commits, "authors": Counter(c["author"] for c in commits).most_common(),
            "files": files, "areas": Counter(f["area"] for f in files).most_common(),
            "prs": sorted({p for c in commits for p in c["prs"]}, key=lambda x: int(x))}


def catch_up(data):
    steps = []
    d = (data.get("changes") or {}).get("diff") or {}
    loc = data.get("local") or {}
    gi = data.get("git") or {}
    pre = data["prefixes"]
    act = (data.get("changes") or {}).get("git") or {}
    changed_files = [f["file"] for f in act.get("files", [])] + [f["file"] for f in gi.get("dirty", [])]
    if gi.get("behind"):
        steps.append({"title": "Pull the latest code", "command": "git pull", "why": f"Your branch is {gi['behind']} commit(s) behind {gi['upstream']}."})
    if gi.get("last_fetch"):
        try:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(gi["last_fetch"])).days
            if age >= 3:
                steps.append({"title": "Fetch from the remote", "command": "git fetch --all --prune",
                              "why": f"Last fetch was {age} days ago, so “behind/ahead” numbers may be stale."})
        except ValueError:
            pass
    dk = d.get("docker") or {}
    dfc = d.get("dockerfiles") or {}
    if dk.get("added") or dk.get("removed") or dk.get("changed") or dfc.get("changed") or dfc.get("added") or \
            any(file_area(f) == "Docker" for f in changed_files):
        why = []
        if dk.get("added"):
            why.append("new services: " + ", ".join(dk["added"]))
        if dk.get("changed"):
            why.append("changed services: " + ", ".join(x["service"] for x in dk["changed"]))
        if dfc.get("changed") or dfc.get("added"):
            why.append("Dockerfile changed: " + ", ".join(dfc.get("changed", []) + dfc.get("added", [])))
        if not why:
            why.append("Docker files changed")
        steps.append({"title": "Rebuild and restart the containers", "command": pre["build"] or pre["up"], "why": "; ".join(why) + "."})
    if (d.get("composer") or {}).get("added") or (d.get("composer") or {}).get("changed") or (d.get("composer") or {}).get("removed") \
            or loc.get("composer_out_of_sync") or (data["packages"]["require"] and not loc.get("vendor", True)):
        why = "composer.lock changed." if d.get("composer") and any(d["composer"].values()) else ""
        if loc.get("composer_out_of_sync"):
            why += f" {len(loc['composer_out_of_sync'])} installed package(s) differ from composer.lock."
        if not loc.get("vendor", True):
            why += " vendor/ is missing."
        steps.append({"title": "Install PHP dependencies", "command": f"{pre['composer']} install", "why": why.strip()})
    if data["packages"]["npm"] or data["packages"]["npm_dev"]:
        nd = d.get("npm") or {}
        if any(nd.get(k) for k in ("added", "removed", "changed")) or loc.get("npm_out_of_sync") or not loc.get("node_modules", True):
            why = "package-lock.json changed." if any(nd.get(k) for k in ("added", "removed", "changed")) else ""
            if loc.get("npm_out_of_sync"):
                why += f" {len(loc['npm_out_of_sync'])} installed package(s) differ from package-lock.json."
            if not loc.get("node_modules", True):
                why += " node_modules/ is missing."
            steps.append({"title": "Install JS dependencies", "command": f"{pre['npm']} install", "why": why.strip()})
    missing = loc.get("env_missing") or []
    new_env = (d.get("env") or {}).get("added") or []
    if not loc.get("env_exists", True):
        steps.append({"title": "Create your .env", "command": f"cp .env.example .env && {pre['artisan']} key:generate",
                      "why": "There is no .env file yet."})
    elif missing or new_env:
        keys = sorted(set(missing) | (set(new_env) & set(missing) if loc.get("env_exists") else set(new_env)))
        steps.append({"title": "Add new settings to your .env", "command": "", "keys": keys or new_env,
                      "why": "These keys are in .env.example but not in your .env" + (" (some were added recently)." if new_env else ".")})
    pend = [m["name"] for m in ((data.get("runtime") or {}).get("migrations") or []) if m["status"] == "Pending"]
    new_m = (d.get("migrations") or {}).get("added") or []
    if pend or new_m:
        steps.append({"title": "Run database migrations", "command": f"{pre['artisan']} migrate",
                      "why": (f"{len(pend)} pending migration(s) reported by artisan." if pend else f"{len(new_m)} new migration file(s) since the baseline."),
                      "items": pend or new_m})
    if (d.get("migrations") or {}).get("removed"):
        steps.append({"title": "Check removed migrations", "command": f"{pre['artisan']} migrate:status",
                      "why": "Migration files were deleted or renamed; your database may hold migrations the code no longer has.",
                      "items": d["migrations"]["removed"]})
    if any(file_area(f) in ("Config", "Routes", "Providers & bootstrap") for f in changed_files):
        steps.append({"title": "Clear cached config & routes", "command": f"{pre['artisan']} optimize:clear",
                      "why": "Config, routes or service providers changed; stale caches cause confusing bugs."})
    if any(file_area(f) in ("Jobs, events & listeners", "Mail & notifications") for f in changed_files) or (d.get("listeners") or {}).get("added"):
        cmd = f"{pre['artisan']} horizon:terminate" if data["packages"].get("horizon") else f"{pre['artisan']} queue:restart"
        steps.append({"title": "Restart queue workers", "command": cmd, "why": "Job/listener code changed; long-running workers still run the old code."})
    if any(file_area(f) == "Seeders & factories" for f in changed_files):
        steps.append({"title": "Consider re-seeding", "command": f"{pre['artisan']} migrate:fresh --seed",
                      "why": "Seeders or factories changed. This wipes your local database, so only do it if that is fine."})
    if any(file_area(f) in ("Frontend JS/CSS", "Blade views", "Livewire") for f in changed_files) and (data["packages"]["npm"] or data["packages"]["npm_dev"]):
        steps.append({"title": "Rebuild frontend assets", "command": f"{pre['npm']} run dev", "why": "Frontend files changed. Keep the dev server running while you work."})
    if any(file_area(f) == "Tests" for f in changed_files) or steps:
        steps.append({"title": "Run the test suite", "command": pre["test"], "why": "Confirms your environment works after the changes."})
    return steps


# =====================================================================================================
# 21. Insights
# =====================================================================================================

RAW_SQL_RE = re.compile(r"(DB::(?:raw|select|statement|unprepared|insert|update|delete)|->(?:whereRaw|orWhereRaw|selectRaw|orderByRaw|havingRaw|groupByRaw|fromRaw))\(\s*(\"[^\"]*\$|['\"][^'\"]*['\"]\s*\.\s*\$|\$)")
TODO_RE = re.compile(r"(?://|#|\*|<!--|\{\{--)\s*(TODO|FIXME|HACK|XXX|BUG)\b[:\s]*(.*)", re.I)


def build_insights(data, proj):
    items = []

    def add(sev, area, title, detail, rows=None, cols=None):
        items.append({"severity": sev, "area": area, "title": title, "detail": detail, "rows": rows or [], "cols": cols or []})

    idx = proj.idx
    routes = data["routes_static"]
    broken = []
    for r in routes:
        if r.get("action_type") != "controller" or not r.get("controller"):
            continue
        c = idx.get(r["controller"])
        if c is None:
            if r["controller"].startswith("App\\"):
                broken.append([f"{'|'.join(r['methods'])} {r['uri']}", r["action"], "controller class not found", f"{r['file']}:{r['line']}"])
        elif r.get("method") and not idx.has_method(c, r["method"]) and not idx.has_method(c, "__call"):
            broken.append([f"{'|'.join(r['methods'])} {r['uri']}", r["action"], f"method {r['method']}() not found", f"{r['file']}:{r['line']}"])
    if broken:
        add("crit", "Routes", f"{len(broken)} route(s) point at missing code", "These routes will throw an error when requested.",
            broken, ["Route", "Action", "Problem", "Defined at"])
    seen, dups = {}, []
    for r in routes:
        if r.get("source") not in ("static",):
            continue
        for m in r["methods"]:
            if m == "HEAD":
                continue
            k = (m, r["uri"], r.get("domain"))
            if k in seen:
                dups.append([f"{m} {r['uri']}", seen[k], f"{r['file']}:{r['line']}"])
            else:
                seen[k] = f"{r['file']}:{r['line']}"
    if dups:
        add("warn", "Routes", f"{len(dups)} duplicate route definition(s)", "The later definition wins; the earlier one is dead code.",
            dups, ["Route", "First defined", "Redefined"])
    names = Counter(r["name"] for r in routes if r.get("name") and r.get("source") == "static")
    dn = [[n, c] for n, c in names.items() if c > 1]
    if dn:
        add("warn", "Routes", f"{len(dn)} route name(s) used more than once", "route('name') will only ever generate one of them.", dn, ["Name", "Times"])
    open_routes = []
    for r in routes:
        if r.get("source") != "static" or not set(r["methods"]) & {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        mw = " ".join(r["middleware"])
        if re.search(r"\b(auth|can:|signed|guest|role|permission|admin|verified|password\.confirm)", mw):
            continue
        open_routes.append([f"{'|'.join(m for m in r['methods'] if m != 'HEAD')} {r['uri']}", r["action"], ", ".join(r["middleware"]) or "—"])
    if open_routes:
        add("info", "Security", f"{len(open_routes)} state-changing route(s) without auth middleware",
            "Not necessarily wrong (webhooks, contact forms, login), but worth a glance when reviewing changes.", open_routes,
            ["Route", "Action", "Middleware"])
    tables = data["schema"]
    if tables:
        no_table = [[m["name"], m["table"], m["file"]] for m in data["models"].values()
                    if not m["abstract"] and m["table"] not in tables and not m.get("connection")]
        if no_table:
            add("warn", "Database", f"{len(no_table)} model(s) without a matching migration", "The table may live in another database, a schema dump, or be missing.",
                no_table, ["Model", "Expected table", "File"])
        model_tables = {m["table"] for m in data["models"].values()}
        pivots = {r["pivot_table"] for m in data["models"].values() for r in m["relations"] if r.get("pivot_table")}
        for m in data["models"].values():
            for r in m["relations"]:
                if r["type"] == "belongsToMany" and not r.get("pivot_table") and r.get("related") in data["models"]:
                    a, b = sorted([snake(m["name"]), snake(short(r["related"]))])
                    pivots.add(f"{a}_{b}")
        orphans = [[t, len(d["columns"])] for t, d in tables.items()
                   if t not in model_tables and t not in FRAMEWORK_TABLES and not is_pivot(d, pivots)]
        if orphans:
            add("info", "Database", f"{len(orphans)} table(s) without a model", "Queried with the query builder, used by a package, or left over.",
                orphans, ["Table", "Columns"])
    bad_rel, missing_fk = [], []
    for m in data["models"].values():
        own = tables.get(m["table"])
        for r in m["relations"]:
            rel = r.get("related")
            if rel and rel not in data["models"] and rel.startswith("App\\") and not idx.get(rel):
                bad_rel.append([f"{m['name']}::{r['name']}()", r["type"], rel])
            if not own or not rel or rel not in data["models"]:
                continue
            other = tables.get(data["models"][rel]["table"])
            if r["type"] == "belongsTo":
                fk = r["keys"][0] if r["keys"] else snake(r["name"]) + "_id"
                if fk not in {c["name"] for c in own["columns"]}:
                    missing_fk.append([f"{m['name']}::{r['name']}()", f"{m['table']}.{fk}", "belongsTo"])
            elif r["type"] in ("hasMany", "hasOne") and other:
                fk = r["keys"][0] if r["keys"] else snake(m["name"]) + "_id"
                if fk not in {c["name"] for c in other["columns"]}:
                    missing_fk.append([f"{m['name']}::{r['name']}()", f"{other['name']}.{fk}", r["type"]])
    if bad_rel:
        add("crit", "Models", f"{len(bad_rel)} relationship(s) point at unknown classes", "Calling these relationships will fail.", bad_rel,
            ["Relationship", "Type", "Related class"])
    if missing_fk:
        add("warn", "Models", f"{len(missing_fk)} relationship(s) whose foreign-key column was not found",
            "Based on Laravel's naming conventions and the migrations. A custom key may be set at runtime, or a migration may be missing.",
            missing_fk, ["Relationship", "Expected column", "Type"])
    unguarded = [[m["name"], m["file"]] for m in data["models"].values() if m["guarded"] == []]
    if unguarded:
        add("info", "Models", f"{len(unguarded)} model(s) are fully unguarded ($guarded = [])", "Any attribute can be mass-assigned; make sure input is validated.",
            unguarded, ["Model", "File"])
    eoc = data["config"]["env_outside_config"]
    if eoc:
        add("warn", "Config", f"env() is called outside config/ ({len(eoc)}×)",
            "After `php artisan config:cache` these calls return null. Read the value through config() instead.",
            [[e["key"], f"{e['file']}:{e['line']}"] for e in eoc], ["Key", "Where"])
    undocumented = [[r["key"], ", ".join(r["config"][:3])] for r in data["env"]["matrix"]
                    if r["config"] and not r["in_example"] and not r["defaults"]
                    and not r["key"].startswith(("AWS_", "PUSHER_", "POSTMARK_", "RESEND_", "SLACK_", "MAILGUN_", "SES_", "LOG_PAPERTRAIL", "PAPERTRAIL_", "MEMCACHED_", "DYNAMODB_", "SQS_", "REDIS_QUEUE", "DB_URL", "DATABASE_URL", "REDIS_URL", "MAIL_URL", "DB_SOCKET", "MAIL_EHLO", "MYSQL_ATTR", "LOG_SLACK", "IRON_", "ABLY_", "SPARKPOST_"))]
    if undocumented and proj.env_example:
        add("info", "Config", f"{len(undocumented)} env var(s) read by config, with no default and not in .env.example",
            "New developers won't know these exist, and the config value will be null until someone sets them.", undocumented, ["Key", "Config"])
    js_text = " ".join(read_text(ap) for ap, _ in walk(proj.root, "resources", exts=(".js", ".ts", ".vue", ".jsx", ".tsx")))[:3_000_000]
    unused = [[r["key"]] for r in data["env"]["matrix"] if r["in_example"] and not r["config"] and not r["code"] and not r["compose"]
              and not (r["key"].startswith(("VITE_", "MIX_")) and r["key"] in js_text)
              and r["key"] not in ("APP_MAINTENANCE_DRIVER", "APP_MAINTENANCE_STORE", "PHP_CLI_SERVER_WORKERS", "BCRYPT_ROUNDS", "WWWUSER", "WWWGROUP", "SAIL_XDEBUG_MODE")]
    if unused:
        add("info", "Config", f"{len(unused)} .env.example key(s) not referenced by config/, code or compose",
            "Possibly read by a package directly, or left over.", unused, ["Key"])
    a = data["async"]
    lonely = [[short(e), e] for e, d in a["events"].items() if not d["listeners"] and not d.get("broadcast")]
    if lonely:
        add("info", "Events", f"{len(lonely)} event(s) with no listener found", "Fired into the void, or listened to in a way this tool can't see.", lonely, ["Event", "Class"])
    deaf = [[short(l), ", ".join(short(x) for x in d["handles"]) or "?"] for l, d in a["listeners"].items() if not d["events"]]
    if deaf:
        add("warn", "Events", f"{len(deaf)} listener(s) not wired to any event", "Check event discovery or $listen.", deaf, ["Listener", "Handles"])
    scheduled = {s["target"] for s in data["console"]["schedule"]}
    idle = [[short(j)] for j, d in a["jobs"].items() if not d.get("dispatched_by") and short(j) not in scheduled]
    if idle:
        add("info", "Jobs", f"{len(idle)} job(s) never dispatched in app code", "Maybe dispatched from tests, tinker or a package.", idle, ["Job"])
    routed = {r["controller"] for r in data["routes"] if r.get("controller")}
    unrouted = [[c["name"], c["file"]] for c in data["classes"] if c["role"] == "controller" and not c["abstract"]
                and c["fqn"] not in routed and c["name"] != "Controller" and c["public"]]
    if unrouted:
        add("info", "HTTP", f"{len(unrouted)} controller(s) not referenced by any route", "Dead code, or routed in a way this tool can't see.", unrouted, ["Controller", "File"])
    lw_unused = [[c["alias"], c["file"]] for c in data["livewire"]["components"] if not c["routes"] and not c["used_in"] and not c.get("abstract")
                 and not any(c["alias"].endswith(x) for x in ("navigation",))]
    if lw_unused:
        add("info", "Livewire", f"{len(lw_unused)} Livewire component(s) not used in a route or view", "Possibly embedded dynamically.", lw_unused, ["Component", "File"])
    pages = data["inertia_pages"]
    renders = [r for r in data["renders"] if r["kind"] == "inertia"]
    missing_pages = [[r["name"], f"{short(r['by'])}::{r['method']}", f"{r['file']}:{r['line']}"] for r in renders if r["name"] not in pages]
    if missing_pages and pages:
        add("crit", "Frontend", f"{len(missing_pages)} Inertia page(s) rendered but not found", "The browser will show a blank page or a JS error.",
            missing_pages, ["Page", "Rendered by", "Where"])
    views = data["views"]
    vrefs = []
    for r in data["renders"]:
        if r["kind"] == "view" and "::" not in r["name"] and r["name"] not in views:
            vrefs.append([r["name"], f"{short(r['by'])}::{r['method']}"])
    for r in data["routes_static"]:
        if r.get("view") and r["view"] not in views:
            vrefs.append([r["view"], f"Route {r['uri']}"])
    for v in views.values():
        for inc in ([v["extends"]] if v["extends"] else []) + v["includes"]:
            if "::" not in inc and inc not in views and not inc.startswith("$"):
                vrefs.append([inc, f"view {v['name']}"])
    if vrefs and views:
        add("warn", "Frontend", f"{len(vrefs)} reference(s) to Blade views that don't exist", "Could also be a package view or a dynamic name.", vrefs, ["View", "Referenced from"])
    unesc = [[v["name"], u["line"], u["expr"]] for v in views.values() for u in v["unescaped"]]
    if unesc:
        add("info", "Security", f"{len(unesc)} unescaped Blade output(s) {{!! !!}}", "Fine for trusted HTML; an XSS risk if the value contains user input.",
            unesc, ["View", "Line", "Expression"])
    raw = []
    for rel, pf in proj.php.items():
        if rel.startswith(("tests/", "database/migrations/")):
            continue
        for i, ln in enumerate(pf.text.splitlines(), 1):
            if RAW_SQL_RE.search(ln):
                raw.append([f"{rel}:{i}", ln.strip()[:120]])
    if raw:
        add("warn", "Security", f"{len(raw)} raw SQL call(s) built with variables", "Use bindings (`whereRaw('x = ?', [$v])`) to avoid SQL injection.", raw, ["Where", "Code"])
    big = sorted(([c["name"], c["role"], c["loc"], c["methods"], c["file"]] for c in data["classes"] if c["loc"] > 400 and c["role"] not in ("test", "migration")),
                 key=lambda x: -x[2])
    if big:
        add("info", "Complexity", f"{len(big)} large class(es) (400+ lines)", "Hotspots that are hard to change safely.", big, ["Class", "Role", "Lines", "Methods", "File"])
    longm = [[f"{c['name']}::{m['name']}()", m["lines"], c["file"]] for c in data["classes"] for m in c["long_methods"] if c["role"] != "test"]
    if longm:
        add("info", "Complexity", f"{len(longm)} long method(s) (80+ lines)", "Candidates for extraction into smaller pieces.", sorted(longm, key=lambda x: -x[1]),
            ["Method", "Lines", "File"])
    fat = [[c["name"], len(c["public"]), c["file"]] for c in data["classes"] if c["role"] == "controller" and len(c["public"]) > 10]
    if fat:
        add("info", "Complexity", f"{len(fat)} controller(s) with more than 10 actions", "Consider splitting by resource.", fat, ["Controller", "Public methods", "File"])
    dk = data["docker"]
    latest = [[s["name"], s["image"]] for s in dk["services"] if s.get("image") and s.get("tag") == "latest"]
    if latest:
        add("info", "Docker", f"{len(latest)} image(s) use the `latest` tag", "Teammates may silently run different versions. Pin a version.", latest, ["Service", "Image"])
    nohc = [[s["name"], s["image"] or "(build)"] for s in dk["services"] if s["role"] == "database" and not s["healthcheck"]]
    if nohc:
        add("info", "Docker", "Database service without a healthcheck", "The app may start before the database accepts connections.", nohc, ["Service", "Image"])
    if any(d and d.get("xdebug") for d in dk["dockerfiles"].values()) or dk["php_ini"].get("xdebug.mode"):
        add("info", "Docker", "Xdebug is installed in the dev image", f"xdebug.mode = {dk['php_ini'].get('xdebug.mode', 'see Dockerfile / env (SAIL_XDEBUG_MODE)')}. It slows every request when enabled.")
    t = data["tooling"]["tests"]
    app_classes = sum(1 for c in data["classes"] if c["role"] not in ("test", "migration", "factory", "seeder"))
    if t["cases"] == 0:
        add("warn", "Tests", "No tests found", "Changes can't be verified automatically.")
    elif app_classes and t["cases"] / app_classes < 0.3:
        add("info", "Tests", f"{t['cases']} test case(s) for {app_classes} application classes", "Coverage is probably thin. Lean on manual checks when changing things.")
    pend = [[m["name"]] for m in ((data.get("runtime") or {}).get("migrations") or []) if m["status"] == "Pending"]
    if pend:
        add("warn", "Database", f"{len(pend)} pending migration(s) on your local database", f"Run `{data['prefixes']['artisan']} migrate`.", pend, ["Migration"])
    unused = (data.get("calls") or {}).get("unused") or []
    if unused:
        add("info", "Complexity", f"{len(unused)} public method(s) that nothing calls",
            "No call to them was found in PHP, Blade or JS. Check before deleting: framework hooks, reflection and string-based calls are invisible here.",
            unused, ["Method", "Role", "Defined at"])
    todos = []
    for sub in ("app", "routes", "config", "database", "resources", "tests", "bootstrap", "src", "Modules"):
        for ap, rel in walk(proj.root, sub, exts=(".php", ".js", ".ts", ".vue", ".jsx", ".tsx", ".css", ".scss")):
            text = read_text(ap)
            if not re.search(r"TODO|FIXME|HACK|XXX|BUG", text):
                continue
            for i, ln in enumerate(text.splitlines(), 1):
                m = TODO_RE.search(ln)
                if m:
                    todos.append([m.group(1).upper(), m.group(2).strip()[:140], f"{rel}:{i}"])
    if todos:
        add("info", "Notes", f"{len(todos)} TODO / FIXME comment(s)", "Left by developers: often the best map of known problems.", todos, ["Tag", "Comment", "Where"])
    order = {"crit": 0, "warn": 1, "info": 2}
    items.sort(key=lambda x: (order[x["severity"]], x["area"]))
    return items


# =====================================================================================================
# 22. Assembling everything
# =====================================================================================================

def detect_stack(proj, assets, livewire, filament, docker, routes, tooling):
    env = {**proj.env_example}
    s = {"laravel": proj.laravel_version(), "laravel_major": proj.laravel_major(), "php": proj.require().get("php", ""),
         "php_runtime": next((x["php_version"] for x in docker["services"] if x["name"] == docker.get("app_service") and x.get("php_version")), None),
         "frontend": [], "auth": [], "db": env.get("DB_CONNECTION"), "cache": env.get("CACHE_STORE") or env.get("CACHE_DRIVER"),
         "queue": env.get("QUEUE_CONNECTION"), "session": env.get("SESSION_DRIVER"), "mail": env.get("MAIL_MAILER"),
         "broadcast": env.get("BROADCAST_CONNECTION") or env.get("BROADCAST_DRIVER"), "search": env.get("SCOUT_DRIVER"),
         "filesystem": env.get("FILESYSTEM_DISK") or env.get("FILESYSTEM_DRIVER"),
         "testing": "Pest" if tooling["tests"]["pest"] else "PHPUnit", "bundler": assets["bundler"], "css": assets["css"],
         "docker": "Laravel Sail" if docker.get("sail") else ("docker compose" if docker.get("services") else None),
         "structure": "Laravel 11+ slim skeleton (bootstrap/app.php)" if proj.exists("bootstrap", "providers.php") or
         "withRouting" in (proj.php.get("bootstrap/app.php").text if proj.php.get("bootstrap/app.php") else "") else
         "Classic structure (Http/Kernel.php, RouteServiceProvider)", "api": any(r.get("group") == "api" or r["uri"].startswith("/api") for r in routes)}
    if assets.get("spa"):
        s["frontend"].append(assets["spa"])
    if livewire["components"] or proj.has_pkg("livewire/livewire"):
        v = str(livewire.get("version") or "")
        s["frontend"].append("Livewire " + (re.search(r"\d+", v).group(0) if re.search(r"\d+", v) else ""))
    if proj.has_pkg("livewire/volt"):
        s["frontend"].append("Volt")
    if filament["panels"] or filament["resources"]:
        v = str(filament.get("version") or "")
        s["frontend"].append("Filament " + (re.search(r"\d+", v).group(0) if re.search(r"\d+", v) else "") + " admin")
    if proj.has_npm("alpinejs"):
        s["frontend"].append("Alpine.js")
    if not s["frontend"]:
        s["frontend"].append("Blade")
    elif not assets.get("spa"):
        s["frontend"].insert(0, "Blade")
    for pkg, label in (("laravel/sanctum", "Sanctum"), ("laravel/passport", "Passport"), ("laravel/fortify", "Fortify"),
                       ("laravel/jetstream", "Jetstream"), ("laravel/breeze", "Breeze"), ("laravel/ui", "laravel/ui"),
                       ("laravel/socialite", "Socialite"), ("spatie/laravel-permission", "spatie/permission"),
                       ("tymon/jwt-auth", "JWT"), ("php-open-source-saver/jwt-auth", "JWT")):
        if proj.has_pkg(pkg):
            s["auth"].append(label)
    s["frontend"] = [x.strip() for x in s["frontend"]]
    return s


def analyze(root, light=False, artisan=None, want_db=False):
    t0 = dt.datetime.now()
    proj = Project(root)
    rp, routes = parse_routes(proj)
    models = analyze_models(proj)
    sb = SchemaBuilder(proj).run()
    sb.resolve_model_fks(models)
    asyncd = analyze_async(proj, models)
    console = analyze_console(proj, rp)
    views = analyze_views(proj)
    renders = view_renders(proj)
    pages = inertia_pages(proj)
    for r in renders:
        if r["kind"] == "inertia" and r["name"] in pages:
            pages[r["name"]]["rendered_by"].append(f"{short(r['by'])}::{r['method']}")
        if r["kind"] == "view" and r["name"] in views:
            views[r["name"]]["used_by"].append(f"{short(r['by'])}::{r['method']}")
    for r in routes:
        if r.get("view") in views:
            views[r["view"]]["used_by"].append(f"route {r['uri']}")
    livewire = analyze_livewire(proj, views, routes)
    filament = analyze_filament(proj, models)
    assets = analyze_assets(proj)
    docker = analyze_docker(proj)
    prefixes = command_prefixes(docker, proj)
    config = analyze_config(proj)
    matrix = env_matrix(proj, config, docker)
    middleware = analyze_middleware(proj)
    tooling = analyze_tooling(proj)
    classes = class_records(proj)
    routes_static = routes + filament["routes"]
    pkg_routes = package_routes(proj, routes_static)
    stack = detect_stack(proj, assets, livewire, filament, docker, routes, tooling)
    hashes = {rel: sha1(pf.text) for rel, pf in proj.php.items()}
    for v in views.values():
        hashes[v["file"]] = sha1(read_text(proj.p(v["file"])))
    for pg in pages.values():
        hashes[pg["file"]] = sha1(read_text(proj.p(pg["file"])))
    data = {
        "meta": {"name": proj.name(), "description": proj.composer.get("description") or "", "root": proj.root,
                 "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), "version": VERSION,
                 "composer_name": proj.composer.get("name") or "", "php_files": len(proj.php)},
        "stack": stack, "routes": routes_static + pkg_routes, "routes_static": routes_static, "route_registration": rp.registration,
        "models": models, "schema": sb.to_dict(), "migrations": sb.migrations, "async": asyncd, "console": console,
        "views": views, "renders": renders, "inertia_pages": pages, "livewire": livewire, "filament": filament,
        "assets": assets, "docker": docker, "prefixes": prefixes, "config": config,
        "env": {"matrix": matrix, "example_keys": list(proj.env_example), "env_exists": proj.exists(".env")},
        "middleware": middleware, "tooling": tooling, "classes": classes, "notes": proj.notes, "file_hashes": hashes,
        "packages": {"require": proj.require(), "require_dev": proj.require_dev(), "locked": proj.locked_versions(),
                     "npm": proj.pkg.get("dependencies") or {}, "npm_dev": proj.pkg.get("devDependencies") or {},
                     "npm_locked": proj.npm_locked(), "horizon": proj.has_pkg("laravel/horizon")},
    }
    if light:
        data["http"] = {"controllers": [], "requests": [], "resources": [], "policies": []}
        return data, proj
    data["git"] = git_info(proj.root)
    data["local"] = local_status(proj, docker, prefixes)
    prefix = detect_artisan(proj, docker, artisan)
    if artisan and not prefix:
        proj.notes.append("--artisan was given but no running app container or local PHP install was found; live data was skipped.")
    data["runtime"] = runtime_data(proj, prefix, want_db, models) if prefix else None
    rt = data["runtime"]
    if rt and rt.get("routes"):
        static_idx = {(tuple(m for m in r["methods"] if m != "HEAD"), r["uri"]): r for r in routes_static}
        merged = []
        for r in rt["routes"]:
            s = static_idx.get((tuple(m for m in r["methods"] if m != "HEAD"), r["uri"]))
            if s:
                r.update({"file": s["file"], "line": s["line"], "group": s["group"], "action_type": s["action_type"] if r["action_type"] != "closure" else "closure"})
            elif r["uri"].startswith(tuple(f"/{p['path']}" for p in filament["panels"] if p.get("path"))) or "filament" in (r.get("name") or ""):
                r["group"], r["action_type"] = "filament", "filament"
            else:
                r["group"] = r["group"] or ("package" if not (r.get("controller") or "").startswith("App\\") and r["action"] != "Closure" else "")
            merged.append(r)
        data["routes"] = merged
    if rt and rt.get("models"):
        for fqn, info in rt["models"].items():
            tbl = info.get("table") or models.get(fqn, {}).get("table")
            if not tbl:
                continue
            cols = [{"name": a.get("name"), "type": str(a.get("type") or "").split("(")[0], "detail": "", "nullable": bool(a.get("nullable")),
                     "default": a.get("default"), "unique": bool(a.get("unique")), "index": False, "primary": bool(a.get("increments")),
                     "unsigned": False, "auto": bool(a.get("increments")), "comment": None, "fk": None, "source": "database"}
                    for a in info.get("attributes", []) if not a.get("appended")]
            old = data["schema"].get(tbl, {"name": tbl, "fks": [], "indexes": [], "created_in": None, "altered_in": [], "primary": None, "polymorphic": []})
            fkmap = {c["name"]: c.get("fk") for c in old.get("columns", [])}
            for c in cols:
                c["fk"] = fkmap.get(c["name"])
            data["schema"][tbl] = {**old, "columns": cols, "source": "database (artisan model:show)"}
    data["http"] = analyze_http(proj, data)
    try:
        data["calls"] = build_call_graph(proj, data)
    except Exception as ex:  # noqa: BLE001 - the rest of the map is still useful without traces
        import traceback
        traceback.print_exc()
        proj.notes.append(f"The call graph could not be built ({ex.__class__.__name__}: {ex}); request traces are unavailable.")
        data["calls"] = None
    data["insights"] = build_insights(data, proj)
    data["meta"]["seconds"] = round((dt.datetime.now() - t0).total_seconds(), 2)
    return data, proj


# =====================================================================================================
# 23. HTML: design tokens, layout, shared JS
# =====================================================================================================

MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
D3_URL = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"
FONTS_URL = "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Space+Grotesk:wght@500;600;700&display=swap"

CSS = r"""
/* Layout: a survey-atlas feel. Fixed index of sheets on the left, wide sheet on the right, ink-blue accent,
   colour-coded legend for class roles (the map key), monospace for anything you could paste into a terminal. */
:root {
  --bg: #f5f6f8; --surface: #ffffff; --surface-2: #eef0f4; --line: #dadfe7; --line-2: #c8cfda;
  --fg: #17202c; --muted: #566273; --faint: #8b95a4;
  --accent: #2a4fc9; --accent-soft: #e6ebfa; --accent-ink: #ffffff;
  --ok: #17784a; --ok-bg: #e2f3ea; --warn: #995600; --warn-bg: #fcefd9; --crit: #b3261e; --crit-bg: #fbe7e5;
  --info: #2a5db0; --info-bg: #e7eefa; --code-bg: #eef1f6; --shadow: 0 1px 2px rgba(20,30,50,.06), 0 2px 8px rgba(20,30,50,.05);
  --m-get: #17784a; --m-post: #2a5db0; --m-put: #995600; --m-patch: #8a5a00; --m-delete: #b3261e; --m-any: #6a4bb8;
  --role-model: #2f5fd0; --role-controller: #0f8a7e; --role-middleware: #7a4fd6; --role-request: #0e7fa5; --role-resource: #4b55c9;
  --role-livewire: #c2387a; --role-filament: #b86e00; --role-job: #c4561b; --role-event: #c0322b; --role-listener: #a8325e;
  --role-mail: #8a3fbf; --role-notification: #8a3fbf; --role-observer: #5b8a1f; --role-policy: #4f7d16; --role-command: #4e5d6e;
  --role-provider: #7a6a55; --role-component: #b13fae; --role-enum: #2a7fb8; --role-rule: #2a7fb8; --role-cast: #2a7fb8;
  --role-scope: #2a7fb8; --role-data: #2a7fb8; --role-action: #23853f; --role-service: #23853f; --role-repository: #23853f;
  --role-exception: #a33a3a; --role-factory: #8c6d1f; --role-seeder: #8c6d1f; --role-migration: #8c6d1f; --role-test: #6b6f76;
  --role-trait: #8b93a1; --role-interface: #8b93a1; --role-other: #8b93a1;
  --role-view: #2f5fd0; --role-layout: #7a6a55; --role-email: #8a3fbf; --role-volt: #c2387a; --role-page: #0f8a7e;
  --role-partial: #8b93a1; --role-external: #8b93a1;
  --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-head: "Space Grotesk", "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --step--1: .8125rem; --step-0: .9375rem; --step-1: 1.125rem; --step-2: 1.375rem; --step-3: 1.875rem; --step-4: 2.5rem;
  --radius: 8px;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f131a; --surface: #161b24; --surface-2: #1d2430; --line: #2a3240; --line-2: #384254;
  --fg: #e5e9f0; --muted: #a3adbd; --faint: #737e90;
  --accent: #8ea8ff; --accent-soft: #1f2a48; --accent-ink: #0f131a;
  --ok: #5fd39a; --ok-bg: #14301f; --warn: #f0b25a; --warn-bg: #33250f; --crit: #ff8f86; --crit-bg: #3a1714;
  --info: #8db4ff; --info-bg: #17243d; --code-bg: #1b2230; --shadow: 0 1px 2px rgba(0,0,0,.4);
  --m-get: #5fd39a; --m-post: #8db4ff; --m-put: #f0b25a; --m-patch: #e9a948; --m-delete: #ff8f86; --m-any: #c2a8ff;
  --role-model: #7ea2ff; --role-controller: #4fd1c0; --role-middleware: #b69cff; --role-request: #5cc8ef; --role-resource: #9aa2ff;
  --role-livewire: #f28cbc; --role-filament: #f2b35a; --role-job: #f59a6a; --role-event: #ff8a80; --role-listener: #f58fb3;
  --role-mail: #cf9cf5; --role-notification: #cf9cf5; --role-observer: #a6d96a; --role-policy: #9ccf5e; --role-command: #a9b6c6;
  --role-provider: #c9b79b; --role-component: #ea8fe6; --role-enum: #7cc2f0; --role-rule: #7cc2f0; --role-cast: #7cc2f0;
  --role-scope: #7cc2f0; --role-data: #7cc2f0; --role-action: #6fd38c; --role-service: #6fd38c; --role-repository: #6fd38c;
  --role-exception: #f08080; --role-factory: #d9b45a; --role-seeder: #d9b45a; --role-migration: #d9b45a; --role-test: #a4a9b1;
  --role-trait: #7b8494; --role-interface: #7b8494; --role-other: #7b8494;
  --role-view: #7ea2ff; --role-layout: #c9b79b; --role-email: #cf9cf5; --role-volt: #f28cbc; --role-page: #4fd1c0;
  --role-partial: #7b8494; --role-external: #7b8494;
  color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0f131a; --surface: #161b24; --surface-2: #1d2430; --line: #2a3240; --line-2: #384254;
  --fg: #e5e9f0; --muted: #a3adbd; --faint: #737e90;
  --accent: #8ea8ff; --accent-soft: #1f2a48; --accent-ink: #0f131a;
  --ok: #5fd39a; --ok-bg: #14301f; --warn: #f0b25a; --warn-bg: #33250f; --crit: #ff8f86; --crit-bg: #3a1714;
  --info: #8db4ff; --info-bg: #17243d; --code-bg: #1b2230; --shadow: 0 1px 2px rgba(0,0,0,.4);
  --m-get: #5fd39a; --m-post: #8db4ff; --m-put: #f0b25a; --m-patch: #e9a948; --m-delete: #ff8f86; --m-any: #c2a8ff;
  --role-model: #7ea2ff; --role-controller: #4fd1c0; --role-middleware: #b69cff; --role-request: #5cc8ef; --role-resource: #9aa2ff;
  --role-livewire: #f28cbc; --role-filament: #f2b35a; --role-job: #f59a6a; --role-event: #ff8a80; --role-listener: #f58fb3;
  --role-mail: #cf9cf5; --role-notification: #cf9cf5; --role-observer: #a6d96a; --role-policy: #9ccf5e; --role-command: #a9b6c6;
  --role-provider: #c9b79b; --role-component: #ea8fe6; --role-enum: #7cc2f0; --role-rule: #7cc2f0; --role-cast: #7cc2f0;
  --role-scope: #7cc2f0; --role-data: #7cc2f0; --role-action: #6fd38c; --role-service: #6fd38c; --role-repository: #6fd38c;
  --role-exception: #f08080; --role-factory: #d9b45a; --role-seeder: #d9b45a; --role-migration: #d9b45a; --role-test: #a4a9b1;
  --role-trait: #7b8494; --role-interface: #7b8494; --role-other: #7b8494;
  --role-view: #7ea2ff; --role-layout: #c9b79b; --role-email: #cf9cf5; --role-volt: #f28cbc; --role-page: #4fd1c0;
  --role-partial: #7b8494; --role-external: #7b8494;
  color-scheme: dark; }

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 400 var(--step-0)/1.55 var(--font-body); }
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
a:hover { text-decoration-thickness: 2px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
code, kbd, .mono { font-family: var(--font-mono); font-size: .86em; }
code { background: var(--code-bg); padding: .1em .35em; border-radius: 4px; overflow-wrap: anywhere; }
h1, h2, h3, h4 { font-family: var(--font-head); line-height: 1.2; text-wrap: balance; margin: 0; letter-spacing: -.01em; }
h1 { font-size: var(--step-4); font-weight: 700; }
h2 { font-size: var(--step-2); font-weight: 600; }
h3 { font-size: var(--step-1); font-weight: 600; }
h4 { font-size: var(--step-0); font-weight: 600; }
p { margin: 0; max-width: 72ch; overflow-wrap: anywhere; }
li, dd, summary { overflow-wrap: anywhere; }
td { overflow-wrap: break-word; }
td .sub-list > span { overflow-wrap: normal; }
ul, ol { margin: 0; padding-left: 1.25rem; }
small, .small { font-size: var(--step--1); }
.muted { color: var(--muted); }
.faint { color: var(--faint); }
.nowrap { white-space: nowrap; }
.num { font-variant-numeric: tabular-nums; }

.shell { display: grid; grid-template-columns: 252px minmax(0, 1fr); min-height: 100vh; }
.side { position: sticky; top: 0; height: 100vh; overflow-y: auto; background: var(--surface); border-right: 1px solid var(--line);
        padding: 22px 14px 18px; display: flex; flex-direction: column; gap: 18px; }
.brand { display: grid; gap: 2px; padding: 0 8px; }
.brand .eyebrow { font: 600 .6875rem/1 var(--font-mono); letter-spacing: .12em; text-transform: uppercase; color: var(--faint); }
.brand .name { font: 700 1.125rem/1.25 var(--font-head); color: var(--fg); text-decoration: none; overflow-wrap: anywhere; }
.nav { display: grid; gap: 14px; }
.nav-group { display: grid; gap: 1px; }
.nav-label { font: 600 .6875rem/1 var(--font-mono); letter-spacing: .1em; text-transform: uppercase; color: var(--faint); padding: 0 8px 6px; }
.nav a { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; padding: 6px 8px; border-radius: 6px;
         color: var(--muted); text-decoration: none; font-weight: 500; }
.nav a:hover { background: var(--surface-2); color: var(--fg); }
.nav a[aria-current="page"] { background: var(--accent-soft); color: var(--accent); }
.nav a .count { font: 500 .75rem/1 var(--font-mono); color: var(--faint); font-variant-numeric: tabular-nums; }
.side-foot { margin-top: auto; display: grid; gap: 8px; padding: 12px 8px 0; border-top: 1px solid var(--line); font-size: var(--step--1); color: var(--faint); }
.theme-btn { justify-self: start; font: 500 var(--step--1)/1 var(--font-body); color: var(--muted); background: var(--surface-2);
             border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; cursor: pointer; }
.theme-btn:hover { color: var(--fg); border-color: var(--line-2); }

main { min-width: 0; }
.wrap { max-width: 1240px; padding-block: 34px 96px; padding-left: max(16px, env(safe-area-inset-left, 0px));
        padding-right: max(16px, env(safe-area-inset-right, 0px)); display: grid; gap: 40px; }
@media (min-width: 861px) { .wrap { padding-left: 40px; padding-right: 40px; } }
.wrap, .sec, .sec-head, .sub, .card, .page-head, .prose, details.box > .body, .insight > .body, .steps .step-body { grid-template-columns: minmax(0, 1fr); }
.wrap > *, .sec > *, .sub > *, .card > * { min-width: 0; }
.page-head { display: grid; gap: 10px; padding-bottom: 22px; border-bottom: 1px solid var(--line); }
.crumb { font: 500 .75rem/1 var(--font-mono); letter-spacing: .08em; text-transform: uppercase; color: var(--faint); }
.lede { font-size: var(--step-1); color: var(--muted); max-width: 70ch; }
.sec { display: grid; gap: 16px; scroll-margin-top: 80px; }
.sec-head { display: grid; gap: 6px; }
.sec-head p { color: var(--muted); }
.sub { display: grid; gap: 12px; }

.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px;
        display: grid; gap: 4px; text-decoration: none; color: inherit; }
a.tile:hover { border-color: var(--accent); }
.tile .v { font: 600 var(--step-3)/1 var(--font-head); font-variant-numeric: tabular-nums; color: var(--fg); }
.tile .k { font-size: var(--step--1); color: var(--muted); }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px;
        display: grid; gap: 10px; align-content: start; min-width: 0; }
.card h3 { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.card-link { text-decoration: none; color: inherit; }
.card-link:hover { border-color: var(--accent); }
.card-link p { color: var(--muted); font-size: var(--step--1); }

.kv { display: grid; grid-template-columns: minmax(110px, max-content) minmax(0, 1fr); gap: 6px 16px; font-size: var(--step--1); }
.kv dt { color: var(--faint); }
.kv dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }

.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; font: 500 .75rem/1.2 var(--font-body); padding: 3px 9px; border-radius: 999px;
        background: var(--surface-2); color: var(--muted); border: 1px solid var(--line); white-space: nowrap; }
.chip::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--dot, var(--faint)); flex: none; }
.chip.plain::before { display: none; }
.badge { display: inline-block; font: 600 .6875rem/1.4 var(--font-mono); padding: 1px 6px; border-radius: 4px; letter-spacing: .02em;
         background: var(--surface-2); color: var(--muted); border: 1px solid var(--line); white-space: nowrap; }
.badge.ok { background: var(--ok-bg); color: var(--ok); border-color: transparent; }
.badge.warn { background: var(--warn-bg); color: var(--warn); border-color: transparent; }
.badge.crit { background: var(--crit-bg); color: var(--crit); border-color: transparent; }
.badge.info { background: var(--info-bg); color: var(--info); border-color: transparent; }
.m { display: inline-block; font: 600 .6875rem/1.5 var(--font-mono); padding: 0 6px; border-radius: 4px; margin-right: 3px;
     color: var(--mc, var(--muted)); border: 1px solid currentColor; white-space: nowrap; }
.m-GET { --mc: var(--m-get); } .m-POST { --mc: var(--m-post); } .m-PUT { --mc: var(--m-put); } .m-PATCH { --mc: var(--m-patch); }
.m-DELETE { --mc: var(--m-delete); } .m-ANY, .m-OPTIONS { --mc: var(--m-any); }

.callout { border: 1px solid var(--line); border-left: 4px solid var(--cc, var(--info)); background: var(--surface); border-radius: var(--radius);
           padding: 12px 16px; display: grid; gap: 6px; }
.callout.ok { --cc: var(--ok); } .callout.warn { --cc: var(--warn); } .callout.crit { --cc: var(--crit); } .callout.info { --cc: var(--info); }
.callout p { color: var(--muted); }

.tbl-tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.tbl-tools input[type="search"] { flex: 1 1 220px; min-width: 0; max-width: 420px; font: inherit; padding: 8px 12px; border-radius: 6px;
           border: 1px solid var(--line-2); background: var(--surface); color: var(--fg); }
.tbl-tools .count { font: 500 var(--step--1)/1 var(--font-mono); color: var(--faint); }
.qf { font: 500 .75rem/1 var(--font-mono); padding: 6px 10px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface);
      color: var(--muted); cursor: pointer; }
.qf:hover, .qf[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); max-width: 100%; }
table.data { border-collapse: collapse; width: 100%; font-size: var(--step--1); }
table.data th, table.data td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
table.data tr:last-child td { border-bottom: 0; }
table.data th { font: 600 .6875rem/1.3 var(--font-mono); letter-spacing: .06em; text-transform: uppercase; color: var(--faint);
                background: var(--surface-2); white-space: nowrap; position: relative; }
table.data th[data-sort] { cursor: pointer; user-select: none; }
table.data th[data-sort]:hover { color: var(--fg); }
table.data th[aria-sort="ascending"]::after { content: " ↑"; } table.data th[aria-sort="descending"]::after { content: " ↓"; }
table.data td.mono, table.data td .mono { font-family: var(--font-mono); font-size: .78rem; }
table.data tbody tr:hover { background: color-mix(in srgb, var(--accent-soft) 45%, transparent); }
.sub-list { display: flex; flex-wrap: wrap; gap: 4px 14px; min-width: 0; }
.sub-list > span { overflow-wrap: anywhere; min-width: 0; }
.sub-list.mono { font-family: var(--font-mono); font-size: .8125rem; }
td .sub-list { display: grid; gap: 2px; }
td .sub-list.mono { font-size: .75rem; }
.ref { font: 400 .75rem/1.3 var(--font-mono); color: var(--faint); text-decoration: none; overflow-wrap: anywhere; }
a.ref:hover { color: var(--accent); text-decoration: underline; }
.empty { color: var(--faint); font-style: italic; }

details.box { border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
details.box > summary { cursor: pointer; padding: 10px 14px; font-weight: 600; list-style: none; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
details.box > summary::-webkit-details-marker { display: none; }
details.box > summary::before { content: "▸"; color: var(--faint); transition: transform .15s; display: inline-block; }
details.box[open] > summary::before { transform: rotate(90deg); }
details.box > .body { padding: 0 14px 14px; display: grid; gap: 12px; min-width: 0; }

.diagram { border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); display: grid; min-width: 0; }
.diagram-bar { display: flex; gap: 6px; align-items: center; padding: 8px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.diagram-bar .title { font-weight: 600; margin-right: auto; font-size: var(--step--1); }
.dbtn { font: 500 .75rem/1 var(--font-body); padding: 6px 10px; border-radius: 6px; border: 1px solid var(--line); background: var(--surface-2);
        color: var(--muted); cursor: pointer; }
.dbtn:hover { color: var(--fg); border-color: var(--line-2); }
.diagram-canvas { overflow: auto; padding: 16px; max-height: 78vh; min-height: 120px; }
.diagram-canvas svg { transform-origin: 0 0; max-width: none !important; height: auto; }
pre.mermaid { margin: 0; font-family: var(--font-mono); font-size: .75rem; color: var(--faint); white-space: pre; background: none; }
pre.mermaid[data-processed] { color: inherit; }
.diagram-src { display: none; margin: 0; padding: 12px 16px; border-top: 1px solid var(--line); font: .75rem/1.5 var(--font-mono);
               white-space: pre; overflow: auto; max-height: 320px; background: var(--code-bg); }
.diagram.show-src .diagram-src { display: block; }
.no-mermaid .diagram-canvas::before { content: "Diagrams need an internet connection to load the Mermaid library. The diagram source is shown instead."; display: block; color: var(--warn); margin-bottom: 8px; font-size: var(--step--1); }

.graph { border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); display: grid;
         grid-template-columns: minmax(0, 1fr) 300px; min-height: 520px; overflow: hidden; }
.graph-main { display: grid; grid-template-rows: auto 1fr; min-width: 0; border-right: 1px solid var(--line); }
.graph-bar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; padding: 8px 10px; border-bottom: 1px solid var(--line); }
.graph-bar input { font: inherit; font-size: var(--step--1); padding: 6px 10px; border-radius: 6px; border: 1px solid var(--line-2); background: var(--surface); color: var(--fg); min-width: 0; flex: 1 1 160px; max-width: 260px; }
.graph-canvas { position: relative; min-height: 460px; cursor: grab; touch-action: none; }
.graph-canvas svg { display: block; width: 100%; height: 100%; }
.graph-canvas text { font: 500 10px var(--font-body); fill: var(--fg); paint-order: stroke; stroke: var(--surface); stroke-width: 3px; pointer-events: none; }
.graph-canvas line { stroke: var(--line-2); stroke-opacity: .9; }
.graph-canvas circle { stroke: var(--surface); stroke-width: 1.5px; cursor: pointer; }
.graph-canvas .dim { opacity: .12; }
.graph-canvas .hl circle, .graph-canvas circle.hl { stroke: var(--fg); stroke-width: 2px; }
.graph-canvas line.hl { stroke: var(--accent); stroke-opacity: 1; stroke-width: 1.6px; }
.graph-legend { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 10px; border-top: 1px solid var(--line); }
.graph-legend label { display: inline-flex; align-items: center; gap: 5px; font-size: .75rem; color: var(--muted); cursor: pointer;
                      padding: 2px 8px; border: 1px solid var(--line); border-radius: 999px; }
.graph-legend input { accent-color: var(--accent); margin: 0; }
.graph-legend .sw { width: 9px; height: 9px; border-radius: 50%; }
.graph-info { padding: 14px 16px; display: grid; gap: 10px; align-content: start; font-size: var(--step--1); overflow-y: auto; max-height: 640px; min-width: 0; }
.graph-info h4 { overflow-wrap: anywhere; }
.graph-info ul { list-style: none; padding: 0; display: grid; gap: 3px; }
.graph-info button.lnk { background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; font: inherit; text-align: left; overflow-wrap: anywhere; }
.graph-msg { padding: 24px; color: var(--faint); }
@media (max-width: 900px) { .graph { grid-template-columns: minmax(0, 1fr); } .graph-main { border-right: 0; border-bottom: 1px solid var(--line); } .graph-info { max-height: 300px; } }

.steps { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; counter-reset: step; }
.steps > li { counter-increment: step; display: grid; grid-template-columns: 32px minmax(0, 1fr); gap: 12px; align-items: start;
              background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px; }
.steps > li::before { content: counter(step); font: 600 .875rem/32px var(--font-mono); text-align: center; width: 32px; height: 32px;
                      border-radius: 50%; background: var(--accent-soft); color: var(--accent); }
.steps .step-body { display: grid; gap: 6px; min-width: 0; }
.cmd { display: flex; align-items: stretch; gap: 0; border: 1px solid var(--line-2); border-radius: 6px; overflow: hidden; background: var(--code-bg); max-width: 100%; }
.cmd code { background: none; padding: 8px 12px; flex: 1; min-width: 0; overflow-x: auto; white-space: pre; font-size: .8125rem; border-radius: 0; }
.copy { font: 500 .75rem/1 var(--font-body); border: 0; border-left: 1px solid var(--line-2); background: var(--surface); color: var(--muted); padding: 0 12px; cursor: pointer; }
.copy:hover { color: var(--accent); }
.copy.done { color: var(--ok); }

.status-list { list-style: none; padding: 0; display: grid; gap: 8px; }
.status-list li { display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 10px; align-items: start; }
.dot { width: 12px; height: 12px; border-radius: 50%; margin-top: 5px; background: var(--faint); }
.dot.ok { background: var(--ok); } .dot.warn { background: var(--warn); } .dot.crit { background: var(--crit); } .dot.info { background: var(--info); }

.insight { border: 1px solid var(--line); border-left: 4px solid var(--cc, var(--info)); border-radius: var(--radius); background: var(--surface); }
.insight.crit { --cc: var(--crit); } .insight.warn { --cc: var(--warn); } .insight.info { --cc: var(--info); }
.insight > summary { cursor: pointer; padding: 12px 16px; display: grid; gap: 4px; list-style: none; }
.insight > summary::-webkit-details-marker { display: none; }
.insight > summary .t { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; font-weight: 600; }
.insight > summary p { color: var(--muted); font-size: var(--step--1); }
.insight > .body { padding: 0 16px 16px; display: grid; gap: 10px; }

.tree { list-style: none; padding-left: 0; font: .8125rem/1.6 var(--font-mono); }
.tree ul { list-style: none; padding-left: 18px; border-left: 1px dashed var(--line-2); margin-left: 6px; }
.tree details > summary { cursor: pointer; list-style: none; }
.tree details > summary::-webkit-details-marker { display: none; }
.tree details > summary::before { content: "▸ "; color: var(--faint); }
.tree details[open] > summary::before { content: "▾ "; }
.tree .seg { color: var(--fg); font-weight: 500; }
.tree .leaf { display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; padding-left: 14px; }

.prose { display: grid; gap: 12px; max-width: 78ch; }
.prose p { max-width: none; }
.prose strong { font-weight: 600; }
.md { display: grid; gap: 10px; font-size: var(--step-0); max-width: 80ch; }
.md pre { background: var(--code-bg); padding: 10px 14px; border-radius: 6px; overflow-x: auto; font: .8125rem/1.5 var(--font-mono); margin: 0; }
.md h1, .md h2, .md h3, .md h4 { margin-top: 8px; }
.md table { border-collapse: collapse; font-size: var(--step--1); }
.md td, .md th { border: 1px solid var(--line); padding: 4px 8px; }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
@media (max-width: 760px) { .split { grid-template-columns: minmax(0, 1fr); } }
.bar { height: 8px; border-radius: 4px; background: var(--accent); opacity: .75; min-width: 2px; }
.bar-row { display: grid; grid-template-columns: minmax(120px, 220px) minmax(0, 1fr) 48px; gap: 10px; align-items: center; font-size: var(--step--1); }
.bar-row .num { text-align: right; color: var(--muted); }
.legend-row { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: var(--step--1); color: var(--muted); }

@media (max-width: 860px) {
  .shell { display: block; }
  body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 30; background: var(--surface); }
  .side { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 20; height: auto; flex-direction: row; align-items: center; gap: 10px;
          padding: 8px max(16px, env(safe-area-inset-right, 0px)) 8px max(16px, env(safe-area-inset-left, 0px)); border-right: 0; border-bottom: 1px solid var(--line); overflow: visible; }
  .brand { padding: 0; flex: none; max-width: 38vw; }
  .brand .eyebrow { display: none; }
  .brand .name { font-size: .9375rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .nav { display: flex; gap: 2px; overflow-x: auto; flex: 1; min-width: 0; scrollbar-width: none; }
  .nav-group { display: contents; }
  .nav-label { display: none; }
  .nav a { white-space: nowrap; padding: 6px 10px; }
  .nav a .count { display: none; }
  .side-foot { display: none; }
  h1 { font-size: var(--step-3); }
  .wrap { padding-block: 22px 72px; gap: 32px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
@media print { .side, .diagram-bar, .graph-bar, .tbl-tools { display: none; } .shell { display: block; } }
"""

THEME_BOOT = r"""(function(){try{var t=localStorage.getItem('laravel-map-theme');if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();"""

JS_COMMON = r"""
(function () {
  const root = document.documentElement;
  window.loadScript = window.loadScript || function (urls, ok, fail) {
    const next = i => { if (i >= urls.length) { fail && fail(); return; }
      const s = document.createElement('script'); s.src = urls[i]; s.onload = ok; s.onerror = () => { s.remove(); next(i + 1); }; document.head.appendChild(s); };
    next(0);
  };
  // ---- theme toggle: system -> light -> dark
  const btn = document.querySelector('.theme-btn');
  function label() { const t = root.getAttribute('data-theme'); if (btn) btn.textContent = 'Theme: ' + (t || 'system'); }
  label();
  if (btn) btn.addEventListener('click', () => {
    const t = root.getAttribute('data-theme');
    const next = !t ? 'light' : t === 'light' ? 'dark' : null;
    if (next) root.setAttribute('data-theme', next); else root.removeAttribute('data-theme');
    try { if (next) localStorage.setItem('laravel-map-theme', next); else localStorage.removeItem('laravel-map-theme'); } catch (e) {}
    label(); rerenderDiagrams(); document.dispatchEvent(new CustomEvent('lm-theme'));
  });

  // ---- table filtering & sorting
  document.querySelectorAll('[data-filter-for]').forEach(inp => {
    const tbl = document.getElementById(inp.getAttribute('data-filter-for'));
    if (!tbl) return;
    const counter = document.querySelector('[data-count-for="' + tbl.id + '"]');
    const rows = Array.from(tbl.tBodies[0] ? tbl.tBodies[0].rows : []);
    const texts = rows.map(r => r.textContent.toLowerCase());
    function apply() {
      const terms = inp.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      let shown = 0;
      rows.forEach((r, i) => { const hit = terms.every(t => texts[i].includes(t)); r.hidden = !hit; if (hit) shown++; });
      if (counter) counter.textContent = shown === rows.length ? rows.length + ' rows' : shown + ' of ' + rows.length;
    }
    inp.addEventListener('input', apply);
    apply();
  });
  document.querySelectorAll('.qf[data-qf]').forEach(b => b.addEventListener('click', () => {
    const inp = document.getElementById(b.getAttribute('data-target'));
    if (!inp) return;
    const on = b.getAttribute('aria-pressed') === 'true';
    document.querySelectorAll('.qf[data-target="' + b.getAttribute('data-target') + '"]').forEach(x => x.setAttribute('aria-pressed', 'false'));
    inp.value = on ? '' : b.getAttribute('data-qf');
    if (!on) b.setAttribute('aria-pressed', 'true');
    inp.dispatchEvent(new Event('input'));
  }));
  document.querySelectorAll('table.data th[data-sort]').forEach(th => th.addEventListener('click', () => {
    const tbl = th.closest('table'); const idx = Array.from(th.parentNode.children).indexOf(th);
    const dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
    th.parentNode.querySelectorAll('th').forEach(x => x.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', dir);
    const body = tbl.tBodies[0]; const rows = Array.from(body.rows);
    const val = r => { const c = r.cells[idx]; return c ? (c.getAttribute('data-v') || c.textContent).trim() : ''; };
    const numeric = rows.every(r => val(r) === '' || !isNaN(parseFloat(val(r))));
    rows.sort((a, b) => { let x = val(a), y = val(b);
      if (numeric) { x = parseFloat(x) || 0; y = parseFloat(y) || 0; return dir === 'ascending' ? x - y : y - x; }
      return dir === 'ascending' ? x.localeCompare(y) : y.localeCompare(x); });
    rows.forEach(r => body.appendChild(r));
  }));

  // ---- copy buttons
  document.querySelectorAll('button.copy').forEach(b => b.addEventListener('click', () => {
    const text = b.getAttribute('data-copy');
    const done = () => { b.classList.add('done'); b.textContent = 'Copied'; setTimeout(() => { b.classList.remove('done'); b.textContent = 'Copy'; }, 1400); };
    const fallback = () => { const code = b.parentNode.querySelector('code'); if (!code) return; const rg = document.createRange(); rg.selectNodeContents(code);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg); b.textContent = 'Selected'; };
    try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
  }));

  // ---- mermaid diagrams (lazy, theme aware, zoomable)
  const blocks = Array.from(document.querySelectorAll('pre.mermaid'));
  blocks.forEach(p => { p.dataset.src = p.textContent; });
  function isDark() { const t = root.getAttribute('data-theme'); return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; }
  function visible(el) { return !!(el.offsetParent || el.getClientRects().length); }
  let ready = false;
  function init() {
    if (!window.mermaid) return false;
    window.mermaid.initialize({ startOnLoad: false, theme: isDark() ? 'dark' : 'neutral', securityLevel: 'strict', maxTextSize: 900000, maxEdges: 4000,
      fontFamily: getComputedStyle(root).getPropertyValue('--font-body'), flowchart: { htmlLabels: true, curve: 'basis', useMaxWidth: false },
      er: { useMaxWidth: false }, themeVariables: { fontSize: '13px' } });
    ready = true; return true;
  }
  function render(list) {
    if (!ready && !init()) return;
    const todo = list.filter(p => !p.hasAttribute('data-processed') && visible(p));
    if (!todo.length) return;
    window.mermaid.run({ nodes: todo }).then(() => todo.forEach(fit)).catch(err => console.warn('mermaid', err));
  }
  function fit(p) {
    const box = p.closest('.diagram'); const svg = p.querySelector('svg'); if (!box || !svg) return;
    const canvas = box.querySelector('.diagram-canvas'); const w = svg.getBBox ? svg.getBoundingClientRect().width : 0;
    const avail = canvas.clientWidth - 32; box._z = 1;
    if (w > avail && avail > 0) { box._z = Math.max(.35, avail / w); }
    svg.style.transform = 'scale(' + box._z + ')'; svg.style.marginBottom = ((box._z - 1) * svg.getBoundingClientRect().height / box._z) + 'px';
  }
  function rerenderDiagrams() {
    if (!window.mermaid) return; ready = false; init();
    blocks.forEach(p => { p.removeAttribute('data-processed'); p.innerHTML = ''; p.textContent = p.dataset.src; });
    render(blocks);
  }
  document.querySelectorAll('.diagram').forEach(box => {
    const svgOf = () => box.querySelector('.diagram-canvas svg');
    const setZ = z => { const s = svgOf(); if (!s) return; box._z = Math.min(4, Math.max(.2, z)); s.style.transform = 'scale(' + box._z + ')';
      s.style.marginBottom = ((box._z - 1) * s.getBoundingClientRect().height / box._z) + 'px'; };
    box.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
      const a = b.getAttribute('data-act');
      if (a === 'in') setZ((box._z || 1) * 1.25);
      if (a === 'out') setZ((box._z || 1) / 1.25);
      if (a === 'reset') setZ(1);
      if (a === 'fit') { const p = box.querySelector('pre.mermaid'); if (p) fit(p); }
      if (a === 'src') box.classList.toggle('show-src');
    }));
  });
  document.querySelectorAll('details').forEach(d => d.addEventListener('toggle', () => { if (d.open) render(Array.from(d.querySelectorAll('pre.mermaid'))); }));
  if (blocks.length) {
    if (window.mermaid) render(blocks);
    else setTimeout(() => {
      if (blocks.every(p => p.querySelector('svg') || p.hasAttribute('data-processed'))) return;  // already rendered by the host page
      if (window.mermaid) render(blocks);
      else loadScript(__MERMAID__, () => render(blocks), () => document.body.classList.add('no-mermaid'));
    }, 250);
  }
})();
"""

JS_GRAPH = r"""
(function () {
  const graphs = Array.from(document.querySelectorAll('.graph[data-graph]'));
  if (!graphs.length) return;
  function boot() { graphs.forEach(el => { try { build(el); } catch (e) { console.error(e); el.querySelector('.graph-canvas').innerHTML = '<p class="graph-msg">Could not draw this graph: ' + e.message + '</p>'; } }); }
  if (window.d3) boot(); else window.loadScript(__D3__, boot,
    () => graphs.forEach(el => { el.querySelector('.graph-canvas').innerHTML = '<p class="graph-msg">The interactive graph needs d3, which could not be loaded (no internet?). Re-run with --offline once while online to bundle it. The tables on this page list the same information.</p>'; }));
  function build(el) {
    const data = JSON.parse(el.querySelector('script[type="application/json"]').textContent);
    const canvas = el.querySelector('.graph-canvas'), info = el.querySelector('.graph-info'), search = el.querySelector('input[type="search"]');
    const css = () => getComputedStyle(document.documentElement);
    const color = k => css().getPropertyValue('--role-' + k).trim() || css().getPropertyValue('--faint').trim();
    const W = Math.max(320, canvas.clientWidth || 800), H = Math.max(440, Math.min(720, Math.round(window.innerHeight * .68)));
    canvas.style.height = H + 'px';
    const nodes = data.nodes.map(d => Object.assign({}, d));
    const byId = new Map(nodes.map(n => [n.id, n]));
    const links = data.edges.filter(e => byId.has(e.s) && byId.has(e.t) && e.s !== e.t).map(e => ({ source: e.s, target: e.t, k: e.k || '' }));
    const out = new Map(), inn = new Map();
    links.forEach(l => { (out.get(l.source) || out.set(l.source, []).get(l.source)).push(l); (inn.get(l.target) || inn.set(l.target, []).get(l.target)).push(l); });
    nodes.forEach(n => { n.deg = (out.get(n.id) || []).length + (inn.get(n.id) || []).length; n.r = 4 + Math.sqrt(n.deg) * 2.1; });
    const kinds = Array.from(new Set(nodes.map(n => n.k)));
    const angle = new Map(kinds.map((k, i) => [k, (i / kinds.length) * Math.PI * 2]));
    const spread = Math.min(W, H) * .28;
    const svg = d3.select(canvas).append('svg').attr('viewBox', [0, 0, W, H]).attr('preserveAspectRatio', 'xMidYMid meet').attr('role', 'img').attr('aria-label', data.label || 'Graph');
    const defs = svg.append('defs');
    defs.append('marker').attr('id', el.id + '-arrow').attr('viewBox', '0 -4 8 8').attr('refX', 8).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto').append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', 'currentColor');
    const g = svg.append('g');
    const link = g.append('g').selectAll('line').data(links).join('line').attr('stroke-width', 1).style('color', 'var(--line-2)')
      .attr('marker-end', nodes.length < 400 ? 'url(#' + el.id + '-arrow)' : null);
    const node = g.append('g').selectAll('circle').data(nodes).join('circle').attr('r', d => d.r).attr('fill', d => color(d.k));
    node.append('title').text(d => d.l + (d.sub ? '\n' + d.sub : ''));
    const label = g.append('g').selectAll('text').data(nodes).join('text').text(d => d.l).attr('dx', d => d.r + 3).attr('dy', 3);
    const degs = nodes.map(n => n.deg).sort((a, b) => b - a);
    const thresh = degs[Math.min(degs.length - 1, Math.max(0, Math.floor(nodes.length * .18)))] || 0;
    let zoomK = 1;
    function labels() { label.style('display', d => (nodes.length <= 60 || d.deg >= Math.max(1, thresh) || zoomK > 1.7 || d._hl) ? null : 'none'); }
    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(l => 40 + (l.source.r || 4) + (l.target.r || 4)).strength(.35))
      .force('charge', d3.forceManyBody().strength(nodes.length > 500 ? -40 : -110).distanceMax(420))
      .force('x', d3.forceX(d => W / 2 + Math.cos(angle.get(d.k)) * spread).strength(.06))
      .force('y', d3.forceY(d => H / 2 + Math.sin(angle.get(d.k)) * spread).strength(.06))
      .force('collide', d3.forceCollide(d => d.r + 2.5));
    function ticked() {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => { const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y, L = Math.hypot(dx, dy) || 1; return d.target.x - dx / L * (d.target.r + 2); })
        .attr('y2', d => { const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y, L = Math.hypot(dx, dy) || 1; return d.target.y - dy / L * (d.target.r + 2); });
      node.attr('cx', d => d.x).attr('cy', d => d.y);
      label.attr('x', d => d.x).attr('y', d => d.y);
    }
    if (nodes.length > 350) { sim.stop(); for (let i = 0; i < 260; i++) sim.tick(); ticked(); } else sim.on('tick', ticked);
    const zoom = d3.zoom().scaleExtent([.08, 8]).on('zoom', ev => { g.attr('transform', ev.transform); zoomK = ev.transform.k; labels(); });
    svg.call(zoom).on('dblclick.zoom', null);
    node.call(d3.drag()
      .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(.2).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; if (nodes.length > 350) ticked(); })
      .on('end', (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    function fitView(sel) {
      const pts = (sel || nodes).filter(n => n.x != null);
      if (!pts.length) return;
      const x0 = d3.min(pts, d => d.x) - 40, x1 = d3.max(pts, d => d.x) + 120, y0 = d3.min(pts, d => d.y) - 30, y1 = d3.max(pts, d => d.y) + 30;
      const k = Math.min(4, .95 / Math.max((x1 - x0) / W, (y1 - y0) / H));
      svg.transition().duration(450).call(zoom.transform, d3.zoomIdentity.translate(W / 2, H / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2));
    }
    const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    let selected = null;
    function select(d, center) {
      selected = d;
      const nb = new Set([d.id]);
      (out.get(d.id) || []).forEach(l => nb.add(typeof l.target === 'object' ? l.target.id : l.target));
      (inn.get(d.id) || []).forEach(l => nb.add(typeof l.source === 'object' ? l.source.id : l.source));
      nodes.forEach(n => n._hl = nb.has(n.id));
      node.classed('dim', n => !nb.has(n.id)).classed('hl', n => n.id === d.id);
      label.classed('dim', n => !nb.has(n.id));
      link.classed('dim', l => l.source.id !== d.id && l.target.id !== d.id).classed('hl', l => l.source.id === d.id || l.target.id === d.id);
      labels();
      const o = (out.get(d.id) || []).map(l => l.target), i = (inn.get(d.id) || []).map(l => l.source);
      const li = arr => arr.length ? '<ul>' + arr.slice(0, 80).map(n => '<li><button class="lnk" data-id="' + esc(n.id) + '">' + esc(n.l) + '</button> <span class="faint">' + esc(n.kl || n.k) + '</span></li>').join('') + '</ul>' : '<p class="faint">none</p>';
      info.innerHTML = '<h4>' + esc(d.l) + '</h4>' + '<div class="chips"><span class="chip" style="--dot:' + color(d.k) + '">' + esc(d.kl || d.k) + '</span></div>' +
        (d.sub ? '<p class="muted">' + esc(d.sub) + '</p>' : '') + (d.f ? '<p class="ref">' + esc(d.f) + '</p>' : '') +
        (d.u ? '<p><a href="' + esc(d.u) + '">Open details →</a></p>' : '') +
        '<div><strong>' + esc(data.outLabel || 'Uses') + ' (' + o.length + ')</strong>' + li(o) + '</div>' +
        '<div><strong>' + esc(data.inLabel || 'Used by') + ' (' + i.length + ')</strong>' + li(i) + '</div>';
      info.querySelectorAll('button.lnk').forEach(b => b.addEventListener('click', () => select(byId.get(b.getAttribute('data-id')), true)));
      if (center) fitView(nodes.filter(n => nb.has(n.id)));
    }
    function clear() { selected = null; nodes.forEach(n => n._hl = false); node.classed('dim', false).classed('hl', false); label.classed('dim', false); link.classed('dim', false).classed('hl', false); labels(); info.innerHTML = info.dataset.empty; }
    info.dataset.empty = info.innerHTML;
    node.on('click', (ev, d) => { ev.stopPropagation(); select(d, false); });
    svg.on('click', () => clear());
    if (search) search.addEventListener('input', () => {
      const q = search.value.toLowerCase().trim();
      if (!q) { clear(); return; }
      const hits = nodes.filter(n => n.l.toLowerCase().includes(q) || (n.sub || '').toLowerCase().includes(q));
      if (hits.length === 1) { select(hits[0], true); return; }
      const ids = new Set(hits.map(n => n.id)); nodes.forEach(n => n._hl = ids.has(n.id));
      node.classed('dim', n => !ids.has(n.id)).classed('hl', false); label.classed('dim', n => !ids.has(n.id)); link.classed('dim', true); labels();
    });
    el.querySelectorAll('[data-gact]').forEach(b => b.addEventListener('click', () => {
      const a = b.getAttribute('data-gact');
      if (a === 'fit') fitView(); if (a === 'reset') { clear(); fitView(); }
      if (a === 'isolate' && selected) {
        const nb = new Set(nodes.filter(n => n._hl).map(n => n.id));
        node.style('display', n => nb.has(n.id) ? null : 'none'); label.style('display', n => nb.has(n.id) ? null : 'none');
        link.style('display', l => nb.has(l.source.id) && nb.has(l.target.id) ? null : 'none'); fitView(nodes.filter(n => nb.has(n.id)));
      }
      if (a === 'all') { node.style('display', null); link.style('display', null); labels(); applyKinds(); fitView(); }
    }));
    function applyKinds() {
      const off = new Set(Array.from(el.querySelectorAll('.graph-legend input')).filter(i => !i.checked).map(i => i.value));
      node.style('display', n => off.has(n.k) ? 'none' : null);
      label.style('display', n => off.has(n.k) ? 'none' : ((nodes.length <= 60 || n.deg >= Math.max(1, thresh) || zoomK > 1.7 || n._hl) ? null : 'none'));
      link.style('display', l => off.has(l.source.k) || off.has(l.target.k) ? 'none' : null);
    }
    el.querySelectorAll('.graph-legend input').forEach(i => i.addEventListener('change', applyKinds));
    el.querySelectorAll('.graph-legend .sw').forEach(sw => sw.style.background = color(sw.getAttribute('data-k')));
    document.addEventListener('lm-theme', () => { node.attr('fill', d => color(d.k)); el.querySelectorAll('.graph-legend .sw').forEach(sw => sw.style.background = color(sw.getAttribute('data-k'))); });
    labels();
    setTimeout(() => fitView(), nodes.length > 350 ? 50 : 1400);
  }
})();
"""


# =====================================================================================================
# 24. HTML helpers
# =====================================================================================================

def e(s):
    return html.escape("" if s is None else str(s), quote=True)


class Html:
    """Rendering context: knows the editor link format and the project root."""

    def __init__(self, root, editor):
        self.root = root
        self.editor = editor
        self._n = 0

    def uid(self, p="x"):
        self._n += 1
        return f"{p}{self._n}"

    def ref(self, rel, line=None, label=None):
        if not rel:
            return ""
        text = label or (f"{rel}:{line}" if line else rel)
        if self.editor:
            path = os.path.join(self.root, rel)
            url = self.editor.replace("{path}", path).replace("{line}", str(line or 1))
            return f'<a class="ref" href="{e(url)}">{e(text)}</a>'
        return f'<span class="ref">{e(text)}</span>'


EDITORS = {"vscode": "vscode://file/{path}:{line}", "cursor": "cursor://file/{path}:{line}",
           "phpstorm": "phpstorm://open?file={path}&line={line}", "idea": "idea://open?file={path}&line={line}",
           "sublime": "subl://open?url=file://{path}&line={line}", "zed": "zed://file/{path}:{line}", "none": None}


def pick_editor(name, root):
    if name == "auto":
        if os.path.isdir(os.path.join(root, ".idea")):
            return EDITORS["phpstorm"]
        if os.path.isdir(os.path.join(root, ".vscode")) or shutil.which("code"):
            return EDITORS["vscode"]
        return None
    if name in EDITORS:
        return EDITORS[name]
    return name if "{path}" in name else None


def code(s):
    return f"<code>{e(s)}</code>"


def chip(text, role=None, plain=False):
    style = f' style="--dot: var(--role-{e(role)})"' if role else ""
    return f'<span class="chip{" plain" if plain else ""}"{style}>{e(text)}</span>'


def role_chip(role):
    return chip(ROLE_INFO.get(role, {"label": role})["label"], role)


def badge(text, kind=""):
    return f'<span class="badge {e(kind)}">{e(text)}</span>'


def methods_html(methods):
    ms = [m for m in methods if m != "HEAD"] or methods
    return "".join(f'<span class="m m-{e(m)}">{e(m)}</span>' for m in ms)


def cmd_box(command):
    if not command:
        return ""
    return f'<div class="cmd"><code>{e(command)}</code><button type="button" class="copy" data-copy="{e(command)}">Copy</button></div>'


def callout(kind, title, body=""):
    return f'<div class="callout {e(kind)}"><strong>{title}</strong>{f"<p>{body}</p>" if body else ""}</div>'


def kv(pairs):
    rows = "".join(f"<dt>{e(k)}</dt><dd>{v}</dd>" for k, v in pairs if v not in (None, "", []))
    return f'<dl class="kv">{rows}</dl>' if rows else ""


def section(id_, title, body, lede=""):
    return (f'<section class="sec" id="{e(id_)}"><div class="sec-head"><h2>{e(title)}</h2>'
            f'{f"<p>{lede}</p>" if lede else ""}</div>{body}</section>')


def details(summary, body, open_=False, cls="box"):
    return f'<details class="{cls}"{" open" if open_ else ""}><summary>{summary}</summary><div class="body">{body}</div></details>'


def table(h, tid, headers, rows, filter_=True, empty="Nothing found.", quick=None, sort=True, placeholder="Filter…"):
    if not rows:
        return f'<p class="empty">{e(empty)}</p>'
    tid = tid or h.uid("t")
    tools = ""
    if filter_ and len(rows) > 6:
        fid = tid + "-q"
        qf = "".join(f'<button type="button" class="qf" data-qf="{e(q)}" data-target="{fid}" aria-pressed="false">{e(lbl)}</button>'
                     for lbl, q in (quick or []))
        tools = (f'<div class="tbl-tools"><input type="search" id="{fid}" data-filter-for="{tid}" placeholder="{e(placeholder)}" '
                 f'aria-label="Filter table">{qf}<span class="count" data-count-for="{tid}"></span></div>')
    head = "".join(f'<th{" data-sort" if sort else ""} scope="col">{e(x)}</th>' for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" if not (isinstance(c, tuple)) else f'<td data-v="{e(c[1])}">{c[0]}</td>' for c in r) + "</tr>" for r in rows)
    return f'{tools}<div class="table-wrap"><table class="data" id="{tid}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def mm_id(s):
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", str(s))


def mm_label(s):
    return (str(s).replace("&", "&amp;").replace('"', "#quot;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("&lt;br/&gt;", "<br/>").replace("&lt;small&gt;", "<small>").replace("&lt;/small&gt;", "</small>")
            .replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"))


def mermaid(h, src, title="", lazy=False, note=""):
    did = h.uid("d")
    return (f'<div class="diagram" id="{did}"><div class="diagram-bar"><span class="title">{e(title)}</span>'
            '<button type="button" class="dbtn" data-act="out" aria-label="Zoom out">−</button>'
            '<button type="button" class="dbtn" data-act="in" aria-label="Zoom in">+</button>'
            '<button type="button" class="dbtn" data-act="fit">Fit</button>'
            '<button type="button" class="dbtn" data-act="reset">100%</button>'
            '<button type="button" class="dbtn" data-act="src">Source</button></div>'
            f'<div class="diagram-canvas"><pre class="mermaid">{e(src)}</pre></div>'
            f'<pre class="diagram-src">{e(src)}</pre>{f"<p class=small style=padding:0_16px_12px>{note}</p>" if note else ""}</div>')


def graph(h, nodes, edges, label="Graph", out_label="Uses", in_label="Used by", hint="Click a node to see its connections."):
    gid = h.uid("g")
    kinds = []
    for n in nodes:
        if n["k"] not in [k for k, _ in kinds]:
            kinds.append((n["k"], n.get("kl") or ROLE_INFO.get(n["k"], {}).get("plural", n["k"])))
    legend = "".join(f'<label><input type="checkbox" value="{e(k)}" checked><span class="sw" data-k="{e(k)}"></span>{e(lbl)}</label>' for k, lbl in kinds)
    payload = json.dumps({"nodes": nodes, "edges": edges, "label": label, "outLabel": out_label, "inLabel": in_label}, default=str).replace("</", "<\\/")
    return (f'<div class="graph" id="{gid}" data-graph><div class="graph-main"><div class="graph-bar">'
            f'<input type="search" placeholder="Find a node…" aria-label="Find a node">'
            '<button type="button" class="dbtn" data-gact="fit">Fit</button>'
            '<button type="button" class="dbtn" data-gact="isolate">Isolate selection</button>'
            '<button type="button" class="dbtn" data-gact="all">Show all</button>'
            '<button type="button" class="dbtn" data-gact="reset">Reset</button></div>'
            f'<div class="graph-canvas"></div><div class="graph-legend">{legend}</div></div>'
            f'<aside class="graph-info"><p class="muted">{e(hint)} Drag to move, scroll or pinch to zoom, untick a colour to hide it.</p>'
            f'<p class="faint">{len(nodes)} nodes · {len(edges)} connections</p></aside>'
            f'<script type="application/json">{payload}</script></div>')


def md_to_html(md):
    """Small Markdown renderer for READMEs (headings, lists, code, tables, links, emphasis)."""
    out, lines, i = [], md.splitlines(), 0

    def inline(t):
        t = e(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", t)
        t = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", t)
        t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener">\1</a>', t)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 <span class='faint'>(\2)</span>", t)
        return t

    para = []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            flush()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            out.append("<pre>" + e("\n".join(buf)) + "</pre>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            flush()
            lvl = min(4, len(m.group(1)) + 1)
            out.append(f"<h{lvl}>{inline(m.group(2).strip('# '))}</h{lvl}>")
            i += 1
            continue
        if re.match(r"^\s*([-*+]|\d+[.)])\s+", ln):
            flush()
            ordered = bool(re.match(r"^\s*\d+[.)]", ln))
            items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", lines[i]))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\s*\|?\s*:?-{2,}", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head = "".join(f"<th>{inline(c)}</th>" for c in rows[0]) if rows else ""
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
            out.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            continue
        if ln.strip().startswith(">"):
            flush()
            out.append(f'<div class="callout info"><p>{inline(ln.strip()[1:].strip())}</p></div>')
            i += 1
            continue
        if not ln.strip():
            flush()
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return '<div class="md">' + "".join(out) + "</div>"


# =====================================================================================================
# 25. Controller / request / resource / policy details (used by the HTTP page)
# =====================================================================================================

def analyze_http(proj, data):
    roles = proj.roles
    edges = data["async"]["edges"]
    routes_by = defaultdict(list)
    for r in data["routes"]:
        if r.get("controller"):
            routes_by[(r["controller"], r.get("method") or "__invoke")].append(r)
    out = {"controllers": [], "requests": [], "resources": [], "policies": []}
    for c in proj.classes_by_role("controller"):
        acts = []
        for m in c.methods.values():
            if m.visibility != "public" or m.name.startswith("__") and m.name != "__invoke" or m.static:
                continue
            sc = c.file.method_scan(c, m)
            ptypes = [t for p in m.params for t in p["types"]]
            refs = {f for f, _ in sc.refs} | set(ptypes)
            models = sorted({short(f) for f in refs if roles.get(f) == "model"})
            requests = sorted({short(t) for t in ptypes if roles.get(t) == "request"})
            resources = sorted({short(f) for f in refs if roles.get(f) == "resource"})
            views = sorted({s for fn, s, _ in sc.calls if fn == "view" and s} |
                           {s for cls, mn, s, _ in sc.statics if short(cls) == "View" and mn == "make" and s})
            pages = sorted({s for fn, s, _ in sc.calls if fn == "inertia" and s} |
                           {s for cls, mn, s, _ in sc.statics if short(cls) == "Inertia" and mn == "render" and s})
            disp = sorted({f"{short(x['to'])}" for x in edges if x["from"] == c.fqn and x["method"] == m.name})
            fns = {fn for fn, _, _ in sc.calls}
            mcs = {mn for mn, _, _, _ in sc.mcalls}
            returns = []
            if pages:
                returns.append("Inertia page")
            if views:
                returns.append("view")
            if "json" in mcs or resources:
                returns.append("JSON")
            if fns & {"redirect", "to_route", "back"} or mcs & {"back", "intended"}:
                returns.append("redirect")
            if "abort" in fns or "abort_if" in fns or "abort_unless" in fns:
                returns.append("may abort")
            auth = bool(mcs & {"authorize", "authorizeResource"} or any(short(cls) == "Gate" for cls, _, _, _ in sc.statics))
            services = sorted({short(f) for f in refs if roles.get(f) in ("action", "service", "repository")})
            acts.append({"name": m.name, "line": m.line, "lines": m.end_line - m.line + 1,
                         "routes": [f"{'|'.join(x for x in r['methods'] if x != 'HEAD')} {r['uri']}" for r in routes_by.get((c.fqn, m.name), [])],
                         "models": models, "requests": requests, "resources": resources, "views": views, "pages": pages,
                         "dispatches": disp, "returns": returns, "authorizes": auth, "services": services})
        out["controllers"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel, "line": c.line, "doc": c.doc,
                                   "abstract": c.abstract, "parent": c.extends, "actions": acts,
                                   "middleware": [], "loc": c.end_line - c.line + 1})
    for c in proj.classes_by_role("request"):
        rv = return_value(c.file, c.methods.get("rules"))
        fields = [str(k) for k in rv.keys()] if isinstance(rv, dict) else []
        auth = return_value(c.file, c.methods.get("authorize"))
        out["requests"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel, "fields": fields,
                                "authorize": fmt_val(auth) if auth is not None else "—",
                                "used_by": sorted({f"{short(x['fqn'])}::{a['name']}" for x in out["controllers"] for a in x["actions"] if c.name in a["requests"]})})
    for c in proj.classes_by_role("resource"):
        rv = return_value(c.file, c.methods.get("toArray"))
        fields = [str(k) for k in rv.keys()] if isinstance(rv, dict) else []
        out["resources"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel, "fields": fields,
                                 "used_by": sorted({f"{short(x['fqn'])}::{a['name']}" for x in out["controllers"] for a in x["actions"] if c.name in a["resources"]})})
    model_by_policy = {m["policy"]: m["name"] for m in data["models"].values() if m.get("policy")}
    for c in proj.classes_by_role("policy"):
        out["policies"].append({"fqn": c.fqn, "name": c.name, "file": c.file.rel, "model": model_by_policy.get(c.fqn),
                                "abilities": [m.name for m in c.methods.values() if m.visibility == "public" and not m.name.startswith("__")]})
    return out


# =====================================================================================================
# 26. Pages
# =====================================================================================================

PAGES = [
    ("index.html", "Overview", "Orientation", "What this app is, its stack, an architecture sketch and where to start reading."),
    ("start.html", "Getting started", "Orientation", "Boot the Docker environment, the URLs to open, everyday commands and the state of your machine."),
    ("changes.html", "What changed", "Orientation", "Commits, structural changes and a catch-up checklist since your last look."),
    ("routes.html", "Routes", "Application", "Every URL the app answers, who handles it and which middleware runs."),
    ("http.html", "HTTP layer", "Application", "Request lifecycle, middleware, controllers and what each action does."),
    ("trace.html", "Request traces", "Application", "Follow a route, command or job through every method it reaches: tables, jobs, events, mail."),
    ("models.html", "Models", "Application", "Eloquent models, relationships, casts, scopes, observers and policies."),
    ("database.html", "Database", "Application", "Schema rebuilt from migrations: ER diagram, tables and history."),
    ("events.html", "Events & jobs", "Application", "Events, listeners, queued jobs, mail, notifications, schedule and commands."),
    ("frontend.html", "Frontend", "Application", "Blade views and components, Inertia pages and the asset pipeline."),
    ("livewire.html", "Livewire", "Application", "Livewire and Volt components: state, actions, events and where they appear."),
    ("filament.html", "Filament", "Application", "Admin panels, resources, pages and widgets, and the URLs they create."),
    ("classes.html", "Classes", "Application", "Every class by role, with an interactive dependency graph."),
    ("docker.html", "Docker", "Environment", "Compose services, how they connect, Dockerfiles, ports and volumes."),
    ("config.html", "Config & packages", "Environment", "Environment variables, the config keys they feed and every dependency."),
    ("insights.html", "Insights", "Health", "Broken references, risky patterns, hotspots, ownership and TODOs."),
]


def page_shell(data, current, title, lede, body, counts, pages, with_graph=False):
    name = data["meta"]["name"]
    groups = []
    for grp in ("Orientation", "Application", "Environment", "Health"):
        links = []
        for f, t, g, _desc in PAGES:
            if g != grp or f not in pages:
                continue
            cnt = counts.get(f)
            links.append(f'<a href="{f}"{" aria-current=page" if f == current else ""}>{e(t)}'
                         f'{f"<span class=count>{cnt}</span>" if cnt not in (None, "") else ""}</a>')
        if links:
            groups.append(f'<div class="nav-group"><div class="nav-label">{grp}</div>{"".join(links)}</div>')
    g = data.get("git") or {}
    foot = (f'<div>Mapped {e(data["meta"]["generated"][:16].replace("T", " "))} UTC</div>' +
            (f'<div class="mono">{e(g.get("branch") or "")} @ {e((g.get("head") or "")[:8])}</div>' if g else "") +
            f'<div>laravel_map.py {VERSION}</div><button type="button" class="theme-btn">Theme: system</button>')
    page_title = f"{name} codebase map" if current == "index.html" else f"{title} · {name}"
    local = data.get("_assets_local")
    murls = json.dumps((["assets/mermaid.min.js"] if local else []) + [MERMAID_URL])
    durls = json.dumps((["assets/d3.min.js"] if local else []) + [D3_URL])
    scripts = f"<script>{JS_COMMON.replace('__MERMAID__', murls)}</script>"
    if with_graph:
        scripts += f"<script>{JS_GRAPH.replace('__D3__', durls)}</script>"
    extra_css = ""
    if current == "trace.html":
        scripts += f"<script>{JS_TRACE}</script>"
        extra_css = TRACE_CSS
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="claude:viewport-fit-sides" content="cover">
<title>{e(page_title)}</title>
<meta name="generator" content="laravel_map.py {VERSION}">
<script>{THEME_BOOT}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS_URL}">
<style>{CSS}{extra_css}</style>
</head>
<body>
<div class="shell">
<aside class="side" aria-label="Site navigation">
  <div class="brand"><span class="eyebrow">Laravel map</span><a class="name" href="index.html">{e(name)}</a></div>
  <nav class="nav">{"".join(groups)}</nav>
  <div class="side-foot">{foot}</div>
</aside>
<main>
<div class="wrap">
<header class="page-head"><div class="crumb">{e(name)} · {e(title)}</div><h1>{e(title if current != "index.html" else name)}</h1><p class="lede">{lede}</p></header>
{body}
</div>
</main>
</div>
{scripts}
</body>
</html>
"""


def cls_link(fqn, role=None, page=None):
    if not fqn:
        return ""
    page = page or {"model": "models.html#m-", "controller": "http.html#c-", "livewire": "livewire.html#lw-",
                    "filament": "filament.html#f-"}.get(role or "")
    label = e(short(fqn))
    if page:
        return f'<a href="{page}{e(short(fqn))}" title="{e(fqn)}" class="mono">{label}</a>'
    return f'<span class="mono" title="{e(fqn)}">{label}</span>'


def list_html(items, empty="—", mono=False, limit=12):
    items = [x for x in items if x]
    if not items:
        return f'<span class="faint">{e(empty)}</span>'
    shown = items[:limit]
    more = f' <span class="faint">+{len(items) - limit} more</span>' if len(items) > limit else ""
    return f'<div class="sub-list{" mono" if mono else ""}">' + "".join(f"<span>{x}</span>" for x in shown) + more + "</div>"


def esc_list(items, **kw):
    return list_html([e(x) for x in items], **kw)


# ---------------------------------------------------------------------------------------------- index

def explain(data):
    s, m, d = data["stack"], data["meta"], data["docker"]
    routes = [r for r in data["routes"] if r.get("source") != "package (inferred)"]
    api = [r for r in routes if r["uri"].startswith("/api") or r.get("group") == "api"]
    fil = [r for r in routes if r.get("action_type") == "filament"]
    web = len(routes) - len(api) - len(fil)
    paras = []
    p = f"<strong>{e(m['name'])}</strong> is a Laravel {e(s['laravel'] or '(version unknown)')} application"
    if s["php"]:
        p += f" requiring PHP {e(s['php'])}"
    p += "."
    p += f" It uses the {e(s['structure'].lower() if s['structure'].startswith('Classic') else s['structure'])}."
    paras.append(p)
    ui = f"The user interface is built with <strong>{e(', '.join(s['frontend']))}</strong>"
    if s["bundler"]:
        ui += f", bundled by {e(s['bundler'])}"
    if s["css"]:
        ui += f" and styled with {e(s['css'])}"
    ui += "."
    for pnl in data["filament"]["panels"]:
        nres = sum(1 for r in data["filament"]["resources"] if r["panel"] == pnl["id"])
        ui += f" A Filament panel “{e(pnl['id'])}” lives at <code>/{e(pnl['path'])}</code> with {nres} resource{'s' if nres != 1 else ''}."
    if data["livewire"]["components"]:
        ui += f" There are {len(data['livewire']['components'])} Livewire components."
    paras.append(ui)
    rp = f"It answers <strong>{len(routes)} routes</strong>: {web} web"
    if api:
        rp += f", {len(api)} API under <code>/api</code>"
    if fil:
        rp += f", {len(fil)} generated by Filament"
    rp += "."
    if s["auth"]:
        rp += f" Authentication and authorisation use {e(', '.join(s['auth']))}."
    paras.append(rp)
    models = data["models"]
    if models:
        top = sorted(models.values(), key=lambda x: -len(x["relations"]))[:3]
        mp = (f"<strong>{len(models)} Eloquent models</strong> map onto {len(data['schema'])} tables rebuilt from "
              f"{len(data['migrations'])} migrations")
        if s["db"]:
            mp += f" (<code>{e(s['db'])}</code> in development)"
        mp += ". The most connected models are " + ", ".join(f"<a href='models.html#m-{e(x['name'])}'>{e(x['name'])}</a>" for x in top if x["relations"]) + "." if any(x["relations"] for x in top) else "."
        paras.append(mp)
    a = data["async"]
    bits = []
    if a["jobs"]:
        bits.append(f"{len(a['jobs'])} queued job{'s' if len(a['jobs']) != 1 else ''}")
    if a["events"]:
        bits.append(f"{len(a['events'])} event{'s' if len(a['events']) != 1 else ''} with {len(a['listeners'])} listener{'s' if len(a['listeners']) != 1 else ''}")
    if data["console"]["schedule"]:
        bits.append(f"{len(data['console']['schedule'])} scheduled task{'s' if len(data['console']['schedule']) != 1 else ''}")
    if bits:
        q = f"Background work: {', '.join(bits)}"
        if s["queue"]:
            q += f", on the <code>{e(s['queue'])}</code> queue connection"
        if data["packages"]["horizon"]:
            q += ", supervised by Horizon"
        paras.append(q + ".")
    if d["services"]:
        svc = ", ".join(f"<code>{e(x['name'])}</code> ({e(x['role_label'].lower())}{', PHP ' + e(x['php_version']) if x.get('php_version') and x['role'] == 'app' else ''})"
                        for x in d["services"] if not x.get("only_in"))
        paras.append(f"Locally it runs in Docker using <strong>{e(s['docker'])}</strong> with {len([x for x in d['services'] if not x.get('only_in')])} services: {svc}.")
    t = data["tooling"]["tests"]
    if t["files"]:
        paras.append(f"Tests use {e(s['testing'])}: {t['cases']} test cases in {t['files']} files.")
    g = data.get("git")
    if g and g.get("last_commit"):
        lc = g["last_commit"]
        paras.append(f"{g['contributors']} people committed in the last 12 months. The latest commit is “{e(lc['subject'])}” by {e(lc['author'])}, {e(rel_time(lc['date']))}.")
    return paras


def arch_mermaid(data):
    roles = Counter(c["role"] for c in data["classes"])
    routes = [r for r in data["routes"] if r.get("source") != "package (inferred)"]
    api = sum(1 for r in routes if r["uri"].startswith("/api"))
    fil = sum(1 for r in routes if r.get("action_type") == "filament")
    lines = ["flowchart LR", '  client(("Browser /<br/>API client"))', '  subgraph http["HTTP layer"]', "    direction TB",
             f'    routes["Routes<br/><small>{len(routes) - api - fil} web · {api} api{f" · {fil} Filament" if fil else ""}</small>"]',
             f'    mw["Middleware<br/><small>{len(data["middleware"]["aliases"])} aliases</small>"]']
    handlers = []
    if roles.get("controller"):
        handlers.append(f"{roles['controller']} controllers")
    if data["livewire"]["components"]:
        handlers.append(f"{len(data['livewire']['components'])} Livewire")
    if data["filament"]["resources"]:
        handlers.append(f"{len(data['filament']['resources'])} Filament resources")
    lines.append(f'    ctrl["Handlers<br/><small>{" · ".join(handlers) or "closures"}</small>"]')
    if roles.get("request"):
        lines.append(f'    req["Form requests<br/><small>{roles["request"]}</small>"]')
    lines.append("  end")
    ui = []
    if data["inertia_pages"]:
        ui.append(f"{len(data['inertia_pages'])} Inertia pages")
    nviews = sum(1 for v in data["views"].values() if v["kind"] != "volt")
    if nviews:
        ui.append(f"{nviews} Blade views")
    if ui:
        lines += ['  subgraph uil["UI"]', f'    ui["{"<br/>".join(ui)}"]', "  end"]
    lines += ['  subgraph dom["Domain"]', "    direction TB"]
    svc = roles.get("action", 0) + roles.get("service", 0) + roles.get("repository", 0)
    if svc:
        lines.append(f'    svc["Actions & services<br/><small>{svc}</small>"]')
    lines.append(f'    models["Models<br/><small>{len(data["models"])}</small>"]')
    if roles.get("policy"):
        lines.append(f'    pol["Policies<br/><small>{roles["policy"]}</small>"]')
    lines.append("  end")
    a = data["async"]
    has_async = a["jobs"] or a["events"] or data["console"]["schedule"]
    if has_async:
        lines += ['  subgraph bg["Background"]', "    direction TB"]
        if a["events"]:
            lines.append(f'    ev{{{{"Events → listeners<br/><small>{len(a["events"])} → {len(a["listeners"])}</small>"}}}}')
        if a["jobs"]:
            lines.append(f'    jobs[["Jobs<br/><small>{len(a["jobs"])}</small>"]]')
        if data["console"]["schedule"]:
            lines.append(f'    sch["Scheduler<br/><small>{len(data["console"]["schedule"])} tasks</small>"]')
        if a["mail"] or a["notifications"]:
            lines.append(f'    mailn["Mail & notifications<br/><small>{len(a["mail"]) + len(a["notifications"])}</small>"]')
        lines.append("  end")
    infra = {s["role"]: s for s in data["docker"]["services"] if not s.get("only_in")}
    s = data["stack"]
    db = infra.get("database")
    lines.append(f'  db[("{e(db["name"]) if db else e(s["db"] or "database")}<br/><small>database</small>")]')
    cache = infra.get("cache")
    if cache:
        lines.append(f'  cache[("{e(cache["name"])}<br/><small>cache · queue</small>")]')
    mail = infra.get("mail")
    if mail:
        lines.append(f'  mailsvc["{e(mail["name"])}<br/><small>mail catcher</small>"]')
    lines += ["  client --> routes --> mw --> ctrl"]
    if roles.get("request"):
        lines.append("  ctrl -.validates.-> req")
    if ui:
        lines.append("  ctrl --> ui")
    if svc:
        lines += ["  ctrl --> svc", "  svc --> models"]
    lines.append("  ctrl --> models")
    if roles.get("policy"):
        lines.append("  ctrl -.authorise.-> pol")
    lines.append("  models --> db")
    if a["events"]:
        lines.append("  ctrl -.dispatch.-> ev")
    if a["jobs"]:
        lines.append("  ctrl -.dispatch.-> jobs")
        if cache and (s["queue"] or "") == "redis":
            lines.append("  jobs --> cache")
    if data["console"]["schedule"] and a["jobs"]:
        lines.append("  sch --> jobs")
    if (a["mail"] or a["notifications"]) and has_async:
        if a["events"]:
            lines.append("  ev --> mailn")
        elif a["jobs"]:
            lines.append("  jobs --> mailn")
        if mail:
            lines.append("  mailn --> mailsvc")
    if cache and not a["jobs"]:
        lines.append("  ctrl -.cache · session.-> cache")
    return "\n".join(lines)


def start_reading(data):
    items = []
    if "bootstrap/app.php" in data["file_hashes"] and data["middleware"]["style"] == "bootstrap/app.php":
        items.append(("bootstrap/app.php", "How the app boots: routing files, middleware and exception handling in one place."))
    else:
        if "app/Http/Kernel.php" in data["file_hashes"]:
            items.append(("app/Http/Kernel.php", "Global middleware, middleware groups and route middleware aliases."))
        if "app/Providers/RouteServiceProvider.php" in data["file_hashes"]:
            items.append(("app/Providers/RouteServiceProvider.php", "Which route files load, with which prefix and middleware."))
    for f in ("routes/web.php", "routes/api.php"):
        if f in data["file_hashes"]:
            n = sum(1 for r in data["routes"] if r.get("file") == f)
            items.append((f, f"{n} routes defined directly here, the map of what users can do."))
    by_ctrl = Counter(r["controller"] for r in data["routes"] if r.get("controller") and r.get("source") == "static")
    for fqn, n in by_ctrl.most_common(2):
        c = next((x for x in data["classes"] if x["fqn"] == fqn), None)
        if c:
            items.append((c["file"], f"The busiest controller ({n} routes)."))
    deps = Counter(d for c in data["classes"] for d in c["deps"])
    top_models = sorted(data["models"].values(), key=lambda m: -(len(m["relations"]) * 2 + deps.get(m["fqn"], 0)))[:2]
    for m in top_models:
        items.append((m["file"], f"Core model: {len(m['relations'])} relationships, used by {deps.get(m['fqn'], 0)} classes."))
    for c in sorted((c for c in data["classes"] if c["role"] in ("action", "service", "repository")), key=lambda c: -deps.get(c["fqn"], 0))[:2]:
        if deps.get(c["fqn"]):
            items.append((c["file"], f"Shared business logic, used by {deps[c['fqn']]} classes."))
    if "app/Providers/AppServiceProvider.php" in data["file_hashes"]:
        items.append(("app/Providers/AppServiceProvider.php", "Boot-time wiring: bindings, gates, event listeners, model settings."))
    for p in data["filament"]["panels"]:
        if p.get("file"):
            items.append((p["file"], f"Filament panel “{p['id']}” configuration."))
    if data["tooling"].get("readme"):
        items.insert(0, (data["tooling"]["readme"]["file"], "The team's own introduction."))
    seen, out = set(), []
    for f, why in items:
        if f not in seen:
            seen.add(f)
            out.append((f, why))
    return out[:10]


def page_index(data, h, pages):
    s = data["stack"]
    roles = Counter(c["role"] for c in data["classes"])
    routes = [r for r in data["routes"] if r.get("source") != "package (inferred)"]
    tiles = [("routes.html", len(routes), "routes"), ("models.html", len(data["models"]), "models"),
             ("database.html", len(data["schema"]), "tables"), ("http.html", roles.get("controller", 0), "controllers")]
    if data["livewire"]["components"]:
        tiles.append(("livewire.html", len(data["livewire"]["components"]), "Livewire components"))
    if data["filament"]["resources"]:
        tiles.append(("filament.html", len(data["filament"]["resources"]), "Filament resources"))
    tiles.append(("events.html", len(data["async"]["jobs"]) + len(data["async"]["events"]), "jobs & events"))
    if data["docker"]["services"]:
        tiles.append(("docker.html", len([x for x in data["docker"]["services"] if not x.get("only_in")]), "Docker services"))
    tiles.append(("start.html#tests", data["tooling"]["tests"]["cases"], "test cases"))
    crit = sum(1 for i in data["insights"] if i["severity"] == "crit")
    warn = sum(1 for i in data["insights"] if i["severity"] == "warn")
    tiles.append(("insights.html", crit + warn, "issues to check"))
    tiles_html = '<div class="tiles">' + "".join(f'<a class="tile" href="{f}"><span class="v">{v}</span><span class="k">{e(k)}</span></a>' for f, v, k in tiles) + "</div>"
    body = [tiles_html]
    body.append(section("summary", "In plain words", '<div class="prose">' + "".join(f"<p>{p}</p>" for p in explain(data)) + "</div>"))
    stack_rows = [("Laravel", e(s["laravel"])), ("PHP", e(s["php"]) + (f' <span class="faint">(container runs {e(s["php_runtime"])})</span>' if s["php_runtime"] else "")),
                  ("UI", e(", ".join(s["frontend"]))), ("Assets", e(" + ".join(x for x in (s["bundler"], s["css"]) if x))),
                  ("Auth", e(", ".join(s["auth"]))), ("Database", code(s["db"]) if s["db"] else ""),
                  ("Cache / session", e(" / ".join(x for x in (s["cache"], s["session"]) if x))), ("Queue", code(s["queue"]) if s["queue"] else ""),
                  ("Mail", code(s["mail"]) if s["mail"] else ""), ("Broadcasting", code(s["broadcast"]) if s["broadcast"] else ""),
                  ("Search", code(s["search"]) if s["search"] else ""), ("Tests", e(s["testing"])), ("Dev environment", e(s["docker"] or "local PHP"))]
    notable = [(n, KNOWN_PACKAGES[n]) for n in list(data["packages"]["require"]) + list(data["packages"]["require_dev"]) if n in KNOWN_PACKAGES and n != "laravel/framework"]
    notable_html = "".join(f"<li><code>{e(n)}</code>: {e(d)}</li>" for n, d in notable[:16])
    body.append(section("stack", "Stack", f'<div class="split"><div class="card">{kv(stack_rows)}</div><div class="card"><h3>Notable packages</h3>'
                        f'<ul>{notable_html or "<li class=faint>None of the well-known packages.</li>"}</ul><p class="small"><a href="config.html#composer">All packages →</a></p></div></div>'))
    body.append(section("architecture", "Architecture at a glance", mermaid(h, arch_mermaid(data), "How a request flows through the code"),
                        "Boxes are layers of the codebase with the number of classes in each; dotted arrows are optional or asynchronous paths."))
    sr = start_reading(data)
    if sr:
        rows = "".join(f'<li><div class="step-body">{h.ref(f)}<p class="muted">{e(why)}</p></div></li>' for f, why in sr)
        body.append(section("start-reading", "Where to start reading", f'<ol class="steps">{rows}</ol>', "A suggested reading order for someone new to the codebase."))
    ch = data.get("changes") or {}
    if ch.get("summary"):
        body.append(section("recent", "Since your last look", callout("info", e(ch["summary"]), '<a href="changes.html">See what changed and the catch-up checklist →</a>')))
    top = [i for i in data["insights"] if i["severity"] in ("crit", "warn")][:5]
    if top:
        body.append(section("attention", "Worth a look", "".join(callout(i["severity"], e(i["title"]), e(i["detail"])) for i in top) +
                            '<p><a href="insights.html">All insights →</a></p>'))
    cards = "".join(f'<a class="card card-link" href="{f}"><h3>{e(t)}</h3><p>{e(desc)}</p></a>' for f, t, g, desc in PAGES if f in pages and f != "index.html")
    body.append(section("pages", "Explore", f'<div class="grid-3">{cards}</div>'))
    if data.get("notes"):
        body.append(details("Analysis notes", "<ul>" + "".join(f"<li>{e(n)}</li>" for n in data["notes"]) + "</ul>"))
    lede = e(data["meta"].get("description") or "") if data["meta"].get("description") and "skeleton" not in data["meta"]["description"].lower() else \
        f"A generated map of this Laravel codebase and its development environment, built from source in {data['meta'].get('seconds', '?')} s."
    return "Overview", lede, "".join(body)


# ---------------------------------------------------------------------------------------------- start

PORT_HINT = {"mail": "Mail inbox (Mailpit / MailHog)", "search": "Search dashboard", "db-ui": "Database UI", "storage": "Storage console",
             "websockets": "WebSocket server", "web": "The app", "proxy": "The app (via proxy)", "app": "The app", "assets": "Vite / Node dev server"}


def service_urls(data):
    out = []
    for s in data["docker"]["services"]:
        for p in s["ports"]:
            if not p["host"]:
                continue
            try:
                host_port, cport = int(p["host"]), int(str(p["container"]).split("-")[0])
            except ValueError:
                continue
            what = WEB_PORTS.get(cport) or DB_PORTS.get(cport) or ""
            http_like = cport in WEB_PORTS or (s["role"] in ("web", "app", "proxy", "mail", "search", "db-ui", "storage") and cport not in DB_PORTS)
            if s["role"] == "mail" and cport in (1025, 25, 587):
                http_like = False
            if s["role"] == "assets" or cport == 5173:
                what = "Vite dev server (assets; keep it running)"
            url = f"http://localhost{'' if host_port == 80 else ':' + str(host_port)}" if http_like else f"localhost:{host_port}"
            label = PORT_HINT.get(s["role"], s["role_label"]) if http_like else (what or s["role_label"])
            if s["role"] == "mail" and http_like:
                label = "Mail inbox: every email the app sends lands here"
            if s["role"] == "database":
                label = f"{what or 'Database'}: connect a GUI client here"
            out.append({"service": s["name"], "url": url, "label": label, "http": http_like, "raw": p["raw"]})
    return out


def page_start(data, h, pages):
    pre, d, loc, t = data["prefixes"], data["docker"], data.get("local") or {}, data["tooling"]
    body = []
    steps = []
    if not loc.get("env_exists", False):
        steps.append(("Create your environment file", "cp .env.example .env", "Laravel reads settings from .env; the example file holds safe defaults."))
    if d.get("sail") and not loc.get("vendor", False):
        php = (data["stack"]["php_runtime"] or "83").replace(".", "")
        steps.append(("Install PHP dependencies (first time, before Sail exists)",
                      f'docker run --rm -u "$(id -u):$(id -g)" -v "$(pwd):/var/www/html" -w /var/www/html laravelsail/php{php}-composer:latest composer install --ignore-platform-reqs',
                      "Sail itself lives in vendor/, so the very first install runs in a throwaway container."))
    if d["services"]:
        steps.append(("Start the containers", pre["up"], f"Starts {len([s for s in d['services'] if not s.get('only_in')])} services in the background. The first run builds images and takes a few minutes."))
    if not (d.get("sail") and not loc.get("vendor", False)):
        steps.append(("Install PHP dependencies", f"{pre['composer']} install", "Fills vendor/ from composer.lock."))
    if not loc.get("app_key"):
        steps.append(("Generate the app key", f"{pre['artisan']} key:generate", "Needed for encryption, sessions and cookies."))
    seeders = any(c["role"] == "seeder" for c in data["classes"])
    steps.append(("Create the database tables", f"{pre['artisan']} migrate" + (" --seed" if seeders else ""),
                  f"Runs {len(data['migrations'])} migrations" + (" and fills in demo data from the seeders." if seeders else ".")))
    if data["packages"]["npm"] or data["packages"]["npm_dev"]:
        steps.append(("Install JS dependencies and start Vite" if data["assets"]["bundler"] == "Vite" else "Install JS dependencies and build assets",
                      f"{pre['npm']} install && {pre['npm']} run dev", "Keep this running while you work so CSS/JS changes show up."))
    if data["filament"]["panels"]:
        steps.append(("Create an admin user for Filament", f"{pre['artisan']} make:filament-user", "Then log in at the panel URL below."))
    mk = [m for m in t["make"] if m["target"] in ("setup", "install", "init", "bootstrap", "start", "dev", "up")]
    extra = ""
    if mk or "setup" in t["composer_scripts"] or "dev" in t["composer_scripts"]:
        bits = [f"<code>make {e(m['target'])}</code>" for m in mk] + [f"<code>composer {x}</code>" for x in ("setup", "dev") if x in t["composer_scripts"]]
        extra = callout("info", "Shortcuts exist", "The project defines " + ", ".join(bits) + ". These may do several of the steps below in one go (see Scripts further down).")
    sl = "".join(f'<li><div class="step-body"><h4>{e(ti)}</h4>{cmd_box(c)}<p class="muted small">{e(why)}</p></div></li>' for ti, c, why in steps)
    body.append(section("run", "Run it locally", extra + f'<ol class="steps">{sl}</ol>',
                        f"Generated for <strong>{e(pre['mode'])}</strong>. Skip the steps you have already done."))
    urls = service_urls(data)
    app_url = data["env"]["matrix"] and next((r["example"] for r in data["env"]["matrix"] if r["key"] == "APP_URL"), None)
    for p in data["filament"]["panels"]:
        base = next((u["url"] for u in urls if u["http"] and u["label"].startswith("The app")), app_url or "http://localhost")
        urls.insert(0, {"service": "filament", "url": base.rstrip("/") + "/" + p["path"].strip("/"), "label": f"Filament “{p['id']}” panel", "http": True, "raw": ""})
    rows = [[f'<a href="{e(u["url"])}" class="mono">{e(u["url"])}</a>' if u["http"] else code(u["url"]), e(u["label"]), code(u["service"])] for u in urls]
    if app_url:
        rows.insert(0, [f'<span class="mono">{e(app_url)}</span>', "APP_URL in .env.example (used when generating links)", ""])
    body.append(section("urls", "Open in your browser", table(h, "t-urls", ["URL", "What", "Service"], rows, filter_=False, empty="No published ports found."),
                        "Ports published by the compose file, mapped to what they are for."))
    everyday = [("Start / stop", pre["up"]), ("", pre["down"]), ("Follow logs", pre["logs"]), ("Shell into the app container", pre["shell"]),
                ("Run artisan", f"{pre['artisan']} list"), ("Tinker (REPL)", pre["tinker"]), ("Run tests", pre["test"]),
                ("Reset the database", f"{pre['artisan']} migrate:fresh --seed"), ("Clear all caches", f"{pre['artisan']} optimize:clear"),
                ("Work the queue", f"{pre['artisan']} queue:work" if not data["packages"]["horizon"] else f"{pre['artisan']} horizon"),
                ("Run the scheduler", f"{pre['artisan']} schedule:work"), ("Rebuild images", pre["build"]), ("Container status", pre["ps"])]
    rows = [[e(a), cmd_box(c)] for a, c in everyday if c]
    body.append(section("commands", "Everyday commands", table(h, "t-cmds", ["Task", "Command"], rows, filter_=False)))
    st = []
    if loc:
        if not loc["env_exists"]:
            st.append(("crit", "No .env file", "Copy .env.example to .env."))
        else:
            if loc["env_missing"]:
                st.append(("warn", f"Your .env is missing {len(loc['env_missing'])} key(s) from .env.example", ", ".join(f"<code>{e(k)}</code>" for k in loc["env_missing"])))
            else:
                st.append(("ok", ".env has every key from .env.example", ""))
            if loc["env_extra"]:
                st.append(("info", f"{len(loc['env_extra'])} key(s) in your .env aren't in .env.example", ", ".join(f"<code>{e(k)}</code>" for k in loc["env_extra"])))
            st.append(("ok" if loc["app_key"] else "warn", "APP_KEY is set" if loc["app_key"] else "APP_KEY is empty", "" if loc["app_key"] else f"Run <code>{e(pre['artisan'])} key:generate</code>."))
        st.append(("ok" if loc["vendor"] else "warn", "vendor/ installed" if loc["vendor"] else "vendor/ is missing", "" if loc["vendor"] else f"Run <code>{e(pre['composer'])} install</code>."))
        if loc["composer_out_of_sync"]:
            st.append(("warn", f"{len(loc['composer_out_of_sync'])} PHP package(s) differ from composer.lock", ", ".join(e(x["name"]) for x in loc["composer_out_of_sync"][:12])))
        if data["packages"]["npm"] or data["packages"]["npm_dev"]:
            st.append(("ok" if loc["node_modules"] else "warn", "node_modules/ installed" if loc["node_modules"] else "node_modules/ is missing", ""))
            if loc["npm_out_of_sync"]:
                st.append(("warn", f"{len(loc['npm_out_of_sync'])} JS package(s) differ from package-lock.json", ", ".join(e(x["name"]) for x in loc["npm_out_of_sync"][:12])))
        if loc.get("containers") is not None:
            running = [c for c in loc["containers"] if c.get("state") == "running"]
            known = [s["name"] for s in d["services"] if not s.get("only_in") and not s.get("profiles")]
            down = [n for n in known if n not in {c["service"] for c in running}]
            st.append(("ok" if not down else "warn", f"{len(running)} of {len(known)} containers running", ("Not running: " + ", ".join(f"<code>{e(x)}</code>" for x in down)) if down else ""))
        elif loc.get("docker_cli") is False and d["services"]:
            st.append(("info", "Docker CLI not found on this machine", "Container status was not checked."))
    g = data.get("git")
    if g:
        st.append(("info", f"On branch <code>{e(g['branch'])}</code>" + (f" tracking <code>{e(g['upstream'])}</code>" if g["upstream"] else " (no upstream)"),
                   (f"{g['behind']} behind, {g['ahead']} ahead." if g["upstream"] else "") + (f" Last fetch {e(rel_time(g['last_fetch']))}." if g.get("last_fetch") else "")))
        if g["behind"]:
            st.append(("warn", f"You are {g['behind']} commit(s) behind", "Run <code>git pull</code>."))
        if g["dirty"]:
            st.append(("info", f"{len(g['dirty'])} uncommitted change(s) in your working tree", ", ".join(f"<code>{e(x['file'])}</code>" for x in g["dirty"][:8]) + (" …" if len(g["dirty"]) > 8 else "")))
        if g["stashes"]:
            st.append(("info", f"{g['stashes']} stash(es) saved", "<code>git stash list</code>"))
    rt = data.get("runtime")
    if rt and rt.get("migrations") is not None:
        pend = [m for m in rt["migrations"] if m["status"] == "Pending"]
        st.append(("warn" if pend else "ok", f"{len(pend)} pending migration(s)" if pend else "Database is migrated", ""))
    for err in (rt or {}).get("errors", []):
        st.append(("info", "Live check failed", e(err)))
    if not rt:
        st.append(("info", "Live checks were skipped", "Re-run with <code>--artisan auto</code> while the containers are up to add real routes, pending migrations and app info."))
    sl = "".join(f'<li><span class="dot {k}"></span><div><strong>{t_}</strong>{f"<p class=muted>{dsc}</p>" if dsc else ""}</div></li>' for k, t_, dsc in st)
    body.append(section("machine", "Your machine right now", f'<ul class="status-list">{sl}</ul>', "Checked when this map was generated."))
    sc = []
    if t["composer_scripts"]:
        sc.append("<h3>composer scripts</h3>" + table(h, "t-cs", ["Script", "Runs"], [[cmd_box(f"composer {k}"), esc_list(v, mono=True)] for k, v in t["composer_scripts"].items()], filter_=False))
    if t["npm_scripts"]:
        sc.append("<h3>npm scripts</h3>" + table(h, "t-ns", ["Script", "Runs"], [[cmd_box(f"npm run {k}"), code(v)] for k, v in t["npm_scripts"].items()], filter_=False))
    if t["make"]:
        sc.append("<h3>Makefile targets</h3>" + table(h, "t-mk", ["Target", "Description", "First step"], [[cmd_box(f"make {m['target']}"), e(m["desc"]), code(m["recipe"]) if m["recipe"] else ""] for m in t["make"]], filter_=False))
    if sc:
        body.append(section("scripts", "Scripts", '<div class="sub">' + "".join(sc) + "</div>", "Shortcuts the team already defined. Prefer these over ad-hoc commands."))
    q = [[e(x["tool"]), e(x["kind"]), code(x["file"]), cmd_box(x["command"]) if x["command"] else "", e(x["extra"])] for x in t["quality"]]
    ci = []
    for wf in t["ci"]:
        jobs = "".join(f'<li><strong>{e(j["name"])}</strong> <span class="faint">{e(j["runs_on"])}</span>'
                       + (f' <span class="faint">services: {e(", ".join(j["services"]))}</span>' if j["services"] else "")
                       + "<ul>" + "".join(f'<li class="mono small">{e(s.get("run") or s.get("uses"))}</li>' for s in j["steps"] if s.get("run") or not str(s.get("uses", "")).startswith(("actions/checkout", "actions/cache"))) + "</ul></li>"
                       for j in wf["jobs"])
        ci.append(details(f'{e(wf["name"])} <span class="faint mono small">{e(wf["file"])}</span> <span class="faint small">on {e(", ".join(map(str, wf["triggers"])))}</span>',
                          f"<ul>{jobs or '<li class=faint>No jobs parsed.</li>'}</ul>"))
    qbody = (table(h, "t-q", ["Tool", "Checks", "Config", "Run it", ""], q, filter_=False, empty="No code-quality tools detected.") +
             ("<h3>Continuous integration</h3>" + "".join(ci) if ci else callout("info", "No CI pipeline found", "Nothing in .github/workflows, .gitlab-ci.yml or similar.")))
    if t["deploy"]:
        qbody += "<h3>Deployment</h3>" + table(h, "t-dep", ["File", "What"], [[code(x["file"]), e(x["what"])] for x in t["deploy"]], filter_=False)
    body.append(section("quality", "Quality gates & CI", qbody, "What has to pass before code is merged. Run the same commands locally first."))
    tests = t["tests"]
    pu = t.get("phpunit") or {}
    tb = kv([("Framework", e(data["stack"]["testing"])), ("Test files", str(tests["files"])), ("Test cases", str(tests["cases"])),
             ("By folder", e(", ".join(f"{k}: {v}" for k, v in tests["by_dir"].items()))), ("Suites", e(", ".join(pu.get("suites", [])))),
             ("Test environment", e(", ".join(f"{k}={v}" for k, v in (pu.get("env") or {}).items() if k in ("DB_CONNECTION", "DB_DATABASE", "CACHE_STORE", "CACHE_DRIVER", "QUEUE_CONNECTION", "MAIL_MAILER", "SESSION_DRIVER", "APP_ENV"))))])
    tl = "".join(details(f'<span class="mono small">{e(x["file"])}</span> <span class="faint small">{len(x["cases"])} cases</span>', esc_list(x["cases"], limit=40)) for x in tests["list"])
    body.append(section("tests", "Tests", f'<div class="card">{tb}{cmd_box(pre["test"])}</div>{tl}'))
    docs = t["docs"]
    if docs or t.get("readme"):
        dbody = ""
        if t.get("readme"):
            dbody += details(f"{e(t['readme']['file'])} <span class='faint small'>rendered</span>", md_to_html(t["readme"]["text"]), open_=True)
        if docs:
            dbody += table(h, "t-docs", ["Document", "Title", "Lines"], [[h.ref(x["file"]), e(x["title"]), (str(x["lines"]), x["lines"])] for x in docs], filter_=False)
        body.append(section("docs", "Project docs", dbody))
    g = data.get("git")
    if g and g.get("owners"):
        rows = [[e(area), ", ".join(f"{e(o['author'])} <span class='faint'>({o['commits']})</span>" for o in owners)]
                for area, owners in sorted(g["owners"].items(), key=lambda kv_: -sum(o["commits"] for o in kv_[1]))]
        body.append(section("owners", "Who knows what", table(h, "t-own", ["Area", "Most commits in the last 12 months"], rows, filter_=False),
                            "Good people to ask about each part of the code. Based on git history, so it misses pairing and reviews."))
    return "Getting started", "How to get this app running on your machine, what to open, and what state your checkout is in.", "".join(body)


# ---------------------------------------------------------------------------------------------- changes

def page_changes(data, h, pages):
    ch = data.get("changes") or {}
    body = []
    base = ch.get("baseline")
    how = ('Compare against something else with <code>--since main</code>, <code>--since v2.3.0</code>, <code>--since "2026-09-01"</code> '
           'or <code>--since "3 weeks ago"</code>. Each run is saved, so the next run compares with this one.')
    if not base:
        body.append(callout("info", "No baseline yet", "This is the first map of this checkout and git history wasn't available for a comparison. " + how))
        return "What changed", "Structural changes, commits and a catch-up checklist.", "".join(body)
    body.append(callout("info", f"Compared with {e(base['label'])}", e(base.get("detail", "")) + " " + how))
    steps = data.get("catch_up") or []
    if steps:
        sl = []
        for s in steps:
            extra = ""
            if s.get("keys"):
                extra = '<p class="small">' + ", ".join(f"<code>{e(k)}</code>" for k in s["keys"]) + "</p>"
            if s.get("items"):
                extra += esc_list(s["items"], mono=True, limit=10)
            sl.append(f'<li><div class="step-body"><h4>{e(s["title"])}</h4>{cmd_box(s["command"])}<p class="muted small">{e(s["why"])}</p>{extra}</div></li>')
        body.append(section("catch-up", "Catch-up checklist", f'<ol class="steps">{"".join(sl)}</ol>',
                            "Do these in order to get your environment in step with the code."))
    act = ch.get("git")
    if act and not act["commits"] and not act["files"]:
        body.append(callout("info", "No new commits since the baseline", "Only your working tree differs (see below)."))
        act = None
    if act:
        n = len(act["commits"])
        auth = ", ".join(f"{e(a)} ({c})" for a, c in act["authors"][:8])
        intro = f"<p><strong>{n} commit{'s' if n != 1 else ''}</strong>" + (f" by {auth}" if auth else "") + "."
        if act["prs"]:
            intro += f" Pull/merge requests mentioned: {', '.join('#' + e(p) for p in act['prs'][:30])}."
        intro += "</p>"
        mx = max([c for _, c in act["areas"]] or [1])
        bars = "".join(f'<div class="bar-row"><span>{e(a)}</span><div class="bar" style="width:{max(2, int(c / mx * 100))}%"></div><span class="num">{c}</span></div>' for a, c in act["areas"])
        rows = [[code(c["sha"]), (e(c["date"][:10]), c["date"]), e(c["author"]), e(c["subject"]) + (" " + badge("merge") if c["merge"] else "")] for c in act["commits"]]
        frows = [[badge({"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied"}.get(f["status"], f["status"]),
                        {"A": "ok", "D": "crit", "M": "info"}.get(f["status"], "")), h.ref(f["file"]) + (f' <span class="faint small">from {e(f["old"])}</span>' if f.get("old") else ""),
                  e(f["area"]), (f'<span class="num" style="color:var(--ok)">+{e(f["plus"])}</span> <span class="num" style="color:var(--crit)">−{e(f["minus"])}</span>', f["plus"] or 0)] for f in act["files"]]
        body.append(section("activity", "Git activity", intro + (f'<div class="card"><h3>Files changed by area</h3>{bars}</div>' if bars else "") +
                            "<h3>Commits</h3>" + table(h, "t-commits", ["Commit", "Date", "Author", "Message"], rows, empty="No commits in this range.") +
                            "<h3>Files</h3>" + table(h, "t-files", ["Change", "File", "Area", "Lines"], frows, empty="No committed file changes.",
                                                     quick=[(a, a) for a, _ in act["areas"][:6]])))
    g = data.get("git") or {}
    if g.get("dirty"):
        rows = [[badge(x["status"]), h.ref(x["file"]), e(file_area(x["file"]))] for x in g["dirty"]]
        body.append(section("working-tree", "Uncommitted changes", table(h, "t-dirty", ["Status", "File", "Area"], rows),
                            "Local edits and untracked files in your working tree right now (?? means untracked)."))
    d = ch.get("diff")
    if d:
        parts = []

        def block(title, rows, headers, empty=None):
            if rows:
                parts.append(f"<h3>{e(title)}</h3>" + table(h, None, headers, rows, filter_=len(rows) > 8))

        r = d["routes"]
        block("Routes added", [[methods_html(x["key"].split(" ", 1)[0].split("|")), code(x["key"].split(" ", 1)[1]), e(x.get("name") or ""), f'<span class="mono small">{e(short(x.get("action") or ""))}</span>'] for x in r["added"]], ["Method", "URI", "Name", "Action"])
        block("Routes removed", [[methods_html(x["key"].split(" ", 1)[0].split("|")), code(x["key"].split(" ", 1)[1]), e(x.get("name") or ""), f'<span class="mono small">{e(short(x.get("action") or ""))}</span>'] for x in r["removed"]], ["Method", "URI", "Name", "Action"])
        block("Routes changed", [[code(x["key"]), "<br>".join(f"{e(k)}: <s>{e(fmt_val(x['old'][k]))}</s> → {e(fmt_val(x['new'][k]))}" for k in ("name", "action", "middleware") if x["old"].get(k) != x["new"].get(k))] for x in r["changed"]], ["Route", "What changed"])
        t = d["tables"]
        block("New tables", [[code(x["table"]), e(", ".join(x["columns"][:14]))] for x in t["added"]], ["Table", "Columns"])
        block("Dropped tables", [[code(x)] for x in t["removed"]], ["Table"])
        block("Table changes", [[code(x["table"]), esc_list(["+ " + c for c in x["added"]] + ["− " + c for c in x["removed"]] + ["~ " + c for c in x["changed"]], mono=True)] for x in t["changed"]], ["Table", "Columns"])
        block("New migrations", [[code(x)] for x in d["migrations"]["added"]], ["Migration"])
        block("Removed migrations", [[code(x)] for x in d["migrations"]["removed"]], ["Migration"])
        m = d["models"]
        block("New models", [[cls_link(x, "model")] for x in m["added"]], ["Model"])
        block("Removed models", [[code(short(x))] for x in m["removed"]], ["Model"])
        block("Model changes", [[cls_link(x["model"], "model"), esc_list([f"+ {y}" for y in x["relations_added"]] + [f"− {y}" for y in x["relations_removed"]] +
                                                                         [f"+ fillable {y}" for y in x["fillable_added"]] + [f"− fillable {y}" for y in x["fillable_removed"]] +
                                                                         [f"cast {y}" for y in x["casts_changed"]], mono=True)] for x in m["changed"]], ["Model", "Changes"])
        c = d["classes"]
        block("New classes", [[f'<span class="mono">{e(short(x["fqn"]))}</span>', role_chip(x["role"]), h.ref(x["file"])] for x in sorted(c["added"], key=lambda x: (ROLE_ORDER.index(x["role"]) if x["role"] in ROLE_ORDER else 99, x["fqn"]))], ["Class", "Role", "File"])
        block("Removed classes", [[f'<span class="mono">{e(short(x["fqn"]))}</span>', role_chip(x["role"]), e(x["file"])] for x in c["removed"]], ["Class", "Role", "File"])
        ev = d["env"]
        block("New keys in .env.example", [[code(k), badge("missing from your .env", "warn") if k in ((data.get("local") or {}).get("env_missing") or []) else ""] for k in ev["added"]], ["Key", ""])
        block("Keys removed from .env.example", [[code(k)] for k in ev["removed"]], ["Key"])
        for key, title in (("composer", "PHP packages"), ("npm", "JS packages")):
            p = d[key]
            rows = [[code(x["name"]), badge("added", "ok"), e(x["version"])] for x in p["added"]] + \
                   [[code(x), badge("removed", "crit"), ""] for x in p["removed"]] + \
                   [[code(x["name"]), badge("changed", "info"), f"{e(x['old'])} → {e(x['new'])}"] for x in p["changed"]]
            block(title, rows, ["Package", "", "Version"])
        dk = d["docker"]
        rows = [[code(x), badge("added", "ok"), ""] for x in dk["added"]] + [[code(x), badge("removed", "crit"), ""] for x in dk["removed"]] + \
               [[code(x["service"]), badge("changed", "info"), "<br>".join(f"{e(k)}: {e(fmt_val(x['old'].get(k)))} → {e(fmt_val(x['new'].get(k)))}" for k in x["new"] if x["old"].get(k) != x["new"].get(k))] for x in dk["changed"]] + \
               [[code(x), badge("Dockerfile changed", "info"), ""] for x in d["dockerfiles"]["changed"] + d["dockerfiles"]["added"]]
        block("Docker", rows, ["Service / file", "", "Detail"])
        for key, title in (("schedule", "Scheduled tasks"), ("commands", "Console commands"), ("listeners", "Event → listener wiring"),
                           ("livewire", "Livewire components"), ("filament", "Filament resources"), ("inertia_pages", "Inertia pages"), ("views", "Blade views")):
            x = d[key]
            rows = [[e(v), badge("added", "ok")] for v in x["added"]] + [[e(v), badge("removed", "crit")] for v in x["removed"]]
            block(title, rows, ["Item", ""])
        mw = d["middleware"]
        block("Middleware aliases", [[code(k), badge("added", "ok")] for k in mw["added"]] + [[code(k), badge("removed", "crit")] for k in mw["removed"]] + [[code(k), badge("changed", "info")] for k in mw["changed"]], ["Alias", ""])
        f = d["files"]
        if f["changed"] or f["added"] or f["removed"]:
            rows = [[badge("modified", "info"), h.ref(x), e(file_area(x))] for x in f["changed"]] + [[badge("added", "ok"), h.ref(x), e(file_area(x))] for x in f["added"]] + \
                   [[badge("deleted", "crit"), e(x), e(file_area(x))] for x in f["removed"]]
            parts.append(details(f"All changed source files ({len(rows)})", table(h, "t-srcf", ["Change", "File", "Area"], rows)))
        body.append(section("structure", "What changed in the application", "".join(parts) or '<p class="empty">No structural changes: same routes, models, schema, packages and Docker setup.</p>',
                            "Computed by comparing the two maps, so it also covers uncommitted work."))
    return "What changed", "What's different since the baseline, and what you need to do about it.", "".join(body)


# ---------------------------------------------------------------------------------------------- routes

def action_html(r, roles):
    t = r.get("action_type")
    if t in ("controller", "livewire", "filament") and r.get("controller"):
        role = roles.get(r["controller"], "controller" if t == "controller" else t)
        m = r.get("method")
        link = cls_link(r["controller"], role)
        return link + (f'<span class="mono">@{e(m)}</span>' if m and t == "controller" else "") + (" " + badge("Livewire") if t == "livewire" else "")
    if t == "closure":
        return '<span class="faint">Closure</span>'
    return f'<span class="mono small">{e(r.get("action") or t)}</span>'


def route_tree(routes):
    tree = {}
    for r in routes:
        node = tree
        segs = [s for s in r["uri"].strip("/").split("/") if s] or ["/"]
        for s in segs:
            node = node.setdefault(s, {})
        node.setdefault("__routes__", []).append(r)

    def count(n):
        return len(n.get("__routes__", [])) + sum(count(v) for k, v in n.items() if k != "__routes__")

    def render(n, depth):
        out = []
        for r in n.get("__routes__", []):
            out.append(f'<li class="leaf">{methods_html(r["methods"])}<span class="faint">{e(r.get("name") or "")}</span></li>')
        for k in sorted(x for x in n if x != "__routes__"):
            child = n[k]
            c = count(child)
            inner = render(child, depth + 1)
            label = f'<span class="seg">/{e(k)}</span> <span class="faint">{c}</span>'
            out.append(f'<li><details{" open" if depth < 1 else ""}><summary>{label}</summary><ul>{inner}</ul></details></li>')
        return "".join(out)

    return f'<ul class="tree">{render(tree, 0)}</ul>'


def page_routes(data, h, pages):
    roles = {c["fqn"]: c["role"] for c in data["classes"]}
    routes = data["routes"]
    src = "artisan route:list (live)" if (data.get("runtime") or {}).get("routes") else "static analysis of the route files"
    groups = Counter((r.get("group") or "—").split(":")[0] for r in routes)
    reg = "<ul>" + "".join(f"<li>{e(x)}</li>" for x in data["route_registration"]) + "</ul>" if data["route_registration"] else ""
    body = [callout("info", f"{len(routes)} routes from {e(src)}",
                    reg + ("Package routes marked <em>inferred</em> are guessed from installed packages; run with <code>--artisan auto</code> for the exact list." if any(r.get("source") == "package (inferred)" for r in routes) else ""))]
    rows = []
    traced = (data.get("calls") or {}).get("routes") or {}
    ridx = {id(r): i for i, r in enumerate(routes)}
    for r in sorted(routes, key=lambda r: (r["uri"], r["methods"])):
        src_cell = h.ref(r["file"], r["line"]) if r.get("file") else f'<span class="faint small">{e(r.get("source"))}</span>'
        i = ridx[id(r)]
        trace_link = f' <a class="small" href="trace.html#r-{i}" title="Follow this request">trace →</a>' if i in traced and "trace.html" in pages else ""
        rows.append([(methods_html(r["methods"]), "|".join(r["methods"])), f'<span class="mono">{e(r["uri"])}</span>' + (f' <span class="faint small">{e(r["domain"])}</span>' if r.get("domain") else ""),
                     f'<span class="mono small">{e(r.get("name") or "")}</span>', action_html(r, roles) + trace_link,
                     f'<span class="mono small">{e(", ".join(r["middleware"]))}</span>', e(r.get("group") or ""), src_cell])
    quick = [(g, g) for g, _ in groups.most_common(6) if g != "—"] + [("POST", "POST"), ("DELETE", "DELETE"), ("auth", "auth")]
    body.append(section("all", "All routes", table(h, "t-routes", ["Method", "URI", "Name", "Handler", "Middleware", "Group", "Defined in"], rows, quick=quick,
                                                     placeholder="Filter: try “api post”, “admin”, “auth:sanctum”…")))
    body.append(section("tree", "URL tree", route_tree(routes), "The same routes grouped by path segment."))
    by_c = defaultdict(list)
    for r in routes:
        if r.get("controller") and r.get("action_type") == "controller":
            by_c[r["controller"]].append(r)
    rows = [[cls_link(c, roles.get(c, "controller")), (str(len(rs)), len(rs)), esc_list(sorted({r.get("method") or "" for r in rs}), mono=True)] for c, rs in sorted(by_c.items(), key=lambda x: -len(x[1]))]
    body.append(section("by-controller", "By controller", table(h, "t-byc", ["Controller", "Routes", "Actions"], rows)))
    mwc = Counter(m for r in routes for m in r["middleware"])
    rows = [[code(m), (str(n), n), e(data["middleware"]["aliases"].get(m.split(":")[0], ""))] for m, n in mwc.most_common()]
    body.append(section("middleware-usage", "Middleware in use", table(h, "t-mwu", ["Middleware", "Routes", "Class"], rows), "How often each middleware (with its parameters) is applied to a route."))
    chans = data["console"]["channels"]
    if chans:
        rows = [[code(c["name"]), e(c["handler"]), h.ref(c["file"], c["line"])] for c in chans]
        body.append(section("channels", "Broadcast channels", table(h, "t-ch", ["Channel", "Authorised by", "Defined in"], rows), "Private and presence channels the frontend can subscribe to."))
    return "Routes", "Every URL the application answers, which code handles it and which middleware runs first.", "".join(body)


# ---------------------------------------------------------------------------------------------- http

def page_http(data, h, pages):
    mw, http = data["middleware"], data["http"]
    d = data["docker"]
    body = []
    web = next((s for s in d["services"] if s["role"] in ("web", "proxy") and not s.get("only_in")), None)
    app = d.get("app_service")
    lines = ["flowchart LR", '  b(("Browser"))']
    prev = "b"
    if web:
        port = next((p["host"] for p in web["ports"] if p["host"]), "")
        lines.append(f'  w["{e(web["name"])}<br/><small>web server{" :" + e(port) if port else ""}</small>"]')
        lines.append(f"  {prev} --> w")
        prev = "w"
    if app:
        lines.append(f'  a["{e(app)}<br/><small>PHP container</small>"]')
        lines.append(f"  {prev} --> a")
        prev = "a"
    lines += ['  i["public/index.php"]', f"  {prev} --> i",
              f'  g["Global middleware<br/><small>{len(mw["global"])} classes</small>"]', "  i --> g",
              '  r{"Router<br/><small>match URI</small>"}', "  g --> r"]
    for grp in [x for x in mw["groups"] if x in ("web", "api")]:
        lines.append(f'  mg_{grp}["{grp} group<br/><small>{len(mw["groups"][grp])} middleware</small>"]')
        lines.append(f'  r -->|"{grp} routes"| mg_{grp}')
        lines.append(f"  mg_{grp} --> rm")
    lines += ['  rm["Route middleware<br/><small>auth, can:, throttle…</small>"]', '  c["Controller action<br/><small>or Livewire / closure</small>"]', "  rm --> c",
              '  resp(["Response<br/><small>view · JSON · redirect</small>"])', "  c --> resp"]
    if not [x for x in mw["groups"] if x in ("web", "api")]:
        lines.append("  r --> rm")
    body.append(section("lifecycle", "Request lifecycle", mermaid(h, "\n".join(lines), "From the browser to your controller"),
                        "Each request passes through the global middleware, then its route group's middleware, then any route-specific middleware."))
    parts = []
    if mw["framework_defaults"]:
        parts.append(callout("info", "Laravel 11+ middleware", "Global and group middleware below combine the framework defaults with the changes made in <code>bootstrap/app.php</code>."))
    if mw["notes"]:
        parts.append("<ul>" + "".join(f"<li>{e(n)}</li>" for n in mw["notes"]) + "</ul>")
    parts.append("<h3>Global (every request)</h3>" + esc_list([short(x) for x in mw["global"]], mono=True, limit=30))
    for gname, items in mw["groups"].items():
        parts.append(f"<h3>{e(gname)} group</h3>" + esc_list([short(x) if "\\" in x else x for x in items], mono=True, limit=30))
    used = Counter(m.split(":")[0] for r in data["routes"] for m in r["middleware"])
    rows = [[code(a), f'<span class="mono small" title="{e(c)}">{e(short(c))}</span>', (str(used.get(a, 0)), used.get(a, 0)),
             badge("app") if c.startswith("App\\") else ""] for a, c in sorted(mw["aliases"].items())]
    parts.append("<h3>Aliases (usable in routes)</h3>" + table(h, "t-alias", ["Alias", "Class", "Routes using it", ""], rows))
    body.append(section("middleware", "Middleware", "".join(parts), f"Configured in <code>{e(mw['style'] or 'framework defaults')}</code>."))
    cparts = []
    for c in sorted(http["controllers"], key=lambda c: c["name"]):
        if not c["actions"] and c["abstract"]:
            continue
        rows = []
        for a in c["actions"]:
            uses = []
            if a["requests"]:
                uses.append("validates " + ", ".join(f"<code>{e(x)}</code>" for x in a["requests"]))
            if a["models"]:
                uses.append("models " + ", ".join(f"<a href='models.html#m-{e(x)}'>{e(x)}</a>" for x in a["models"]))
            if a["services"]:
                uses.append("calls " + ", ".join(f"<code>{e(x)}</code>" for x in a["services"]))
            if a["dispatches"]:
                uses.append("dispatches " + ", ".join(f"<code>{e(x)}</code>" for x in a["dispatches"]))
            if a["authorizes"]:
                uses.append("checks authorisation")
            ret = a["returns"][:]
            out = ", ".join(e(x) for x in ret)
            if a["pages"]:
                out += ": " + ", ".join(f"<code>{e(x)}</code>" for x in a["pages"])
            elif a["views"]:
                out += ": " + ", ".join(f"<code>{e(x)}</code>" for x in a["views"])
            ri = next((i for i, r in enumerate(data["routes"]) if r.get("controller") == c["fqn"] and (r.get("method") or "__invoke") == a["name"]
                       and i in ((data.get("calls") or {}).get("routes") or {})), None)
            tl = f' <a class="small" href="trace.html#r-{ri}">trace →</a>' if ri is not None and "trace.html" in pages else ""
            rows.append([f'<span class="mono">{e(a["name"])}()</span>' + tl + (f' <span class="faint small">{a["lines"]} lines</span>' if a["lines"] > 30 else ""),
                         esc_list(a["routes"], mono=True, empty="no route"), "<br>".join(uses) or '<span class="faint">—</span>', out or '<span class="faint">—</span>'])
        summ = (f'<span class="mono">{e(c["name"])}</span> <span class="faint small">{len(c["actions"])} actions · {c["loc"]} lines</span>')
        inner = (f'<p class="small">{h.ref(c["file"], c["line"])}{" · " + e(c["doc"]) if c["doc"] else ""}</p>' +
                 table(h, None, ["Action", "Route", "Uses", "Returns"], rows, filter_=False, sort=False, empty="No public actions."))
        cparts.append(f'<div id="c-{e(c["name"])}">{details(summ, inner)}</div>')
    body.append(section("controllers", "Controllers", "".join(cparts) or '<p class="empty">No controllers.</p>',
                        "What each action validates, touches and returns, read from the source."))
    if http["requests"]:
        rows = [[f'<span class="mono">{e(r["name"])}</span>', esc_list(r["fields"], mono=True, limit=20), code(r["authorize"]), esc_list(r["used_by"], mono=True), h.ref(r["file"])] for r in http["requests"]]
        body.append(section("requests", "Form requests", table(h, "t-req", ["Request", "Validated fields", "authorize()", "Used by", "File"], rows)))
    if http["resources"]:
        rows = [[f'<span class="mono">{e(r["name"])}</span>', esc_list(r["fields"], mono=True, limit=24), esc_list(r["used_by"], mono=True), h.ref(r["file"])] for r in http["resources"]]
        body.append(section("resources", "API resources", table(h, "t-res", ["Resource", "JSON fields", "Used by", "File"], rows)))
    if http["policies"]:
        rows = [[f'<span class="mono">{e(p["name"])}</span>', f"<a href='models.html#m-{e(p['model'])}'>{e(p['model'])}</a>" if p["model"] else '<span class="faint">?</span>',
                 esc_list(p["abilities"], mono=True), h.ref(p["file"])] for p in http["policies"]]
        body.append(section("policies", "Policies", table(h, "t-pol", ["Policy", "Model", "Abilities", "File"], rows), "Authorisation rules, used via $this->authorize(), Gate, @can or the can: middleware."))
    return "HTTP layer", "How a request travels through middleware into controllers, and what each controller action does.", "".join(body)


# ---------------------------------------------------------------------------------------------- models

def model_mermaid(models):
    lines = ["flowchart LR"]
    names = {fqn: m["name"] for fqn, m in models.items()}
    for fqn, m in models.items():
        lines.append(f'  {mm_id(m["name"])}["<b>{mm_label(m["name"])}</b><br/><small>{mm_label(m["table"])}</small>"]')
    edges = {}
    for fqn, m in models.items():
        for r in m["relations"]:
            rel = r.get("related")
            t = r["type"]
            if t == "morphTo":
                continue
            if rel not in names:
                continue
            a, b = m["name"], names[rel]
            if t in ("hasMany", "morphMany"):
                key, card = (a, b, "1:N"), r["name"]
            elif t in ("hasOne", "morphOne"):
                key, card = (a, b, "1:1"), r["name"]
            elif t == "belongsTo":
                key, card = (b, a, "1:N"), r["name"]
            elif t in ("belongsToMany", "morphToMany", "morphedByMany"):
                x, y = sorted([a, b])
                key, card = (x, y, "N:M"), r["name"]
            elif t in ("hasManyThrough", "hasOneThrough"):
                key, card = (a, b, "via"), r["name"]
            else:
                continue
            edges.setdefault(key, []).append(card)
    merged = {}
    for (a, b, card), labels in edges.items():
        if card == "1:1" and (a, b, "1:N") in edges:
            merged.setdefault((a, b, "1:N"), []).extend(labels)
            continue
        merged.setdefault((a, b, card), []).extend(labels)
    for (a, b, card), labels in merged.items():
        arrow = "-.->" if card == "via" else ("<-->" if card == "N:M" else "-->")
        lab = f"{card} · " + ", ".join(sorted(set(labels)))
        lines.append(f'  {mm_id(a)} {arrow}|"{mm_label(lab)}"| {mm_id(b)}')
    return "\n".join(lines)


def page_models(data, h, pages):
    models = data["models"]
    body = []
    if not models:
        return "Models", "Eloquent models.", '<p class="empty">No Eloquent models found.</p>'
    if len(models) <= 70:
        body.append(section("diagram", "Relationship map", mermaid(h, model_mermaid(models), "Models and how they relate"),
                            "Arrows point from the “one” side to the “many” side. Labels give the cardinality and the relationship method names."))
    else:
        nodes = [{"id": m["fqn"], "l": m["name"], "k": "model", "kl": "Model", "sub": m["table"], "f": m["file"], "u": f"#m-{m['name']}"} for m in models.values()]
        edges = [{"s": m["fqn"], "t": r["related"], "k": r["type"]} for m in models.values() for r in m["relations"] if r.get("related") in models]
        body.append(section("diagram", "Relationship map", graph(h, nodes, edges, "Model relationships", "Relates to", "Related from")))
    deps = Counter(d for c in data["classes"] for d in c["deps"])
    rows = []
    for m in sorted(models.values(), key=lambda m: m["name"]):
        rows.append([f'<a href="#m-{e(m["name"])}" class="mono">{e(m["name"])}</a>' + (" " + badge("abstract") if m["abstract"] else ""),
                     code(m["table"]), (str(len(m["relations"])), len(m["relations"])), (str(deps.get(m["fqn"], 0)), deps.get(m["fqn"], 0)),
                     e(", ".join(t for t in m["traits"] if t not in ("HasFactory",)))])
    body.append(section("summary", "All models", table(h, "t-models", ["Model", "Table", "Relationships", "Used by (classes)", "Traits"], rows)))
    cards = []
    in_schema = data["schema"]
    for m in sorted(models.values(), key=lambda m: m["name"]):
        rels = "".join(f'<li><span class="mono small">{e(r["type"])}</span> → ' + (f"<a href='#m-{e(short(r['related']))}'>{e(short(r['related']))}</a>" if r.get("related") in models else e(short(r.get("related") or r.get("morph") or "polymorphic"))) +
                       f' <span class="faint mono small">{e(r["name"])}()</span>' + (f' <span class="faint small">pivot {e(r["pivot_table"])}</span>' if r.get("pivot_table") else "") + "</li>" for r in m["relations"])
        casts = ", ".join(f"<code>{e(k)}</code>: {e(v)}" for k, v in m["casts"].items())
        reverse = sorted({f"{x['name']}::{r['name']}" for x in models.values() for r in x["relations"] if r.get("related") == m["fqn"]})
        tbl = in_schema.get(m["table"])
        cols = f"{len(tbl['columns'])} columns" if tbl else "not found in migrations"
        evs = ", ".join(f"{e(k)} → <code>{e(short(v))}</code>" for k, v in m["dispatches_events"].items())
        info = kv([("Table", f'<a href="database.html#tb-{e(m["table"])}"><code>{e(m["table"])}</code></a> <span class="faint">{e(cols)}</span>'),
                   ("Fillable", e(", ".join(m["fillable"]))), ("Guarded", e(", ".join(m["guarded"]) if m["guarded"] else ("nothing (fully unguarded)" if m["guarded"] == [] else ""))),
                   ("Hidden", e(", ".join(m["hidden"]))), ("Casts", casts), ("Appends", e(", ".join(m["appends"]))), ("Eager loads", e(", ".join(m["with"]))),
                   ("Scopes", e(", ".join(m["scopes"]))), ("Accessors", e(", ".join(m["accessors"] + m["mutators"]))),
                   ("Observers", e(", ".join(short(o) for o in m["observers"]))), ("Policy", e(short(m["policy"] or "")) + (" <span class=faint>(by naming convention)</span>" if m.get("policy_auto") else "")),
                   ("Model events", evs), ("Boot hooks", e(", ".join(m["boot_hooks"]))), ("Factory", e(short(m["factory"] or ""))),
                   ("Connection", e(m["connection"] or "")), ("Primary key", e(m["primary_key"]) if m["primary_key"] != "id" else ""),
                   ("Referenced by", e(", ".join(reverse)))])
        cards.append(f'<article class="card" id="m-{e(m["name"])}"><h3><span class="mono">{e(m["name"])}</span>'
                     f'{"".join(chip(t, plain=True) for t in m["traits"])}</h3><p class="small">{h.ref(m["file"], m["line"])}{" · " + e(m["doc"]) if m["doc"] else ""}</p>'
                     f'{"<ul>" + rels + "</ul>" if rels else "<p class=faint>No relationships.</p>"}{info}</article>')
    body.append(section("details", "Model details", f'<div class="grid-2">{"".join(cards)}</div>'))
    return "Models", "Eloquent models: the tables they wrap, how they relate, and the behaviour attached to them.", "".join(body)


# ---------------------------------------------------------------------------------------------- database

def er_mermaid(schema, compact=False, only=None):
    lines = ["erDiagram"]
    safe = lambda s: re.sub(r"[^A-Za-z0-9_]", "_", s)  # noqa: E731
    for name, t in schema.items():
        if only and name not in only:
            continue
        if compact:
            lines.append(f"  {safe(name)} {{\n    id _\n  }}" if False else f"  {safe(name)}")
            continue
        lines.append(f"  {safe(name)} {{")
        for c in t["columns"][:40]:
            keys = []
            if c.get("primary"):
                keys.append("PK")
            if c.get("fk"):
                keys.append("FK")
            if c.get("unique"):
                keys.append("UK")
            typ = safe(c["type"] or "col") or "col"
            note = ("nullable" if c.get("nullable") else "")
            lines.append(f"    {typ} {safe(c['name'])}" + (f" {', '.join(keys)}" if keys else "") + (f' "{note}"' if note else ""))
        if len(t["columns"]) > 40:
            lines.append(f'    more _{len(t["columns"]) - 40}_columns')
        lines.append("  }")
    seen = set()
    for name, t in schema.items():
        for c in t["columns"]:
            fk = c.get("fk")
            if not fk or not fk.get("table") or fk["table"] not in schema:
                continue
            if only and (name not in only or fk["table"] not in only):
                continue
            key = (fk["table"], name, c["name"])
            if key in seen:
                continue
            seen.add(key)
            right = "o|" if c.get("unique") else "o{"
            left = "|o" if c.get("nullable") else "||"
            lines.append(f'  {safe(fk["table"])} {left}--{right} {safe(name)} : "{c["name"]}"')
    return "\n".join(lines)


def page_database(data, h, pages):
    schema = data["schema"]
    body = []
    if not schema:
        return "Database", "Schema from migrations.", '<p class="empty">No migrations or schema dump found.</p>'
    src = Counter(t.get("source", "migrations") for t in schema.values())
    body.append(callout("info", f"{len(schema)} tables, rebuilt from {len(data['migrations'])} migrations", "Source: " + ", ".join(f"{e(k)} ({v})" for k, v in src.items()) +
                        ". The schema is replayed from the migration files (create, alter, rename, drop), so it shows what <code>migrate</code> would build. Raw SQL statements are not interpreted."))
    app_tables = {k: v for k, v in schema.items() if k not in FRAMEWORK_TABLES}
    if len(app_tables) <= 30:
        body.append(section("erd", "Entity-relationship diagram", mermaid(h, er_mermaid(app_tables), "Application tables (framework tables hidden)"),
                            "Lines join a foreign-key column to the table it references. ‖ means required, o means optional, the crow's foot is the “many” side."))
    else:
        body.append(section("erd", "Entity-relationship diagram", mermaid(h, er_mermaid(app_tables, compact=True), "Tables and foreign keys (columns hidden)") +
                            details("Full diagram with columns (large)", mermaid(h, er_mermaid(app_tables), "All columns", lazy=True))))
    models_by_table = {m["table"]: m["name"] for m in data["models"].values()}
    pivots = {r["pivot_table"] for m in data["models"].values() for r in m["relations"] if r.get("pivot_table")}
    rows = []
    for name, t in sorted(schema.items()):
        fks = [c for c in t["columns"] if c.get("fk")]
        kind = "framework" if name in FRAMEWORK_TABLES else ("pivot" if is_pivot(t, pivots) else "")
        rows.append([f'<a href="#tb-{e(name)}" class="mono">{e(name)}</a>', (str(len(t["columns"])), len(t["columns"])),
                     esc_list([f"{c['name']} → {c['fk']['table']}" for c in fks], mono=True, empty="—"),
                     f"<a href='models.html#m-{e(models_by_table[name])}'>{e(models_by_table[name])}</a>" if name in models_by_table else (badge(kind) if kind else '<span class="faint">no model</span>'),
                     h.ref(t.get("created_in") or "") + (f' <span class="faint small">+{len(t["altered_in"])} alter</span>' if t.get("altered_in") else "")])
    body.append(section("tables", "Tables", table(h, "t-tables", ["Table", "Columns", "Foreign keys", "Model", "Created in"], rows, quick=[("framework", "framework"), ("pivot", "pivot"), ("no model", "no model")])))
    det = []
    for name, t in sorted(schema.items()):
        rows = []
        for c in t["columns"]:
            keys = [x for x, on in (("PK", c.get("primary")), ("unique", c.get("unique")), ("index", c.get("index")), ("auto", c.get("auto"))) if on]
            fk = c.get("fk")
            rows.append([f'<span class="mono">{e(c["name"])}</span>', f'<span class="mono small">{e(c["type"])}{"(" + e(c["detail"]) + ")" if c.get("detail") else ""}</span>',
                         "yes" if c.get("nullable") else "", f'<span class="mono small">{e(c.get("default") or "")}</span>', e(", ".join(keys)),
                         (f'<a href="#tb-{e(fk["table"])}" class="mono small">{e(fk["table"])}.{e(fk.get("column") or "id")}</a>' + (f' <span class="faint small">on delete {e(fk["on_delete"])}</span>' if fk.get("on_delete") else "")) if fk and fk.get("table") else "",
                         f'<span class="faint small">{e(os.path.basename(c.get("source") or ""))[:40]}</span>'])
        summ = f'<span class="mono">{e(name)}</span> <span class="faint small">{len(t["columns"])} columns</span>' + (f' {badge("polymorphic: " + ", ".join(t["polymorphic"]))}' if t.get("polymorphic") else "")
        near = {name} | {c["fk"]["table"] for c in t["columns"] if c.get("fk") and c["fk"].get("table") in schema} | \
               {o for o, ot in schema.items() if any((c.get("fk") or {}).get("table") == name for c in ot["columns"])}
        mini = mermaid(h, er_mermaid({k: schema[k] for k in sorted(near)}), f"{name} and its direct neighbours", lazy=True) if len(near) > 1 and len(schema) > 12 else ""
        det.append(f'<div id="tb-{e(name)}">' + details(summ, table(h, None, ["Column", "Type", "Null", "Default", "Keys", "References", "Added by"], rows, filter_=False, sort=False) + mini) + "</div>")
    body.append(section("columns", "Columns per table", "".join(det)))
    rows = []
    for m in reversed(data["migrations"]):
        ops = "; ".join(f"{o['op']} {o['table'] or ''}{(': ' + o['detail']) if o.get('detail') else ''}" for o in m["ops"]) or "—"
        rows.append([(e(m["date"]) or '<span class="faint">—</span>', m["date"] or "0"), h.ref(m["file"], label=m["name"]), f'<span class="small">{e(ops)}</span>',
                     "" if m["has_down"] else badge("no down()", "warn")])
    body.append(section("migrations", "Migration history", table(h, "t-migs", ["Date", "Migration", "What it does", ""], rows), "Newest first."))
    rt = data.get("runtime") or {}
    if rt.get("migrations"):
        rows = [[code(m["name"]), badge(m["status"], "ok" if m["status"] == "Ran" else "warn"), e(m["batch"] or "")] for m in rt["migrations"]]
        body.append(section("status", "Migration status on your database", table(h, "t-mst", ["Migration", "Status", "Batch"], rows)))
    return "Database", "The database schema as the migrations build it: tables, columns, keys and history.", "".join(body)


# ---------------------------------------------------------------------------------------------- events

def events_flow(data):
    a = data["async"]
    lines = ["flowchart LR"]
    nodes = {}

    def node(fqn, kind):
        if fqn in nodes:
            return nodes[fqn]
        nid = mm_id(fqn)
        lab = mm_label(short(fqn))
        shape = {"events": f'{nid}{{{{"{lab}"}}}}', "jobs": f'{nid}[["{lab}"]]', "listeners": f'{nid}(["{lab}"])',
                 "mail": f'{nid}>"{lab}"]', "notifications": f'{nid}>"{lab}"]'}.get(kind, f'{nid}["{lab}"]')
        lines.append("  " + shape)
        nodes[fqn] = nid
        return nid

    for x in a["edges"]:
        s = node(x["from"], "src")
        t = node(x["to"], x["kind"])
        lab = mm_label(x["method"])
        lines.append(f'  {s} -->|"{lab}"| {t}')
    for w in a["wiring"]:
        if not w["listener"]:
            continue
        s = node(w["event"], "events")
        t = node(w["listener"], "listeners")
        lines.append(f"  {s} -.-> {t}")
    for lf, ld in a["listeners"].items():
        for x in a["edges"]:
            pass
    lines += ["  classDef ev fill:#c0322b1f,stroke:#c0322b", "  classDef job fill:#c4561b1f,stroke:#c4561b", "  classDef lis fill:#a8325e1a,stroke:#a8325e",
              "  classDef mail fill:#8a3fbf1a,stroke:#8a3fbf"]
    for fqn, nid in nodes.items():
        cls = "ev" if fqn in a["events"] else "job" if fqn in a["jobs"] else "lis" if fqn in a["listeners"] else "mail" if fqn in a["mail"] or fqn in a["notifications"] else None
        if cls:
            lines.append(f"  class {nid} {cls}")
    return "\n".join(lines), len(nodes)


def page_events(data, h, pages):
    a, con = data["async"], data["console"]
    body = []
    src, n = events_flow(data)
    if n:
        if n <= 80:
            body.append(section("flow", "Who triggers what", mermaid(h, src, "Dispatchers → events / jobs / mail → listeners"),
                                "Solid arrows: code that dispatches (labelled with the method). Dotted arrows: listeners registered for an event. Hexagons are events, double boxes jobs, rounded boxes listeners."))
        else:
            nodes, edges = {}, []
            for x in a["edges"]:
                nodes[x["from"]] = x["from_role"]
                nodes[x["to"]] = {"events": "event", "jobs": "job", "mail": "mail", "notifications": "notification"}[x["kind"]]
                edges.append({"s": x["from"], "t": x["to"], "k": x["kind"]})
            for w in a["wiring"]:
                if w["listener"]:
                    nodes.setdefault(w["event"], "event")
                    nodes.setdefault(w["listener"], "listener")
                    edges.append({"s": w["event"], "t": w["listener"], "k": "listener"})
            gnodes = [{"id": k, "l": short(k), "k": r, "kl": ROLE_INFO.get(r, {}).get("plural", r)} for k, r in nodes.items()]
            body.append(section("flow", "Who triggers what", graph(h, gnodes, edges, "Event flow", "Triggers", "Triggered by")))
    rows = [[f'<span class="mono">{e(short(k))}</span>' + (" " + badge("broadcast", "info") if v.get("broadcast") else ""),
             esc_list([short(x) for x in v["listeners"]], mono=True, empty="none"), esc_list(v["dispatched_by"], mono=True, empty="not found"), h.ref(v["file"], v["line"])]
            for k, v in sorted(a["events"].items())]
    body.append(section("events", "Events", table(h, "t-ev", ["Event", "Listeners", "Dispatched by", "File"], rows, empty="No event classes.")))
    rows = []
    for w in a["wiring"]:
        l = a["listeners"].get(w["listener"]) or {}
        rows.append([f'<span class="mono">{e(short(w["event"]))}</span>', f'<span class="mono">{e(short(w["listener"] or "Closure"))}</span>' + (f'<span class="faint mono small">::{e(w["method"])}</span>' if w.get("method") and w["method"] != "handle" else ""),
                     badge("queued", "info") if l.get("queued") else "", e(w["source"])])
    body.append(section("listeners", "Listeners", table(h, "t-lis", ["Event", "Listener", "", "Registered by"], rows, empty="No listeners wired."),
                        "Queued listeners run on a queue worker, so they need a running worker in development too."))
    rows = [[f'<span class="mono">{e(short(k))}</span>', badge("queued", "info") if v["queued"] else badge("sync"), e(v.get("queue") or ""),
             e(", ".join(x for x in (f"tries {v['tries']}" if v.get("tries") else "", f"timeout {v['timeout']}s" if v.get("timeout") else "",
                                     "unique" if v.get("unique") else "", "batchable" if v.get("batchable") else "") if x)),
             esc_list(v.get("dispatched_by", []), mono=True, empty="not found"), h.ref(v["file"], v["line"])] for k, v in sorted(a["jobs"].items())]
    body.append(section("jobs", "Jobs", table(h, "t-jobs", ["Job", "Mode", "Queue", "Options", "Dispatched by", "File"], rows, empty="No job classes.")))
    if a["mail"]:
        rows = [[f'<span class="mono">{e(short(k))}</span>', e(v.get("subject") or ""), esc_list(v["views"], mono=True), badge("queued", "info") if v["queued"] else "",
                 esc_list(v.get("sent_by", []), mono=True, empty="not found"), h.ref(v["file"], v["line"])] for k, v in sorted(a["mail"].items())]
        body.append(section("mail", "Mail", table(h, "t-mail", ["Mailable", "Subject", "Views", "", "Sent by", "File"], rows)))
    if a["notifications"]:
        rows = [[f'<span class="mono">{e(short(k))}</span>', e(", ".join(v["channels"])), badge("queued", "info") if v["queued"] else "",
                 esc_list(v.get("sent_by", []), mono=True, empty="not found"), h.ref(v["file"], v["line"])] for k, v in sorted(a["notifications"].items())]
        body.append(section("notifications", "Notifications", table(h, "t-notif", ["Notification", "Channels", "", "Sent by", "File"], rows)))
    obs = [(m["name"], o) for m in data["models"].values() for o in m["observers"]]
    if obs:
        rows = [[f"<a href='models.html#m-{e(mn)}'>{e(mn)}</a>", f'<span class="mono">{e(short(o))}</span>'] for mn, o in obs]
        body.append(section("observers", "Model observers", table(h, "t-obs", ["Model", "Observer"], rows, filter_=False)))
    rows = [[e(s["frequency"]), f'<span class="mono">{e(s["target"])}</span>', e(s["type"]), e(", ".join(s["flags"])), h.ref(s["file"], s["line"])] for s in con["schedule"]]
    body.append(section("schedule", "Scheduled tasks", table(h, "t-sched", ["When", "What", "Type", "Options", "Defined in"], rows, empty="Nothing scheduled."),
                        f"These only run when the scheduler runs. Locally: <code>{e(data['prefixes']['artisan'])} schedule:work</code>" +
                        (" (or the scheduler container)." if any(s["role"] == "scheduler" for s in data["docker"]["services"]) else ".")))
    rows = [[code(c["name"]), f'<span class="mono small">{e(c["signature"] or "")}</span>', e(c["description"] or ""), h.ref(c["file"], c["line"])] for c in con["commands"]]
    rows += [[code(c["name"]), f'<span class="mono small">{e(c["signature"])}</span>', e(c["description"]), h.ref(c["file"], c["line"])] for c in con["closure_commands"]]
    body.append(section("commands", "Artisan commands", table(h, "t-cmd", ["Command", "Signature", "Description", "Defined in"], rows, empty="No custom commands."),
                        f"Run with <code>{e(data['prefixes']['artisan'])} &lt;command&gt;</code>."))
    return "Events & jobs", "Everything that happens outside the request: events and listeners, queued jobs, mail, notifications, the scheduler and console commands.", "".join(body)


# ---------------------------------------------------------------------------------------------- frontend

def page_frontend(data, h, pages):
    s, asst, views, ipages = data["stack"], data["assets"], data["views"], data["inertia_pages"]
    body = []
    body.append(section("stack", "Frontend stack", '<div class="card">' + kv([
        ("UI", e(", ".join(s["frontend"]))), ("Bundler", e(asst["bundler"] or "none found")), ("Config", code(asst["config_file"]) if asst["config_file"] else ""),
        ("Entry points", esc_list(asst["entries"], mono=True)), ("Plugins", e(", ".join(asst["plugins"]))), ("CSS", e(asst["css"] or "")),
        ("JS/TS files", e(", ".join(f"{v} .{k}" for k, v in sorted(asst["js_components"].items())))),
        ("Dev server", cmd_box(f"{data['prefixes']['npm']} run dev") if data["packages"]["npm"] or data["packages"]["npm_dev"] else "")]) + "</div>"))
    if ipages:
        rows = [[f'<span class="mono">{e(p["name"])}</span>' + (" " + badge("partial") if p["kind"] == "partial" else ""),
                 esc_list(p["rendered_by"], mono=True, empty="not rendered by PHP"), h.ref(p["file"])] for p in sorted(ipages.values(), key=lambda p: p["name"])]
        missing = [r for r in data["renders"] if r["kind"] == "inertia" and r["name"] not in ipages]
        extra = callout("crit", f"{len(missing)} page(s) are rendered but don't exist", ", ".join(f"<code>{e(r['name'])}</code> ({e(short(r['by']))}::{e(r['method'])})" for r in missing)) if missing else ""
        body.append(section("inertia", "Inertia pages", extra + table(h, "t-inertia", ["Page", "Rendered by", "File"], rows),
                            "Each controller call to Inertia::render('Name') loads resources/js/Pages/Name.(vue|jsx|tsx|svelte)."))
    if views:
        rows = []
        comp_use = Counter()
        for v in views.values():
            for c in v["components"]:
                comp_use[c] += 1
        for v in sorted(views.values(), key=lambda v: v["name"]):
            uses = [f"↑ {x}" for x in ([v["extends"]] if v["extends"] else [])] + [f"+ {x}" for x in v["includes"]] + [f"&lt;x-{e(x)}&gt;" for x in v["components"]] + [f"⚡ {x}" for x in v["livewire"]]
            rows.append([f'<span class="mono">{e(v["name"])}</span>', badge(v["kind"]), list_html([e(u) if not u.startswith("&lt;") else u for u in uses], mono=True, empty=""),
                         esc_list(v["used_by"], mono=True, empty="—"), (str(v["lines"]), v["lines"]), h.ref(v["file"])])
        body.append(section("views", "Blade views", table(h, "t-views", ["View", "Kind", "Extends ↑ / includes + / components / Livewire ⚡", "Rendered by", "Lines", "File"], rows,
                                                           quick=[("layout", "layout"), ("component", "component"), ("email", "email"), ("livewire", "livewire"), ("volt", "volt")]),
                            "View names use dots for folders: <code>emails.orders.confirmation</code> is resources/views/emails/orders/confirmation.blade.php."))
        rows = []
        for tag, n in comp_use.most_common():
            vname, cls, ext = component_targets_static(tag, views, data)
            target = "package component" if ext else (", ".join(x for x in (f"view {vname}" if vname else "", f"class {short(cls)}" if cls else "") if x) or "not found")
            rows.append([code(f"<x-{tag}>"), e(target), (str(n), n)])
        if rows:
            body.append(section("components", "Blade components in use", table(h, "t-comp", ["Tag", "Resolves to", "Used in (views)"], rows)))
        nodes, edges, seen = [], [], set()

        def add_node(i, l, k, sub="", f="", kl=None):
            if i not in seen:
                seen.add(i)
                nodes.append({"id": i, "l": l, "k": k, "kl": kl or k.capitalize(), "sub": sub, "f": f})

        for v in views.values():
            add_node("v:" + v["name"], v["name"], {"layout": "layout", "component": "component", "email": "email", "volt": "volt", "livewire": "livewire"}.get(v["kind"], "view"), v["file"], v["file"],
                     {"layout": "Layouts", "component": "Components", "email": "Email views", "volt": "Volt", "livewire": "Livewire views"}.get(v["kind"], "Views"))
        for v in views.values():
            for x in ([v["extends"]] if v["extends"] else []):
                add_node("v:" + x, x, "external", kl="Missing / package")
                edges.append({"s": "v:" + v["name"], "t": "v:" + x, "k": "extends"})
            for x in v["includes"]:
                add_node("v:" + x, x, "external", kl="Missing / package")
                edges.append({"s": "v:" + v["name"], "t": "v:" + x, "k": "include"})
            for x in v["components"]:
                vn, cls, ext = component_targets_static(x, views, data)
                tid = "v:" + vn if vn else "x:" + x
                add_node(tid, vn or f"x-{x}", "component" if not ext else "external", kl="Components" if not ext else "Missing / package")
                edges.append({"s": "v:" + v["name"], "t": tid, "k": "component"})
            for x in v["livewire"]:
                add_node("lw:" + x, x, "livewire", kl="Livewire components")
                edges.append({"s": "v:" + v["name"], "t": "lw:" + x, "k": "livewire"})
        for r in data["renders"]:
            if r["kind"] == "view" and r["name"] in views:
                role = next((c["role"] for c in data["classes"] if c["fqn"] == r["by"]), "other")
                add_node("c:" + r["by"], short(r["by"]), role, r["by"], r["file"], ROLE_INFO.get(role, {}).get("plural", role))
                edges.append({"s": "c:" + r["by"], "t": "v:" + r["name"], "k": "renders"})
        if len(nodes) > 1:
            body.append(section("graph", "View graph", graph(h, nodes, edges, "Views", "Uses", "Used by"),
                                "PHP classes that render views, and how views extend layouts, include partials and embed components."))
    return "Frontend", "How the UI is built: Blade views, components, Inertia pages and the asset pipeline.", "".join(body)


def component_targets_static(tag, views, data):
    if "::" in tag:
        return None, None, True
    parts = tag.split(".")
    for cand in ("components." + tag, "components." + tag + ".index", "components." + tag + "." + parts[-1]):
        if cand in views:
            return cand, None, False
    cls = "App\\View\\Components\\" + "\\".join("".join(w.capitalize() for w in re.split(r"[-_]", p)) for p in parts)
    if any(c["fqn"] == cls for c in data["classes"]):
        return None, cls, False
    if tag.startswith(("layouts.", "layout")) and "layouts." + tag.split(".", 1)[-1] in views:
        return "layouts." + tag.split(".", 1)[-1], None, False
    return None, None, False


# ---------------------------------------------------------------------------------------------- livewire

def page_livewire(data, h, pages):
    lw = data["livewire"]
    comps = lw["components"]
    body = [callout("info", f"Livewire {e(lw['version'] or '')} · {len(comps)} components",
                    "A Livewire component is a PHP class (or a Volt single-file component) holding state in public properties. "
                    "The browser calls its public methods (actions) with <code>wire:click</code> etc., and the server re-renders the Blade view and sends back the HTML diff. "
                    f"Volt components are looked up in: {', '.join(code(m) for m in lw['mounts'])}.")]
    rows = []
    for c in sorted(comps, key=lambda c: c["alias"]):
        rows.append([f'<a href="#lw-{e(c["name"] if not c["volt"] else c["alias"])}" class="mono">{e(c["alias"])}</a>', badge("Volt " + c.get("volt_style", "") if c["volt"] else "class", "info" if c["volt"] else ""),
                     esc_list([p["name"] for p in c["props"]], mono=True, empty="—"), esc_list(c["actions"], mono=True, empty="—"),
                     esc_list([f"{x['event']} → {x['method']}" for x in c["listens"]], mono=True, empty="—"),
                     esc_list(sorted({x["event"] for x in c["dispatches"]}), mono=True, empty="—"),
                     esc_list(c["routes"] + [f"in {v}" for v in c["used_in"]], mono=True, empty="not used?")])
    body.append(section("components", "Components", table(h, "t-lw", ["Component", "Type", "State", "Actions", "Listens", "Dispatches", "Route / used in"], rows)))
    if lw["edges"]:
        lines = ["flowchart LR"]
        evn = set()
        for ed in lw["edges"]:
            ev = "ev_" + re.sub(r"\W", "_", ed["event"])
            if ev not in evn:
                lines.append(f'  {ev}{{{{"{mm_label(ed["event"])}"}}}}')
                evn.add(ev)
            lines.append(f'  {mm_id(ed["from"])}["{mm_label(ed["from"])}"] -->|dispatch| {ev}')
            if ed["to"]:
                lines.append(f'  {ev} -->|"#[On]"| {mm_id(ed["to"])}["{mm_label(ed["to"])}"]')
        body.append(section("events", "Component events", mermaid(h, "\n".join(lines), "dispatch() → listeners"),
                            "Browser-side events between components: one component dispatches, any component with a matching #[On] (or $listeners) reacts."))
    cards = []
    for c in sorted(comps, key=lambda c: c["alias"]):
        props = "".join(f'<li><span class="mono">${e(p["name"])}</span>{" <span class=faint>" + e(p["type"]) + "</span>" if p["type"] else ""}'
                        f'{"".join(" " + badge(a) for a in p["attrs"])}{" = " + code(p["default"]) if p["default"] and p["default"] != "null" else ""}</li>' for p in c["props"])
        info = kv([("Class", f'<span class="mono">{e(c["fqn"])}</span>' if c["fqn"] else "Volt single-file component"), ("View", code(c["view"]) if c["view"] else '<span class="faint">none found</span>'),
                   ("Layout", code(c["layout"]) if c["layout"] else ""), ("Title", e(c["title"] or "")), ("Computed", e(", ".join(c["computed"]))),
                   ("Traits", e(", ".join(c["traits"]))), ("Forms", e(", ".join(short(x) for x in c["forms"]))), ("Embed with", code(f"<livewire:{c['alias']} />"))])
        anchor = c["name"] if not c["volt"] else c["alias"]
        cards.append(f'<article class="card" id="lw-{e(anchor)}"><h3><span class="mono">{e(c["alias"])}</span></h3><p class="small">{h.ref(c["file"], c["line"])}</p>'
                     f'{info}{"<h4>State</h4><ul>" + props + "</ul>" if props else ""}{"<h4>Actions</h4>" + esc_list(c["actions"], mono=True) if c["actions"] else ""}</article>')
    body.append(section("details", "Component details", f'<div class="grid-2">{"".join(cards)}</div>'))
    if lw["forms"]:
        rows = [[f'<span class="mono">{e(f["name"])}</span>', esc_list(f["props"], mono=True), h.ref(f["file"], f["line"])] for f in lw["forms"]]
        body.append(section("forms", "Form objects", table(h, "t-lwf", ["Form", "Fields", "File"], rows, filter_=False)))
    wire = Counter()
    for v in data["views"].values():
        for k, n in v["wire"].items():
            wire[k] += n
    if wire:
        body.append(section("wire", "wire: directives in views", '<div class="chips">' + "".join(chip(f"wire:{k} × {n}", plain=True) for k, n in wire.most_common()) + "</div>"))
    return "Livewire", "Livewire and Volt components: their state, actions, events, and where each one is used.", "".join(body)


# ---------------------------------------------------------------------------------------------- filament

def page_filament(data, h, pages):
    f = data["filament"]
    body = []
    pcards = []
    for p in f["panels"]:
        info = kv([("URL", code("/" + p["path"].strip("/"))), ("Default panel", "yes" if p["default"] else ""), ("Features", e(", ".join(p["features"]))),
                   ("Discovers", "<br>".join(f"{e(k)}: <code>{e(v.get('in') or v.get('for') or '')}</code>" for k, v in p["discover"].items())),
                   ("Also registers", e(", ".join(short(x) for x in p["resources"] + p["pages"] + p["widgets"]))),
                   ("Plugins", e(", ".join(p["plugins"]))), ("Middleware", e(", ".join(p["middleware"]))), ("Auth middleware", e(", ".join(p["auth_middleware"]))),
                   ("Brand", e(p["brand"] or "")), ("Tenant", e(p["tenant"] or "")), ("Domain", e(p["domain"] or "")),
                   ("Colours", e(", ".join(f"{k}: {v}" for k, v in p["colors"].items())))])
        nres = sum(1 for r in f["resources"] if r["panel"] == p["id"])
        pcards.append(f'<article class="card"><h3>Panel <span class="mono">{e(p["id"])}</span> {badge(f"{nres} resources")}</h3>'
                      f'<p class="small">{h.ref(p["file"]) if p.get("file") else "<span class=faint>assumed defaults (no PanelProvider found)</span>"}</p>{info}</article>')
    body.append(section("panels", "Panels", f'<div class="grid-2">{"".join(pcards)}</div>', "Each panel is a separate admin area with its own URL, login and navigation."))
    if f["resources"]:
        lines = ["flowchart LR"]
        for p in f["panels"]:
            lines.append(f'  {mm_id("p_" + p["id"])}(["{mm_label(p["id"])} panel<br/><small>/{mm_label(p["path"])}</small>"])')
        for r in f["resources"]:
            rid = mm_id("r_" + r["fqn"])
            lines.append(f'  {rid}["{mm_label(r["name"])}<br/><small>/{mm_label(r["slug"])}</small>"]')
            lines.append(f'  {mm_id("p_" + (r["panel"] or "admin"))} --> {rid}')
            if r["model"]:
                lines.append(f'  {rid} -->|model| {mm_id("m_" + r["model"])}[("{mm_label(short(r["model"]))}")]')
            for rm in r["relations"]:
                lines.append(f'  {rid} -.->|relation manager| {mm_id("rm_" + rm)}["{mm_label(short(rm))}"]')
        body.append(section("map", "Panel map", mermaid(h, "\n".join(lines), "Panels → resources → models")))
        rows = []
        for r in f["resources"]:
            urls = [pg.get("uri", "") for pg in r["pages"]]
            rows.append([f'<a href="#f-{e(r["name"])}" class="mono">{e(r["name"])}</a>', cls_link(r["model"], "model") if r["model"] else '<span class="faint">?</span>',
                         code(r["panel"] or "?"), esc_list(urls, mono=True), (str(len([x for x in r["fields"] if not x["layout"]])), len(r["fields"])),
                         (str(len(r["columns"])), len(r["columns"])), e(r["group"] or "")])
        body.append(section("resources", "Resources", table(h, "t-fres", ["Resource", "Model", "Panel", "URLs", "Form fields", "Table columns", "Nav group"], rows),
                            "A resource is a full CRUD screen set (list, create, edit, view) for one model."))
        cards = []
        for r in f["resources"]:
            fields = "".join(chip(f"{x['type']}: {x['name'] or ''}".rstrip(": "), plain=True) for x in r["fields"] if not x["layout"])
            layout = ", ".join(sorted({x["type"] for x in r["fields"] if x["layout"]}))
            cols = "".join(chip(f"{x['type'].replace('Column', '')}: {x['name'] or ''}", plain=True) for x in r["columns"])
            filt = "".join(chip(f"{x['type'].replace('Filter', '')}: {x['name'] or ''}", plain=True) for x in r["filters"])
            pgs = "".join(f'<li><span class="mono small">{e(pg["key"])}</span> → <code>{e(pg.get("uri", ""))}</code> <span class="faint small">{e(short(pg["class"]))}</span></li>' for pg in r["pages"])
            cards.append(f'<article class="card" id="f-{e(r["name"])}"><h3><span class="mono">{e(r["name"])}</span></h3><p class="small">{h.ref(r["file"], r["line"])}</p>'
                         + kv([("Model", e(short(r["model"] or "?"))), ("Slug", code(r["slug"])), ("Icon", e(r["icon"] or "")), ("Navigation", e(" / ".join(str(x) for x in (r["group"], r["label"]) if x))),
                               ("Title attribute", e(r["title_attribute"] or "")), ("Relation managers", e(", ".join(short(x) for x in r["relations"]))), ("Actions", e(", ".join(r["actions"]))),
                               ("Form layout", e(layout)), ("Cluster", e(r["cluster"] or ""))])
                         + (f"<h4>Form fields</h4><div class=chips>{fields}</div>" if fields else "") + (f"<h4>Table columns</h4><div class=chips>{cols}</div>" if cols else "")
                         + (f"<h4>Filters</h4><div class=chips>{filt}</div>" if filt else "") + (f"<h4>Pages</h4><ul>{pgs}</ul>" if pgs else "") + "</article>")
        body.append(section("resource-details", "Resource details", f'<div class="grid-2">{"".join(cards)}</div>'))
    if f["pages"]:
        rows = [[f'<span class="mono">{e(p["name"])}</span>' + (" " + badge("dashboard") if p["dashboard"] else ""), code(p.get("uri", "")), code(p["panel"] or "?"),
                 code(p["view"]) if isinstance(p.get("view"), str) else "", e(p["group"] or ""), h.ref(p["file"])] for p in f["pages"]]
        body.append(section("pages", "Custom pages", table(h, "t-fpg", ["Page", "URL", "Panel", "View", "Nav group", "File"], rows, filter_=False)))
    if f["widgets"]:
        rows = [[f'<span class="mono">{e(w["name"])}</span>', e(w["type"]), code(w["panel"] or "?"), h.ref(w["file"])] for w in f["widgets"]]
        body.append(section("widgets", "Widgets", table(h, "t-fw", ["Widget", "Type", "Panel", "File"], rows, filter_=False)))
    if f["relation_managers"]:
        rows = [[f'<span class="mono">{e(r["name"])}</span>', code(r["relationship"] or "?"), h.ref(r["file"])] for r in f["relation_managers"]]
        body.append(section("relation-managers", "Relation managers", table(h, "t-frm", ["Relation manager", "Relationship", "File"], rows, filter_=False)))
    body.append(callout("info", "Where these URLs come from", "Filament registers its routes inside the package, so they are derived here from the panel path, each resource's slug and its getPages(). Run with <code>--artisan auto</code> to see the exact list."))
    return "Filament", f"Filament {e(f['version'] or '')} admin panels: their resources, pages and widgets, and the URLs they create.", "".join(body)


# ---------------------------------------------------------------------------------------------- classes

def page_classes(data, h, pages):
    classes = data["classes"]
    roles = Counter(c["role"] for c in classes)
    used_by = Counter(d for c in classes for d in c["deps"])
    legend = "".join(f'<div class="card"><h4>{chip(ROLE_INFO[r]["plural"], r)} <span class="faint num">{roles[r]}</span></h4><p class="small muted">{e(ROLE_INFO[r]["desc"])}</p></div>'
                     for r in ROLE_ORDER if roles.get(r))
    body = [section("roles", "Classes by role", f'<div class="grid-3">{legend}</div>', "Roles are inferred from parent classes, interfaces, traits and namespaces.")]
    skip = {"test", "migration", "factory", "seeder"}
    gn = [c for c in classes if c["role"] not in skip]
    ids = {c["fqn"] for c in gn}
    dup = Counter(c["name"] for c in gn)
    label = lambda c: c["name"] if dup[c["name"]] == 1 else "\\".join(c["fqn"].split("\\")[-2:])  # noqa: E731
    nodes = [{"id": c["fqn"], "l": label(c), "k": c["role"], "kl": ROLE_INFO[c["role"]]["plural"], "sub": c["fqn"], "f": f'{c["file"]}:{c["line"]}',
              "u": {"model": f"models.html#m-{c['name']}", "controller": f"http.html#c-{c['name']}", "livewire": f"livewire.html#lw-{c['name']}", "filament": f"filament.html#f-{c['name']}"}.get(c["role"])}
             for c in gn]
    edges = [{"s": c["fqn"], "t": d} for c in gn for d in c["deps"] if d in ids and d != c["extends"] or (d == c["extends"] and d in ids)]
    body.append(section("graph", "Dependency graph", graph(h, nodes, edges, "Class dependencies", "Depends on", "Used by"),
                        "Each dot is a class (tests, migrations, factories and seeders left out). An arrow means “uses”: imports, type hints, `new`, static calls or ::class. Bigger dots have more connections."))
    rows = [[f'<span class="mono" title="{e(c["fqn"])}">{e(c["name"])}</span>' + (" " + badge("abstract") if c["abstract"] else "") + (" " + badge(c["kind"]) if c["kind"] != "class" else ""),
             role_chip(c["role"]), f'<span class="mono small faint">{e(ns_of(c["fqn"]))}</span>', (str(c["loc"]), c["loc"]), (str(c["methods"]), c["methods"]),
             (str(len(c["deps"])), len(c["deps"])), (str(used_by.get(c["fqn"], 0)), used_by.get(c["fqn"], 0)), h.ref(c["file"], c["line"])] for c in classes]
    body.append(section("all", "All classes", table(h, "t-classes", ["Class", "Role", "Namespace", "Lines", "Methods", "Depends on", "Used by", "File"], rows,
                                                      quick=[(ROLE_INFO[r]["label"], ROLE_INFO[r]["label"]) for r, _ in roles.most_common(6)])))
    hubs = [c for c in sorted(classes, key=lambda c: -used_by.get(c["fqn"], 0)) if used_by.get(c["fqn"])][:15]
    if hubs:
        mx = used_by.get(hubs[0]["fqn"], 1)
        bars = "".join(f'<div class="bar-row"><span class="mono">{e(c["name"])}</span><div class="bar" style="width:{max(2, int(used_by[c["fqn"]] / mx * 100))}%;background:var(--role-{e(c["role"])})"></div><span class="num">{used_by[c["fqn"]]}</span></div>' for c in hubs)
        body.append(section("hubs", "Most depended-upon classes", f'<div class="card">{bars}</div>', "Changing these affects the most code."))
    return "Classes", "Every PHP class in the application, grouped by the role it plays, and how they depend on each other.", "".join(body)


# ---------------------------------------------------------------------------------------------- docker

def docker_mermaid(d):
    lines = ["flowchart LR", '  you(("Your<br/>browser"))']
    svcs = [s for s in d["services"] if not s.get("only_in")]
    shape = {"database": ('[("', '")]'), "cache": ('[("', '")]'), "queue": ('[["', '"]]'), "scheduler": ('[["', '"]]'), "web": ('(["', '"])'),
             "proxy": ('(["', '"])'), "mail": ('>"', '"]')}
    lines.append('  subgraph compose["docker compose"]')
    for s in svcs:
        a, b = shape.get(s["role"], ('["', '"]'))
        img = s["image"] or (f"build {s['build']['context']}" if s.get("build") else "")
        ports = ", ".join(f"{p['host']}→{p['container']}" for p in s["ports"] if p["host"])
        lab = f"<b>{mm_label(s['name'])}</b><br/><small>{mm_label(s['role_label'])}</small><br/><small>{mm_label(img)}</small>" + (f"<br/><small>:{mm_label(ports)}</small>" if ports else "")
        lines.append(f"    {mm_id(s['name'])}{a}{lab}{b}")
    lines.append("  end")
    done = set()
    for s in svcs:
        if s["role"] in ("web", "proxy", "app", "mail", "db-ui", "search", "assets") and any(p["host"] for p in s["ports"]):
            hp = next(p["host"] for p in s["ports"] if p["host"])
            if s["role"] == "app" and any(x["role"] in ("web", "proxy") for x in svcs):
                continue
            lines.append(f'  you -->|":{mm_label(hp)}"| {mm_id(s["name"])}')
    strong = {(x["from"], x["to"]) for x in d["edges"] if x["kind"] != "depends_on"}
    for x in d["edges"]:
        key = (x["from"], x["to"], x["kind"])
        if key in done:
            continue
        done.add(key)
        if x["kind"] == "depends_on":
            if (x["from"], x["to"]) in strong:
                continue
            lines.append(f"  {mm_id(x['from'])} -.-> {mm_id(x['to'])}")
        else:
            lines.append(f'  {mm_id(x["from"])} -->|"{mm_label(x["label"])}"| {mm_id(x["to"])}')
    colors = {"app": "#2f5fd0", "web": "#0f8a7e", "proxy": "#0f8a7e", "database": "#995600", "cache": "#c0322b", "queue": "#c4561b", "scheduler": "#c4561b",
              "mail": "#8a3fbf", "search": "#2a7fb8", "assets": "#23853f", "websockets": "#c2387a"}
    for role, col in colors.items():
        lines.append(f"  classDef {role.replace('-', '_')} fill:{col}1f,stroke:{col},stroke-width:1.5px")
    for s in svcs:
        if s["role"] in colors:
            lines.append(f"  class {mm_id(s['name'])} {s['role'].replace('-', '_')}")
    return "\n".join(lines)


def page_docker(data, h, pages):
    d, pre = data["docker"], data["prefixes"]
    if not d["present"]:
        return "Docker", "Docker development environment.", callout("info", "No Docker setup found", "No compose file or Dockerfile in this project. It probably runs on a local PHP install, Herd, Valet or Homestead.")
    svcs = [s for s in d["services"] if not s.get("only_in")]
    body = []
    roles = Counter(s["role_label"].lower() for s in svcs)
    intro = (f"<p><code>{e(pre['up'])}</code> starts <strong>{len(svcs)} containers</strong>: " +
             ", ".join(f"{n} {r}" for r, n in roles.items()) + ". " +
             ("This project uses <strong>Laravel Sail</strong>, a thin wrapper around docker compose. Run every command through <code>./vendor/bin/sail</code> (add an alias: <code>alias sail='sh $([ -f sail ] && echo sail || echo vendor/bin/sail)'</code>). " if d["sail"] else "") +
             (f"The PHP code runs in <code>{e(d['app_service'])}</code>; that is where artisan, composer and tests run. " if d["app_service"] else "") + "</p>")
    if d["env_used"]:
        intro += "<p>Laravel reaches the other containers by service name, set through these env vars: " + ", ".join(f"<code>{e(x['key'])}</code> → <code>{e(x['service'])}</code>" for x in d["env_used"]) + ".</p>"
    body.append(section("overview", "How the environment fits together", f'<div class="prose">{intro}</div>' + mermaid(h, docker_mermaid(d), "Containers and how they talk"),
                        "Solid arrows are real connections (from env vars or web-server config); dotted arrows are start-up order (depends_on)."))
    urls = service_urls(data)
    rows = [[f'<a href="{e(u["url"])}" class="mono">{e(u["url"])}</a>' if u["http"] else code(u["url"]), e(u["label"]), code(u["service"])] for u in urls]
    body.append(section("ports", "Ports on your machine", table(h, "t-dports", ["Address", "What", "Service"], rows, filter_=False, empty="No ports published.")))
    cmds = [("Start everything", pre["up"]), ("Stop", pre["down"]), ("Rebuild after Dockerfile changes", pre["build"]), ("Logs", pre["logs"]),
            ("Shell in the app container", pre["shell"]), ("Status", pre["ps"]), ("Run artisan", pre["artisan"] + " …"), ("Remove volumes (wipes DB!)", (pre["down"] + " -v") if pre["down"] else "")]
    body.append(section("commands", "Commands", table(h, "t-dcmd", ["Task", "Command"], [[e(a), cmd_box(c)] for a, c in cmds if c], filter_=False)))
    cards = []
    for s in d["services"]:
        envs = ", ".join(f"<code>{e(k)}</code>" for k in s["environment"]) if s["environment"] else ""
        vols = esc_list([f"{v['src'] or '(anonymous)'} → {v['dst']}" + (f" ({v['type']})" if v["type"] != "bind" else "") for v in s["volumes"]], mono=True, empty="", limit=10)
        info = kv([("Role", e(SERVICE_ROLES[s["role"]][1])), ("Image", code(s["image"]) if s["image"] else ""),
                   ("Build", (code((s["build"] or {}).get("file") or (s["build"] or {}).get("context")) + (f" target {e(s['build']['target'])}" if (s["build"] or {}).get("target") else "")) if s.get("build") else ""),
                   ("PHP", e(s.get("php_version") or "") if s["role"] in ("app", "queue", "scheduler", "websockets") else ""),
                   ("Command", code(s["command"]) if s["command"] else ""), ("Ports", esc_list([p["raw"] + (f"  ({', '.join(p['vars'])})" if p["vars"] else "") for p in s["ports"]], mono=True, empty="")),
                   ("Volumes", vols), ("Depends on", e(", ".join(s["depends_on"]))), ("Environment", envs), ("Env files", e(", ".join(s["env_file"]))),
                   ("Healthcheck", "yes" if s["healthcheck"] else ""), ("Profiles", e(", ".join(s["profiles"]))), ("Restart", e(s["restart"] or "")),
                   ("Working dir", code(s["working_dir"]) if s.get("working_dir") else ""), ("Defined in", e(", ".join(s["files"])))])
        cards.append(f'<article class="card"><h3><span class="mono">{e(s["name"])}</span> {chip(s["role_label"], plain=True)}'
                     f'{" " + badge("only in " + s["only_in"], "info") if s.get("only_in") else ""}{" " + badge("tag: latest", "warn") if s.get("tag") == "latest" else ""}</h3>{info}</article>')
    body.append(section("services", "Services", f'<div class="grid-2">{"".join(cards)}</div>', "Environment variable values are not shown, only names."))
    dcards = []
    for f, df in d["dockerfiles"].items():
        if not df:
            continue
        info = kv([("Stages", esc_list([f"{s['image']}" + (f" as {s['as']}" if s["as"] else "") for s in df["stages"]], mono=True)), ("PHP", e(df["php_version"] or "")),
                   ("PHP extensions", e(", ".join(df["php_ext"]))), ("System packages", e(", ".join(x for x in df["apt"] + df["apk"] if not re.match(r"php\d", x))[:600])),
                   ("Xdebug", "installed" if df["xdebug"] else ""), ("Composer", "yes" if df["composer"] else ""), ("Node", "yes" if df["node"] else ""),
                   ("Exposes", e(", ".join(df["expose"]))), ("Workdir", code(df["workdir"]) if df["workdir"] else ""), ("User", e(df["user"] or "")),
                   ("Entrypoint", code(df["entrypoint"]) if df["entrypoint"] else ""), ("Command", code(df["cmd"]) if df["cmd"] else ""), ("Build args", e(", ".join(df["args"])))])
        dcards.append(f'<article class="card"><h3>{h.ref(f)}</h3>{info}</article>')
    if dcards:
        body.append(section("dockerfiles", "Dockerfiles", f'<div class="grid-2">{"".join(dcards)}</div>'))
    extra = []
    if d["supervisor"]:
        extra.append("<h3>Processes started by supervisord</h3>" + table(h, "t-sup", ["Program", "Command", "File"], [[code(x["program"]), code(x["command"]), h.ref(x["file"])] for x in d["supervisor"]], filter_=False))
    if d["php_ini"]:
        extra.append("<h3>PHP settings</h3>" + table(h, "t-ini", ["Setting", "Value"], [[code(k), code(v)] for k, v in d["php_ini"].items()], filter_=False))
    if d["config_files"]:
        extra.append("<h3>Docker-related files</h3>" + table(h, "t-dfiles", ["File", "Kind"], [[h.ref(x["file"]), e(x["kind"])] for x in d["config_files"]]))
    extra.append("<h3>Compose files</h3>" + table(h, "t-cf", ["File", "Role", "Services"], [[h.ref(x["file"]), e({"base": "main file", "override": "auto-merged override", "extra": "used with -f"}[x["kind"]]), e(", ".join(x["services"]))] for x in d["files"]], filter_=False))
    if d["devcontainer"]:
        extra.append(callout("info", "Dev container available", "A .devcontainer folder exists: VS Code / Codespaces can open the project inside the container."))
    body.append(section("files", "Configuration files", "".join(extra)))
    return "Docker", "The local development environment: which containers run, how they connect, and how to work with them.", "".join(body)


# ---------------------------------------------------------------------------------------------- config

def page_config(data, h, pages):
    body = []
    rows = []
    for r in data["env"]["matrix"]:
        state = ""
        if r["in_env"] is False and r["in_example"]:
            state = badge("missing in your .env", "warn")
        elif r["in_env"] and not r["in_example"]:
            state = badge("only in your .env", "info")
        rows.append([code(r["key"]), e(r["group"]), (f'<span class="mono small">{e(r["example"])}</span>' if r["in_example"] else badge("not in .env.example", "warn" if r["config"] and not r["defaults"] else "")),
                     state, esc_list(r["config"], mono=True, limit=4, empty="—"), esc_list(r["defaults"], mono=True, limit=2, empty=""),
                     esc_list(r["code"] + [f"compose: {x}" for x in r["compose"]], mono=True, limit=4, empty="")])
    groups = Counter(r["group"] for r in data["env"]["matrix"])
    body.append(section("env", "Environment variables", table(h, "t-env", ["Key", "Group", ".env.example", "Your .env", "Feeds config", "Default", "Also used by"], rows,
                                                                quick=[(g, g + "_") for g, _ in groups.most_common(8)]),
                        "Values from .env.example are shown, except anything that looks like a secret. Values from your own .env are never shown."))
    rows = [[h.ref(f["file"]), code(f["key"]), (str(f["env_count"]), f["env_count"]), esc_list(f["top_keys"], mono=True, limit=10), badge("custom", "info") if f["custom"] else "",
             (str(data["config"]["config_reads"].get(f["key"], 0)), data["config"]["config_reads"].get(f["key"], 0))] for f in data["config"]["files"]]
    body.append(section("files", "Config files", table(h, "t-cfg", ["File", "config() key", "env() calls", "Top-level keys", "", "Read by app code"], rows),
                        "Code reads these with <code>config('file.key')</code>; only config files should call <code>env()</code>."))
    pk = data["packages"]
    rows = []
    for name, cons in list(pk["require"].items()) + list(pk["require_dev"].items()):
        if name == "php" or name.startswith("ext-"):
            continue
        lock = pk["locked"].get(name, {})
        rows.append([code(name), e(cons), e(lock.get("version", "")), badge("dev") if name in pk["require_dev"] else "", e(KNOWN_PACKAGES.get(name) or lock.get("description", ""))])
    body.append(section("composer", "PHP packages (composer)", table(h, "t-comp-pk", ["Package", "Constraint", "Locked", "", "What it does"], rows),
                        f"{len(pk['locked'])} packages in composer.lock in total, including dependencies of dependencies."))
    rows = []
    for name, cons in list(pk["npm"].items()) + list(pk["npm_dev"].items()):
        rows.append([code(name), e(cons), e(pk["npm_locked"].get(name, "")), badge("dev") if name in pk["npm_dev"] else "", e(KNOWN_NPM.get(name, ""))])
    if rows:
        body.append(section("npm", "JS packages (npm)", table(h, "t-npm", ["Package", "Range", "Locked", "", "What it does"], rows)))
    return "Config & packages", "Settings and dependencies: which environment variables feed which config keys, and what every package is for.", "".join(body)


# ---------------------------------------------------------------------------------------------- insights

def page_insights(data, h, pages):
    ins = data["insights"]
    sev = Counter(i["severity"] for i in ins)
    body = [f'<div class="legend-row"><span>{badge(str(sev.get("crit", 0)) + " critical", "crit")}</span><span>{badge(str(sev.get("warn", 0)) + " warnings", "warn")}</span>'
            f'<span>{badge(str(sev.get("info", 0)) + " notes", "info")}</span><span class="faint">From static analysis. Each finding is a lead to check, not a verdict.</span></div>']
    items = []
    for i in ins:
        tbl = table(h, None, i["cols"], [[e(c) if not str(c).startswith("<") else c for c in r] for r in i["rows"]], filter_=len(i["rows"]) > 10) if i["rows"] else ""
        items.append(f'<details class="insight {e(i["severity"])}"{" open" if i["severity"] == "crit" else ""}><summary><span class="t">{badge(i["area"], i["severity"])} {e(i["title"])}</span>'
                     f'<p>{e(i["detail"])}</p></summary>{f"<div class=body>{tbl}</div>" if tbl else ""}</details>')
    body.append(section("findings", "Findings", "".join(items) or '<p class="empty">Nothing flagged.</p>'))
    g = data.get("git") or {}
    if g.get("churn"):
        rows = [[h.ref(c["file"]), (str(c["commits"]), c["commits"]), e(", ".join(c["authors"])), e(file_area(c["file"]))] for c in g["churn"]]
        body.append(section("churn", "Change hotspots", table(h, "t-churn", ["File", "Commits (12 months)", "Main authors", "Area"], rows),
                            "Files that change most often. Combined with size, these are where bugs and merge conflicts tend to live."))
    if g.get("owners"):
        rows = [[e(a), ", ".join(f"{e(o['author'])} <span class='faint'>({o['commits']})</span>" for o in os_)] for a, os_ in sorted(g["owners"].items())]
        body.append(section("owners", "Who knows what", table(h, "t-own2", ["Area", "Most active (12 months)"], rows, filter_=False)))
    return "Insights", "Things worth checking: broken references, risky patterns, complexity hotspots, ownership and open TODOs.", "".join(body)


# =====================================================================================================
# 28. Method-level call graph ("what calls what") and request traces
# =====================================================================================================

CONF_RANK = {"exact": 0, "inferred": 1, "possible": 2}


def worst(a, b):
    return a if CONF_RANK.get(a, 2) >= CONF_RANK.get(b, 2) else b


class Ty:
    """What an expression evaluates to: candidate classes, how sure we are, and its shape."""
    __slots__ = ("cls", "conf", "kind", "meta")

    def __init__(self, cls, conf="exact", kind="obj", meta=None):
        self.cls = tuple(dict.fromkeys(x for x in cls if x))
        self.conf = conf
        self.kind = kind      # obj | builder | rel | coll | table | ext | http | storage | cache | process | artisan | app | auth
        self.meta = meta      # e.g. the pivot table of a belongsToMany relation


EXT = Ty(("~ext",), "exact", "ext")   # "known, but not one of your classes": nothing to follow, nothing to report


def merge_ty(ts):
    ts = [t for t in ts if t is not None]
    if not ts:
        return None
    objs = [t for t in ts if t.kind != "ext"]
    if not objs:
        return EXT
    kind = objs[0].kind
    same = [t for t in objs if t.kind == kind]
    conf = "exact"
    for t in same:
        conf = worst(conf, t.conf)
    return Ty([c for t in same for c in t.cls], conf, kind, same[0].meta)


EL_BUILDER = {"query", "newQuery", "where", "orWhere", "whereIn", "whereNotIn", "whereNull", "whereNotNull", "whereHas", "orWhereHas",
              "whereDoesntHave", "doesntHave", "has", "with", "withCount", "withSum", "withAvg", "withMax", "withMin", "withExists", "without",
              "orderBy", "orderByDesc", "latest", "oldest", "select", "addSelect", "selectRaw", "whereRaw", "orWhereRaw", "join", "leftJoin",
              "rightJoin", "groupBy", "having", "havingRaw", "limit", "take", "skip", "offset", "when", "unless", "withTrashed", "onlyTrashed",
              "withoutTrashed", "distinct", "lockForUpdate", "sharedLock", "inRandomOrder", "whereBetween", "whereNotBetween", "whereDate",
              "whereMonth", "whereDay", "whereYear", "whereTime", "whereColumn", "whereKey", "whereKeyNot", "whereBelongsTo", "whereRelation",
              "orWhereRelation", "whereLike", "whereAny", "whereAll", "whereNone", "whereJsonContains", "whereNot", "orWhereNot", "whereExists",
              "tap", "forPage", "reorder", "withGlobalScope", "withoutGlobalScope", "withoutGlobalScopes", "whereMorphedTo", "whereHasMorph",
              "orderByRaw", "whereFullText", "withWhereHas", "toBase", "whereIntegerInRaw", "from"}
EL_FIND = {"first", "firstOrFail", "find", "findOrFail", "findOrNew", "sole", "firstWhere", "findOr", "firstOr", "make", "newModelInstance", "firstOrNew"}
EL_CREATE = {"create", "forceCreate", "firstOrCreate", "updateOrCreate", "createOrFirst", "createQuietly", "forceCreateQuietly"}
EL_LIST = {"get", "all", "paginate", "simplePaginate", "cursorPaginate", "cursor", "lazy", "lazyById", "findMany", "chunk", "chunkById",
           "each", "fromQuery", "hydrate", "eachById"}
EL_SCALAR = {"count", "exists", "doesntExist", "sum", "avg", "average", "max", "min", "value", "pluck", "implode", "existsOr", "doesntExistOr"}
EL_MASS_WRITE = {"update", "delete", "forceDelete", "increment", "decrement", "insert", "insertGetId", "insertOrIgnore", "upsert", "restore",
                 "truncate", "updateOrInsert", "incrementEach", "decrementEach", "destroy", "touch"}
INST_WRITE = {"save": "save", "saveQuietly": None, "update": "update", "updateQuietly": None, "delete": "delete", "deleteQuietly": None,
              "forceDelete": "forceDelete", "restore": "restore", "increment": "update", "decrement": "update", "touch": "update",
              "push": "save", "saveOrFail": "save", "deleteOrFail": "delete", "updateOrFail": "update"}
INST_READ = {"load", "loadMissing", "loadCount", "loadSum", "loadMax", "loadMin", "loadAvg", "refresh", "fresh"}
INST_SELF = {"replicate", "fill", "forceFill", "setAttribute", "setRelation", "unsetRelation", "makeHidden", "makeVisible", "append",
             "withoutRelations", "setVisible", "setHidden", "mergeCasts"}
REL_WRITE = {"create", "createMany", "save", "saveMany", "attach", "detach", "sync", "syncWithoutDetaching", "syncWithPivotValues",
             "toggle", "associate", "dissociate", "updateExistingPivot", "firstOrCreate", "updateOrCreate", "forceCreate", "createQuietly",
             "update", "delete", "upsert", "createManyQuietly"}
REL_PIVOT = {"attach", "detach", "sync", "syncWithoutDetaching", "syncWithPivotValues", "toggle", "updateExistingPivot"}
REL_RETURNS_MODEL = {"create", "save", "firstOrCreate", "updateOrCreate", "forceCreate", "createQuietly", "associate", "dissociate"}
COLL_ELEM = {"first", "last", "find", "firstWhere", "sole", "pop", "shift", "random", "firstOrFail"}
COLL_SAME = {"filter", "where", "whereIn", "whereNotIn", "sortBy", "sortByDesc", "values", "unique", "reject", "take", "skip", "reverse",
             "merge", "each", "tap", "sort", "slice", "keyBy", "load", "loadMissing", "fresh", "except", "only", "diff", "intersect",
             "whereNull", "whereNotNull", "concat", "push", "prepend", "collect", "toBase", "whereStrict", "shuffle", "forPage"}
CLOSURE_ELEM = {"each", "map", "filter", "reject", "first", "last", "sortBy", "sortByDesc", "sum", "every", "contains", "groupBy", "keyBy",
                "mapWithKeys", "flatMap", "transform", "partition", "search", "firstWhere", "sole", "doesntContain", "some", "mapToGroups",
                "max", "min", "avg", "unique", "chunk", "chunkById", "lazy", "eachById", "sum", "countBy"}
MODEL_EVENTS_FOR = {"create": ["creating", "created", "saving", "saved"], "save": ["saving", "saved", "creating", "created", "updating", "updated"],
                    "update": ["updating", "updated", "saving", "saved"], "delete": ["deleting", "deleted"],
                    "forceDelete": ["forceDeleting", "forceDeleted", "deleting", "deleted"], "restore": ["restoring", "restored"]}
FACADE_KIND = {"Http": "http", "Storage": "storage", "Cache": "cache", "Redis": "cache", "Process": "process", "Artisan": "artisan"}
EFFECT_VERBS = {"http": {"get", "post", "put", "patch", "delete", "head", "send", "pool"},
                "storage": {"put", "putFile", "putFileAs", "get", "delete", "copy", "move", "exists", "download", "url", "temporaryUrl",
                            "append", "prepend", "writeStream", "readStream", "makeDirectory", "deleteDirectory", "files", "allFiles", "json"},
                "cache": {"get", "put", "remember", "rememberForever", "forget", "flush", "has", "add", "increment", "decrement", "forever",
                          "pull", "many", "putMany", "set", "del", "hset", "hget", "publish", "flexible"},
                "process": {"run", "start", "pipe", "pool", "concurrently"}, "artisan": {"call", "queue"}}
AUTH_CALLS = {"authorize", "can", "cannot", "cant", "allows", "denies", "authorizeForUser", "inspect", "check", "any", "none"}
EDGE_KINDS = ["call", "relation", "scope", "new", "action", "middleware", "validate", "authorize", "dispatch", "event", "listener",
              "observer", "mail", "notify"]
CONVENTIONAL_METHODS = {
    "handle", "boot", "booted", "booting", "register", "rules", "authorize", "messages", "attributes", "prepareForValidation",
    "passedValidation", "failedValidation", "withValidator", "after", "toArray", "toResponse", "with", "via", "toMail", "toDatabase",
    "toBroadcast", "toSlack", "toVonage", "toSms", "build", "content", "envelope", "attachments", "headers", "render", "mount", "form",
    "table", "infolist", "getPages", "getRelations", "getWidgets", "getHeaderActions", "getHeaderWidgets", "getFooterWidgets", "casts",
    "definition", "run", "up", "down", "shouldQueue", "broadcastOn", "broadcastAs", "broadcastWith", "broadcastWhen", "middleware",
    "failed", "retryUntil", "backoff", "uniqueId", "uniqueFor", "tags", "report", "context", "viaQueue", "viaConnection", "schedule",
    "commands", "configure", "panel", "passes", "message", "validate", "get", "set", "serialize", "unserialize", "jsonSerialize",
    "toJson", "terminate", "newFactory", "newCollection", "newEloquentBuilder", "resolveRouteBinding", "getRouteKeyName", "toSearchableArray",
    "searchableAs", "shouldBeSearchable", "prunable", "pruning", "routeNotificationForMail", "routeNotificationForSlack", "canAccessPanel",
    "getFilamentName", "getFilamentAvatarUrl", "label", "color", "icon", "getLabel", "getColor", "getIcon", "getDescription", "options",
    "placeholder", "rendering", "rendered", "hydrate", "dehydrate", "updating", "updated", "exception", "getListeners", "getStats",
    "getData", "getType", "getOptions", "getHeading", "getTableQuery", "getFormSchema", "getTableColumns", "getEloquentQuery",
    "mutateFormDataBeforeCreate", "mutateFormDataBeforeSave", "afterCreate", "afterSave", "beforeCreate", "beforeSave", "getRedirectUrl",
    "getNavigationBadge", "canCreate", "canEdit", "canDelete", "canView", "canViewAny", "shouldRegisterNavigation", "getGloballySearchableAttributes",
}


class CallGraph:
    def __init__(self, proj, data):
        self.proj, self.idx, self.roles = proj, proj.idx, proj.roles
        self.models = data["models"]
        self.rels = {f: {r["name"]: r for r in m["relations"]} for f, m in self.models.items()}
        self.tables = {f: m["table"] for f, m in self.models.items()}
        a = data["async"]
        self.queued = {f for k in ("jobs", "listeners", "mail", "notifications") for f, d in a[k].items() if d.get("queued")}
        self.listeners = defaultdict(list)
        for w in a["wiring"]:
            if w.get("listener"):
                self.listeners[w["event"]].append((w["listener"], w.get("method") or "handle", w.get("source", "")))
        self.observers = {f: m["observers"] for f, m in self.models.items()}
        self.devents = {f: m["dispatches_events"] for f, m in self.models.items()}
        self.policies = {f: m["policy"] for f, m in self.models.items() if m.get("policy")}
        self.user_model = next((u for u in ("App\\Models\\User", "App\\User") if u in self.models), None)
        self.impls = defaultdict(set)
        for c in self.idx.by_fqn.values():
            if c.kind == "class" and not c.abstract:
                for x in set(self.idx.ancestors(c)) | self.idx.all_interfaces(c):
                    if self.idx.get(x):
                        self.impls[x].add(c.fqn)
        self.bindings = self._bindings()
        self.nodes, self.edges = {}, {}
        self.effects = defaultdict(dict)
        self.unresolved = defaultdict(dict)
        self._mcache, self._pcache = {}, {}
        self.roots = []
        self.route_roots = {}

    # ---- registry -----------------------------------------------------------------------------------
    def node(self, nid, kind, label, file=None, line=None, role=None):
        if nid not in self.nodes:
            self.nodes[nid] = [nid, kind, label, file, line or 0, role or ""]
        return nid

    def mnode(self, owner, m):
        c = self.idx.get(owner)
        return self.node(f"{owner}::{m.name}", "method", f"{short(owner)}::{m.name}()", c.file.rel if c else None, m.line,
                         self.roles.get(owner))

    def cnode(self, fqn, kind):
        c = self.idx.get(fqn)
        return self.node(fqn, kind, short(fqn), c.file.rel if c else None, c.line if c else 0, self.roles.get(fqn) or kind)

    def edge(self, f, t, k, conf, line, q=False):
        key = (f, t, k)
        old = self.edges.get(key)
        if old is None or CONF_RANK[conf] < CONF_RANK[old[3]]:
            self.edges[key] = [f, t, k, conf, line or 0, bool(q)]

    def effect(self, nid, k, d, line):
        if d:
            self.effects[nid].setdefault((k, str(d)[:120]), line or 0)

    # ---- class knowledge ----------------------------------------------------------------------------
    def find_method(self, cls, name):
        key = (cls, name)
        if key in self._mcache:
            return self._mcache[key]
        res, seen, queue = None, set(), [cls]
        while queue:
            f = queue.pop(0)
            if f in seen:
                continue
            seen.add(f)
            c = self.idx.get(f)
            if c is None:
                continue
            m = c.methods.get(name)
            if m is not None:
                res = (f, m)
                break
            queue.extend(c.traits)
            if c.extends:
                queue.append(c.extends)
        self._mcache[key] = res
        return res

    def targets(self, cls, name):
        """Methods a call may land on, following interfaces/abstracts to bound or implementing classes."""
        fm = self.find_method(cls, name)
        c = self.idx.get(cls)
        if fm and fm[1].body:
            return [(fm[0], fm[1], "exact")]
        cands = self.bindings.get(cls) or (self.impls.get(cls) if c is not None and (c.kind == "interface" or c.abstract or fm) else None)
        out = []
        if cands:
            conf = "inferred" if (cls in self.bindings or len(cands) == 1) else "possible"
            for i in sorted(cands):
                f2 = self.find_method(i, name)
                if f2 and f2[1].body:
                    out.append((f2[0], f2[1], conf))
        if not out and fm:
            out.append((fm[0], fm[1], "exact"))
        return out

    def _bindings(self):
        out = defaultdict(set)
        for prov in self.proj.classes_by_role("provider"):
            pf = prov.file
            for pname in ("bindings", "singletons"):
                v = prop_value(self.proj, prov, pname)
                if isinstance(v, dict):
                    for k, x in v.items():
                        if isinstance(x, str) and self.idx.get(str(x)):
                            out[str(k)].add(str(x))
            if not prov.body:
                continue
            T = pf.toks
            for k in range(prov.body[0], min(prov.body[1], len(T) - 1)):
                t = T[k]
                if t.k == "name" and t.v in ("bind", "singleton", "scoped", "bindIf", "singletonIf", "scopedIf") and k > 0 \
                        and T[k - 1].v in ("->", "::") and T[k + 1].v == "(":
                    close = pf.pair.get(k + 1, k + 1)
                    args, _ = pf.args(k + 2, close)
                    if not args or not isinstance(args[0], str):
                        continue
                    abstract = str(args[0])
                    if len(args) > 1 and isinstance(args[1], Cls):
                        out[abstract].add(str(args[1]))
                    elif len(args) > 1 and isinstance(args[1], Node) and args[1].type == "closure":
                        for f, _ln in pf.scan(args[1].start, args[1].end, prov.fqn, prov.extends).news:
                            if self.idx.get(f):
                                out[abstract].add(f)
                    elif len(args) == 1 and isinstance(args[0], Cls):
                        out[abstract].add(abstract)
        return out

    def framework_parent(self, cls):
        """True when the class inherits from something outside the project (properties may come from there)."""
        c = self.idx.get(cls)
        anc = self.idx.ancestors(c) if c else []
        return bool(anc) and not self.idx.get(anc[-1])

    def resolve_binding(self, cls, conf="exact"):
        if self.bindings.get(cls):
            return Ty(sorted(self.bindings[cls]), worst(conf, "inferred"))
        return Ty((cls,), conf)

    # ---- types ------------------------------------------------------------------------------------
    def ty(self, types, self_cls, conf="exact"):
        cls, coll = [], False
        for t in types or []:
            if not t:
                continue
            tl = t.lower()
            if tl in ("self", "static", "$this"):
                if self_cls:
                    cls.append(self_cls)
                continue
            if tl in BUILTIN_TYPES or tl in ("null", "?"):
                continue
            if t.endswith("[]"):
                coll, t = True, t[:-2]
            if t.startswith("Illuminate\\") and short(t) in ("Collection", "LazyCollection", "LengthAwarePaginator", "Paginator", "CursorPaginator"):
                coll = True
                continue
            cls.append(t)
        if not cls:
            return Ty(("~mixed",), conf, "coll") if coll else None
        return Ty(cls, conf, "coll" if coll else "obj")

    def ty_doc(self, s, pf, self_cls):
        s = s.strip().lstrip("?")
        m = re.match(r"^\\?[\w\\]+<(?:[^<>]*,\s*)?\\?([\w\\]+)>$", s)
        if m:
            return Ty([pf.type_name(m.group(1))], "inferred", "coll")
        parts = [p for p in s.split("|") if p and p.lower() != "null"]
        coll = any(p.endswith("[]") for p in parts)
        t = self.ty([pf.type_name(p[:-2] if p.endswith("[]") else p) for p in parts if re.fullmatch(r"\\?[\w\\]+(\[\])?", p)], self_cls, "inferred")
        if t is not None and coll:
            t.kind = "coll"
        return t

    def ret_ty(self, owner, m, recv, conf):
        r = (self.rels.get(owner) or {}).get(m.name)
        if r:
            if not r.get("related"):
                return None
            pivot = None
            if r["type"] in ("belongsToMany", "morphToMany", "morphedByMany"):
                a, b = sorted([snake(short(owner)), snake(short(r["related"]))])
                pivot = r.get("pivot_table") or f"{a}_{b}"
            return Ty((r["related"],), conf, "rel", pivot)
        c = self.idx.get(owner)
        if c is None:
            return None
        if m.returns:
            t = self.ty(m.returns.split("|"), recv, conf)
            if t is not None and t.kind != "coll":
                return t
        mm = re.search(r"@return\s+(\S+)", m.rawdoc or "")
        if mm:
            pf = c.file
            old = (pf._cur, pf._cur_parent)
            pf._cur, pf._cur_parent = owner, c.extends
            try:
                t = self.ty_doc(mm.group(1), pf, recv)
            finally:
                pf._cur, pf._cur_parent = old
            if t is not None:
                t.conf = worst(t.conf, conf)
                return t
        if m.returns:
            return EXT
        return None

    def prop_ty(self, cls, prop):
        key = (cls, prop)
        if key in self._pcache:
            return self._pcache[key]
        self._pcache[key] = None
        res, queue, seen = None, [cls], set()
        while queue and res is None:
            f = queue.pop(0)
            if f in seen:
                continue
            seen.add(f)
            c = self.idx.get(f)
            if c is None:
                continue
            p = c.props.get(prop)
            if p:
                if p.get("type"):
                    res = self.ty(p["type"].split("|"), f)
                if res is None and p.get("doc"):
                    mm = re.search(r"@var\s+(\S+)", p["doc"])
                    if mm:
                        res = self.ty_doc(mm.group(1), c.file, f)
            if res is None:
                res = self.assigned_ty(c, prop)
            queue.extend(c.traits)
            if c.extends:
                queue.append(c.extends)
        self._pcache[key] = res
        return res

    def assigned_ty(self, c, prop):
        pf, T = c.file, c.file.toks
        for m in c.methods.values():
            if not m.body:
                continue
            s, e = m.body
            for k in range(s, min(e, len(T)) - 4):
                if T[k].v != "$this" or T[k + 1].v != "->" or T[k + 2].v != prop or T[k + 3].v != "=":
                    continue
                nx = T[k + 4]
                if nx.k == "var":
                    p = next((p for p in m.params if p["name"] and "$" + p["name"] == nx.v), None)
                    if p and p["types"]:
                        t = self.ty(p["types"], c.fqn, "inferred")
                        if t is not None:
                            return t
                elif nx.k == "name" and nx.v.lower() == "new" and T[k + 5].k == "name":
                    return Ty((pf.resolve(T[k + 5].v),), "inferred")
                elif nx.k == "name" and nx.v.lower() in ("app", "resolve") and k + 7 < len(T) and T[k + 5].v == "(" \
                        and T[k + 6].k == "name" and T[k + 7].v == "::":
                    return self.resolve_binding(pf.resolve(T[k + 6].v), "inferred")
        return None

    # ---- walking method bodies ----------------------------------------------------------------------
    def walk(self, nid, pf, s, e, env, cls):
        old = (pf._cur, pf._cur_parent)
        c = self.idx.get(cls) if cls else None
        pf._cur, pf._cur_parent = cls, (c.extends if c else None)
        try:
            self._walk(nid, pf, s, e, env, cls)
        finally:
            pf._cur, pf._cur_parent = old

    @staticmethod
    def _chain_start(T, k, n):
        t = T[k]
        nxt = T[k + 1] if k + 1 < n else None
        if nxt is None:
            return False
        prev = T[k - 1] if k > 0 else None
        pv = prev.v.lower() if prev is not None else ""
        if t.k == "var":
            return nxt.v in ("->", "?->") and pv not in ("->", "?->", "::")
        if t.k != "name" or pv in ("->", "?->", "::", "new", "function", "fn", "const", "class", "use", "namespace", "instanceof",
                                   "extends", "implements", "case"):
            return False
        low = t.v.lower()
        if low == "new":
            return nxt.k == "name"
        if nxt.v == "::":
            return True
        if nxt.v == "(":
            return low not in PHP_KEYWORDS
        return False

    def _walk(self, nid, pf, s, e, env, cls):
        T = pf.toks
        n = min(e, len(T))
        k = s
        errs = (ParseError, IndexError, KeyError, TypeError, AttributeError, RecursionError, ValueError)
        while k < n:
            t = T[k]
            if t.doc and "@var" in t.doc:
                for m in re.finditer(r"@var\s+(\S+)\s+(\$\w+)", t.doc):
                    ty = self.ty_doc(m.group(1), pf, cls)
                    if ty is not None:
                        env[m.group(2)] = ty
            nxt = T[k + 1] if k + 1 < n else None
            if t.k == "name" and nxt is not None and nxt.k == "var" and t.v.lower() not in PHP_KEYWORDS and t.v.lower() not in BUILTIN_TYPES:
                ty = self.ty([pf.type_name(t.v)], cls)
                if ty is not None:
                    env[nxt.v] = ty
                k += 1
                continue
            if t.k == "var" and nxt is not None and nxt.k == "op" and nxt.v in ("=", "??="):
                ty = None
                try:
                    val, j = pf._postfix(k + 2, n)
                    if j >= n or T[j].v in (";", ")", ",", "]"):
                        ty = self.expr_ty(nid, pf, val, env, cls, False)
                except errs:
                    pass
                if ty is not None:
                    env[t.v] = ty
                elif nxt.v == "=":
                    env.pop(t.v, None)
                k += 2
                continue
            if t.k == "name" and t.v.lower() == "foreach" and nxt is not None and nxt.v == "(":
                close = pf.pair.get(k + 1, k + 1)
                asi = next((j for j in range(k + 2, close) if T[j].k == "name" and T[j].v.lower() == "as"), None)
                if asi is not None:
                    ty = None
                    try:
                        val, _ = pf._postfix(k + 2, asi)
                        ty = self.expr_ty(nid, pf, val, env, cls, False)
                    except errs:
                        pass
                    vs = [T[j].v for j in range(asi + 1, close) if T[j].k == "var"]
                    if ty is not None and ty.kind in ("coll", "rel", "builder") and vs:
                        env[vs[-1]] = Ty(ty.cls, worst(ty.conf, "inferred"), "obj")
                k += 2
                continue
            if self._chain_start(T, k, n):
                try:
                    val, _ = pf._postfix(k, n)
                    self.expr_ty(nid, pf, val, env, cls, True)
                except errs:
                    pass
            k += 1

    @staticmethod
    def _label(b):
        if isinstance(b, Node):
            if b.type == "var":
                return b.name
            if b.type == "static":
                return f"{short(b.cls)}::{b.name}()"
            if b.type == "call":
                return f"{b.name}()"
            if b.type == "new":
                return f"new {short(b.cls or '')}"
        return None

    def expr_ty(self, nid, pf, val, env, cls, record):
        if isinstance(val, Node) and val.type == "chain":
            base, calls = val.base, val.calls
        else:
            base, calls = val, []
        cur = self.base_ty(nid, pf, base, env, cls, record)
        label = self._label(base)
        for c in calls:
            if cur is None:
                if record and not c.prop and label and label.startswith("$") and label != "$this":
                    self.unresolved[nid].setdefault(f"{label}->{c.name}()", c.line or 0)
                return None
            cur = self.call_ty(nid, pf, cur, c, env, cls, record)
            label = (f"{label}->{c.name}" + ("" if c.prop else "()")) if label else None
        return cur

    def base_ty(self, nid, pf, b, env, cls, record):
        if isinstance(b, Node):
            if b.type == "var":
                if b.name == "$this":
                    return Ty((cls,), "exact") if cls else None
                return env.get(b.name)
            if b.type == "new":
                if not b.cls or b.cls == "class@anonymous":
                    return EXT
                if record:
                    self.on_new(nid, b.cls, b.line or 0)
                return Ty((b.cls,), "exact")
            if b.type == "static":
                return self.on_static(nid, pf, b, env, cls, record)
            if b.type == "call":
                return self.on_func(nid, b, record)
            if b.type == "closure":
                return EXT
            return None
        if b is None or isinstance(b, (str, int, float, list, dict, bool)):
            return EXT
        return None

    # ---- Laravel semantics --------------------------------------------------------------------------
    def on_class_dispatch(self, nid, f, line, conf="exact"):
        role = self.roles.get(f)
        if role == "job":
            hm = self.find_method(f, "handle") or self.find_method(f, "__invoke")
            self.edge(nid, self.mnode(*hm) if hm else self.cnode(f, "job"), "dispatch", conf, line, f in self.queued)
        elif role == "event":
            self.edge(nid, self.cnode(f, "event"), "event", conf, line)
        elif role == "mail":
            self.edge(nid, self.cnode(f, "mail"), "mail", conf, line, f in self.queued)
        elif role == "notification":
            self.edge(nid, self.cnode(f, "notification"), "notify", conf, line, f in self.queued)

    def on_new(self, nid, f, line):
        if self.roles.get(f) in ("job", "event", "mail", "notification"):
            self.on_class_dispatch(nid, f, line)
            return
        fm = self.find_method(f, "__construct")
        if fm and fm[1].body and fm[1].body[1] - fm[1].body[0] > 1 and fm[0] == f:
            self.edge(nid, self.mnode(*fm), "new", "exact", line)

    def model_events(self, nid, model, op, line, conf):
        evs = MODEL_EVENTS_FOR.get(op, [])
        for o in self.observers.get(model, []):
            for ev in evs:
                fm = self.find_method(o, ev)
                if fm:
                    self.edge(nid, self.mnode(*fm), "observer", worst(conf, "inferred"), line)
        for when, ev in (self.devents.get(model) or {}).items():
            if when in evs and self.idx.get(ev):
                self.on_class_dispatch(nid, ev, line, worst(conf, "inferred"))

    def authorize(self, nid, args, env, line):
        if not args or not isinstance(args[0], str):
            return
        ability, models = args[0], []
        if len(args) > 1:
            x = args[1]
            if isinstance(x, Cls):
                models = [str(x)]
            elif isinstance(x, list):
                models = class_strs(x)[:1]
            elif isinstance(x, Node) and x.type == "var" and x.name in env:
                models = list(env[x.name].cls)
        for mdl in models:
            pol = self.policies.get(mdl)
            fm = self.find_method(pol, ability) if pol else None
            if fm:
                self.edge(nid, self.mnode(*fm), "authorize", "inferred", line)

    def eloquent(self, nid, model, name, line, record, conf):
        tbl = self.tables.get(model, short(model))
        if name in EL_BUILDER:
            return Ty((model,), conf, "builder")
        if name in EL_FIND:
            if record and name not in ("make", "newModelInstance", "firstOrNew"):
                self.effect(nid, "db-read", tbl, line)
            return Ty((model,), conf, "obj")
        if name in EL_CREATE:
            if record:
                self.effect(nid, "db-write", f"{tbl} ({name})", line)
                self.model_events(nid, model, "create", line, conf)
            return Ty((model,), conf, "obj")
        if name in EL_LIST:
            if record:
                self.effect(nid, "db-read", tbl, line)
            return Ty((model,), conf, "coll")
        if name in EL_SCALAR:
            if record:
                self.effect(nid, "db-read", tbl, line)
            return EXT
        if name in EL_MASS_WRITE:
            if record:
                self.effect(nid, "db-write", f"{tbl} ({name})", line)
                if name == "destroy":
                    self.model_events(nid, model, "delete", line, conf)
            return EXT
        return Ty((model,), "inferred", "builder")

    def on_func(self, nid, b, record):
        name = b.name.split("\\")[-1].lower()
        a = b.args or []
        line = b.line or 0
        if name in ("app", "resolve") and a:
            cs = class_strs(a[0])
            return self.resolve_binding(cs[0]) if cs else EXT
        if name == "app":
            return Ty(("~app",), "exact", "app")
        if name == "auth":
            return Ty(("~auth",), "exact", "auth")
        if name == "request" and not a:
            return Ty(("Illuminate\\Http\\Request",), "exact")
        if record:
            if name == "view" and a and isinstance(a[0], str):
                self.effect(nid, "view", a[0], line)
            elif name == "inertia" and a and isinstance(a[0], str):
                self.effect(nid, "page", a[0], line)
            elif name in ("event", "dispatch", "dispatch_sync", "broadcast") and a and isinstance(a[0], Cls):
                self.on_class_dispatch(nid, str(a[0]), line)
        return EXT

    def on_static(self, nid, pf, b, env, cls, record):
        f, name, line = b.cls, b.name, b.line or 0
        a = b.args or []
        if f in self.models:
            fm = self.find_method(f, name)
            if fm and fm[1].body and (fm[1].static or name not in EL_BUILDER | EL_FIND | EL_CREATE | EL_LIST | EL_SCALAR | EL_MASS_WRITE):
                if record:
                    self.edge(nid, self.mnode(*fm), "call", "exact", line)
                return self.ret_ty(fm[0], fm[1], f, "exact")
            sc = self.find_method(f, "scope" + name[:1].upper() + name[1:])
            if sc:
                if record:
                    self.edge(nid, self.mnode(*sc), "scope", "exact", line)
                return Ty((f,), "exact", "builder")
            return self.eloquent(nid, f, name, line, record, "exact")
        if self.roles.get(f) in ("job", "event", "mail", "notification") and name in DISPATCH_STATICS | {"dispatchSync", "dispatchNow"}:
            if record:
                self.on_class_dispatch(nid, f, line)
            return EXT
        if self.idx.get(f):
            outs = []
            for owner, m, conf in self.targets(f, name):
                if record:
                    self.edge(nid, self.mnode(owner, m), "call", conf, line)
                outs.append(self.ret_ty(owner, m, f, conf))
            return merge_ty(outs) if outs else EXT
        sf = short(f)
        if sf in FACADE_KIND:
            t = Ty((sf,), "exact", FACADE_KIND[sf])
            if name in EFFECT_VERBS.get(t.kind, ()):
                return self.call_ty(nid, pf, t, Call(name, a, b.kw, line), env, cls, record)
            return t
        if sf == "DB":
            if name == "table" and a and isinstance(a[0], str):
                return Ty((a[0],), "exact", "table")
            if record and name in ("select", "insert", "update", "delete", "statement", "unprepared", "affectingStatement"):
                self.effect(nid, "db-read" if name == "select" else "db-write", f"raw SQL ({name})", line)
            return EXT
        if record and sf == "Gate" and name in AUTH_CALLS:
            self.authorize(nid, a, env, line)
        if sf == "Auth" and name == "user":
            return Ty((self.user_model,), "inferred") if self.user_model else EXT
        if sf == "Auth" and name == "guard":
            return Ty(("~auth",), "exact", "auth")
        if sf in ("App", "Container") and name in ("make", "get", "makeWith") and a:
            cs = class_strs(a[0])
            return self.resolve_binding(cs[0]) if cs else EXT
        if record and a and isinstance(a[0], str):
            if sf == "Inertia" and name == "render":
                self.effect(nid, "page", a[0], line)
            elif sf == "View" and name == "make":
                self.effect(nid, "view", a[0], line)
        if record and sf in ("Event", "Bus", "Queue") and name in ("dispatch", "dispatchSync", "dispatchNow", "push", "later"):
            for x in class_strs(a):
                self.on_class_dispatch(nid, x, line)
        return EXT

    def call_ty(self, nid, pf, cur, c, env, cls, record):
        name, line, k = c.name, c.line or 0, cur.kind
        if k == "ext":
            return EXT
        if k in ("http", "storage", "cache", "process", "artisan"):
            if name in EFFECT_VERBS.get(k, ()):
                if record:
                    arg = c.args[0] if c.args and isinstance(c.args[0], str) else ""
                    self.effect(nid, k, (f"{name.upper()} {arg}" if k == "http" else f"{name} {arg}").strip(), line)
                return EXT
            return cur
        if k == "app":
            if name in ("make", "makeWith", "get", "build") and c.args:
                cs = class_strs(c.args[0])
                return self.resolve_binding(cs[0]) if cs else EXT
            return EXT
        if k == "auth":
            if name == "user":
                return Ty((self.user_model,), "inferred") if self.user_model else EXT
            return cur if name == "guard" else EXT
        if k == "table":
            tbl = cur.cls[0]
            if name in EL_BUILDER:
                return cur
            if record:
                if name in EL_MASS_WRITE or name in ("insert", "updateOrInsert", "upsert", "insertGetId", "insertOrIgnore"):
                    self.effect(nid, "db-write", f"{tbl} ({name})", line)
                elif name in EL_FIND | EL_LIST | EL_SCALAR:
                    self.effect(nid, "db-read", tbl, line)
            return EXT
        if k == "builder":
            if c.args:
                nested = name in ("whereHas", "orWhereHas", "whereDoesntHave", "orWhereDoesntHave", "with", "withCount", "withWhereHas",
                                  "whereRelation", "load", "has")
                for a in list(c.args) + list(c.kw.values()):
                    for cl in ([a] if not isinstance(a, (list, dict)) else (a.values() if isinstance(a, dict) else a)):
                        if isinstance(cl, Node) and cl.type == "closure" and cl.params and cl.params[0]["name"] and not cl.params[0]["types"]:
                            env["$" + cl.params[0]["name"]] = EXT if nested else Ty(cur.cls, cur.conf, "builder")
            outs = []
            for mdl in cur.cls:
                sc = self.find_method(mdl, "scope" + name[:1].upper() + name[1:]) if mdl in self.models else None
                if sc:
                    if record:
                        self.edge(nid, self.mnode(*sc), "scope", cur.conf, line)
                    outs.append(Ty((mdl,), cur.conf, "builder"))
                elif mdl in self.models:
                    outs.append(self.eloquent(nid, mdl, name, line, record, cur.conf))
            return merge_ty(outs) or EXT
        if k == "rel":
            outs = []
            for mdl in cur.cls:
                if name in REL_WRITE:
                    if record:
                        tbl = cur.meta if (name in REL_PIVOT and cur.meta) else self.tables.get(mdl, short(mdl))
                        self.effect(nid, "db-write", f"{tbl} ({name})", line)
                        if name in ("create", "save", "createMany", "saveMany", "firstOrCreate", "updateOrCreate", "forceCreate"):
                            self.model_events(nid, mdl, "create", line, cur.conf)
                    outs.append(Ty((mdl,), cur.conf, "obj") if name in REL_RETURNS_MODEL else EXT)
                else:
                    outs.append(self.call_ty(nid, pf, Ty((mdl,), cur.conf, "builder"), c, env, cls, record))
            return merge_ty(outs) or EXT
        if k == "coll":
            if c.args and name in CLOSURE_ELEM:
                for a in c.args:
                    if isinstance(a, Node) and a.type == "closure" and a.params and a.params[0]["name"] and not a.params[0]["types"]:
                        env["$" + a.params[0]["name"]] = Ty(cur.cls, worst(cur.conf, "inferred"), "obj")
            if name in COLL_ELEM:
                return Ty(cur.cls, cur.conf, "obj")
            if name in COLL_SAME:
                return cur
            return EXT
        if c.prop:   # property access
            outs = []
            for x in cur.cls:
                r = (self.rels.get(x) or {}).get(name)
                if r and r.get("related"):
                    outs.append(Ty((r["related"],), worst(cur.conf, "inferred"), "coll" if r["type"] in REL_MANY else "obj"))
                    continue
                t = self.prop_ty(x, name) if self.idx.get(x) else None
                if t is not None:
                    outs.append(Ty(t.cls, worst(cur.conf, t.conf), t.kind, t.meta))
                elif not self.idx.get(x) or x in self.models or self.framework_parent(x):
                    outs.append(EXT)
            return merge_ty(outs)
        if record and name in AUTH_CALLS and c.args and isinstance(c.args[0], str):
            self.authorize(nid, c.args, env, line)
        outs, hit = [], False
        for x in cur.cls:
            tg = self.targets(x, name) if self.idx.get(x) else []
            if tg:
                hit = True
                for owner, m, conf in tg:
                    cf = worst(cur.conf, conf)
                    if record:
                        self.edge(nid, self.mnode(owner, m), "relation" if name in (self.rels.get(owner) or {}) else "call", cf, line)
                    outs.append(self.ret_ty(owner, m, x, cf))
                continue
            if x in self.models:
                if name in INST_WRITE:
                    hit = True
                    if record:
                        self.effect(nid, "db-write", f"{self.tables.get(x, short(x))} ({name})", line)
                        if INST_WRITE[name]:
                            self.model_events(nid, x, INST_WRITE[name], line, cur.conf)
                    outs.append(EXT)
                    continue
                if name in INST_READ:
                    hit = True
                    if record:
                        self.effect(nid, "db-read", self.tables.get(x, short(x)), line)
                    outs.append(Ty((x,), cur.conf))
                    continue
                if name in ("newQuery", "query"):
                    hit = True
                    outs.append(Ty((x,), cur.conf, "builder"))
                    continue
                if name in INST_SELF:
                    hit = True
                    outs.append(Ty((x,), cur.conf))
                    continue
            if name == "user" and (x.endswith("Request") or self.roles.get(x) == "request") and self.user_model:
                hit = True
                outs.append(Ty((self.user_model,), "inferred"))
        if outs:
            return merge_ty(outs)
        return None if hit else EXT

    # ---- entry points ---------------------------------------------------------------------------------
    def build(self, data):
        skip = {"test", "migration", "factory", "seeder"}
        for c in list(self.idx.by_fqn.values()):
            if c.role in skip:
                continue
            for m in list(c.methods.values()):
                if not m.body:
                    continue
                nid = self.mnode(c.fqn, m)
                env = {}
                for p in m.params:
                    if p["name"] and p["types"]:
                        t = self.ty(p["types"], c.fqn)
                        if t is not None:
                            env["$" + p["name"]] = t
                self.walk(nid, c.file, m.body[0], m.body[1], env, c.fqn)
        self.add_roots(data)
        self.finalize(data)
        return self

    def add_roots(self, data):
        mw = data["middleware"]
        groups, aliases = mw.get("groups") or {}, mw.get("aliases") or {}
        for i, r in enumerate(data["routes"]):
            t, ctrl, meth, line = r.get("action_type"), r.get("controller"), r.get("method"), r.get("line")
            label = f"{' '.join(m for m in r['methods'] if m != 'HEAD')} {r['uri']}"
            rid = f"route:{i}"
            if t in ("controller", "livewire", "filament") and ctrl and self.idx.get(ctrl):
                self.node(rid, "route", label, r.get("file"), line, "request")
                if t == "filament":
                    c = self.idx.get(ctrl)
                    res = prop_value(self.proj, c, "resource")
                    anc = " ".join(self.idx.ancestors(c))
                    if isinstance(res, str) and self.idx.get(str(res)):
                        mname = "table" if ("ListRecords" in anc or "ManageRecords" in anc) else "infolist" if "ViewRecord" in anc else "form"
                        fm = self.find_method(str(res), mname) or self.find_method(str(res), "form")
                        if fm:
                            self.edge(rid, self.mnode(*fm), "action", "inferred", line)
                    names = [x for x in c.methods if x in ("mount", "getHeaderActions", "table", "form", "getHeaderWidgets")]
                else:
                    names = [meth or "__invoke"] if t == "controller" else ["mount", "render"]
                for mn in names:
                    fm = self.find_method(ctrl, mn)
                    if not fm:
                        continue
                    self.edge(rid, self.mnode(*fm), "action", "exact", line)
                    if t == "controller":
                        for p in fm[1].params:
                            for ty in p["types"]:
                                if self.roles.get(ty) == "request":
                                    for rm in ("authorize", "rules", "prepareForValidation", "after", "withValidator"):
                                        f2 = self.find_method(ty, rm)
                                        if f2 and f2[1].body:
                                            self.edge(rid, self.mnode(*f2), "validate", "exact", line)
            elif t == "closure" and r.get("_closure"):
                rel, s, e, params = r["_closure"]
                pf = self.proj.php.get(rel)
                if pf is None:
                    continue
                self.node(rid, "route", label, r.get("file"), line, "request")
                cid = self.node(f"closure:{i}", "closure", f"Closure ({rel}:{line})", rel, line, "controller")
                env = {}
                for pname, ptypes in params:
                    t2 = self.ty(ptypes, None)
                    if t2 is not None and pname:
                        env["$" + pname] = t2
                self.walk(cid, pf, s, e, env, None)
                self.edge(rid, cid, "action", "exact", line)
            elif t in ("view", "volt", "redirect"):
                self.node(rid, "route", label, r.get("file"), line, "request")
                self.effect(rid, {"view": "view", "volt": "volt", "redirect": "redirect"}[t], r.get("view") or r.get("volt") or r.get("target"), line)
            else:
                continue
            for m in r["middleware"]:
                alias = m.split(":")[0]
                cands = list(groups.get(alias) or []) if alias in groups else [aliases.get(alias)] if alias in aliases else [alias] if "\\" in alias else []
                for x in cands:
                    if isinstance(x, str) and self.idx.get(x):
                        fm = self.find_method(x, "handle")
                        if fm and fm[1].body:
                            self.edge(rid, self.mnode(*fm), "middleware", "exact", 0)
                            continue
                        mc = self.idx.get(x)
                        for mm in mc.methods.values():
                            if mm.body and mm.visibility == "public" and not mm.name.startswith("__"):
                                self.edge(rid, self.mnode(x, mm), "middleware", "exact", 0)
            self.route_roots[i] = rid
            self.roots.append([rid, "Routes", label, r.get("action") or r.get("view") or "", i])
        for cmd in data["console"]["commands"]:
            fm = self.find_method(cmd["fqn"], "handle") or self.find_method(cmd["fqn"], "__invoke")
            if fm:
                rid = self.node(f"cmd:{cmd['fqn']}", "command", f"artisan {cmd['name']}", cmd["file"], cmd["line"], "command")
                self.edge(rid, self.mnode(*fm), "action", "exact", 0)
                self.roots.append([rid, "Artisan commands", f"artisan {cmd['name']}", short(cmd["fqn"]), None])
        cmd_by_name = {c["name"]: c["fqn"] for c in data["console"]["commands"]}
        jobs_by_short = {short(f): f for f in data["async"]["jobs"]}
        for j, s in enumerate(data["console"]["schedule"]):
            rid = self.node(f"sched:{j}", "schedule", f"{s['target']} ({s['frequency']})", s.get("file"), s.get("line"), "command")
            if s["type"] == "job" and s["target"] in jobs_by_short:
                self.on_class_dispatch(rid, jobs_by_short[s["target"]], s.get("line"))
            elif s["type"] == "command" and s["target"] in cmd_by_name:
                fm = self.find_method(cmd_by_name[s["target"]], "handle")
                if fm:
                    self.edge(rid, self.mnode(*fm), "action", "exact", s.get("line"))
            self.roots.append([rid, "Scheduled tasks", s["target"], s["frequency"], None])
        for comp in data["livewire"]["components"]:
            if not comp.get("fqn") or not self.idx.get(comp["fqn"]):
                continue
            rid = self.node(f"lw:{comp['fqn']}", "livewire", f"<livewire:{comp['alias']}>", comp["file"], comp["line"], "livewire")
            for mn in ["mount", "render"] + comp["actions"] + [x["method"] for x in comp["listens"]]:
                fm = self.find_method(comp["fqn"], mn)
                if fm:
                    self.edge(rid, self.mnode(*fm), "action", "exact", 0)
            self.roots.append([rid, "Livewire components", comp["alias"], short(comp["fqn"]), None])
        for group, bucket in (("Queued jobs", "jobs"), ("Listeners", "listeners")):
            for f in sorted(data["async"][bucket]):
                fm = self.find_method(f, "handle") or self.find_method(f, "__invoke")
                if fm:
                    self.roots.append([self.mnode(*fm), group, short(f), "queued" if f in self.queued else "sync", None])

    def finalize(self, data):
        for nid, n in list(self.nodes.items()):
            if n[1] == "event":
                for l, meth, src in self.listeners.get(nid, []):
                    fm = self.find_method(l, meth)
                    if fm:
                        self.edge(nid, self.mnode(*fm), "listener", "inferred" if "auto" in src or "type-hint" in src else "exact", 0, l in self.queued)
            elif n[1] == "mail":
                for v in data["async"]["mail"].get(nid, {}).get("views", []):
                    self.effect(nid, "view", v, 0)
            elif n[1] == "notification":
                for ch in data["async"]["notifications"].get(nid, {}).get("channels", []):
                    self.effect(nid, "channel", ch, 0)
                for mn in ("toMail", "toDatabase", "toBroadcast", "toArray"):
                    fm = self.find_method(nid, mn)
                    if fm and fm[0] == nid:
                        self.edge(nid, self.mnode(*fm), "call", "exact", 0)

    def unused_methods(self, data):
        incoming = {e[1] for e in self.edges.values()}
        words = Counter()
        for pf in self.proj.php.values():
            for t in pf.toks:
                if t.k == "name":
                    words[t.v] += 1
                elif t.k == "str" and len(t.v) < 200:
                    for w in re.findall(r"[A-Za-z_]\w*", t.v):
                        words[w] += 1
        skip_roles = {"test", "migration", "factory", "seeder", "livewire", "filament", "policy", "observer", "listener", "job", "command",
                      "middleware", "provider", "mail", "notification", "request", "resource", "component", "rule", "cast", "scope",
                      "exception", "event", "controller", "interface", "enum"}
        cands = []
        for c in self.idx.by_fqn.values():
            if c.role in skip_roles:
                continue
            rels = self.rels.get(c.fqn) or {}
            for m in c.methods.values():
                n = m.name
                if m.visibility != "public" or n.startswith("__") or n in CONVENTIONAL_METHODS or n in rels or not m.body:
                    continue
                if n.startswith("scope") or re.fullmatch(r"(get|set)\w+Attribute", n) or (m.returns and short(m.returns) == "Attribute"):
                    continue
                if f"{c.fqn}::{n}" in incoming:
                    continue
                cands.append((c, m))
        if cands:
            names = {m.name for _, m in cands}
            for ap, rel in walk(self.proj.root, "resources", exts=(".php", ".js", ".ts", ".vue", ".jsx", ".tsx")):
                for w in re.findall(r"[A-Za-z_]\w*", read_text(ap)):
                    if w in names:
                        words[w] += 1
        return [[f"{c.name}::{m.name}()", ROLE_INFO.get(c.role, {}).get("label", c.role), f"{c.file.rel}:{m.line}"]
                for c, m in cands if words[m.name] <= 1]

    def export(self):
        used = set()
        for e in self.edges.values():
            used.add(e[0])
            used.add(e[1])
        used |= set(self.effects) | set(self.unresolved) | {r[0] for r in self.roots}
        ids = [nid for nid in self.nodes if nid in used]
        pos = {nid: i for i, nid in enumerate(ids)}
        edges = [[pos[e[0]], pos[e[1]], EDGE_KINDS.index(e[2]), ["exact", "inferred", "possible"].index(e[3]), e[4], 1 if e[5] else 0]
                 for e in self.edges.values() if e[0] in pos and e[1] in pos]
        conf = Counter(e[3] for e in edges)
        return {"n": [self.nodes[i] for i in ids], "e": edges, "K": EDGE_KINDS, "C": ["exact", "inferred", "possible"],
                "x": {pos[n]: [[k, d, l] for (k, d), l in v.items()] for n, v in self.effects.items() if n in pos},
                "u": {pos[n]: [[x, l] for x, l in v.items()] for n, v in self.unresolved.items() if n in pos},
                "r": [[pos[r[0]], r[1], r[2], r[3], r[4]] for r in self.roots if r[0] in pos],
                "routes": {i: pos[rid] for i, rid in self.route_roots.items() if rid in pos},
                "pos": pos,
                "stats": {"methods": sum(1 for i in ids if self.nodes[i][1] == "method"), "edges": len(edges),
                          "exact": conf.get(0, 0), "inferred": conf.get(1, 0), "possible": conf.get(2, 0),
                          "unresolved": sum(len(v) for v in self.unresolved.values())}}


def build_call_graph(proj, data):
    cg = CallGraph(proj, data).build(data)
    out = cg.export()
    out["unused"] = cg.unused_methods(data)
    return out


# ---------------------------------------------------------------------------------------------- trace

TRACE_CSS = r"""
.trace { display: grid; grid-template-columns: minmax(240px, 330px) minmax(0, 1fr); gap: 18px; align-items: start; }
.trace-side { position: sticky; top: 16px; display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: 8px; max-height: calc(100vh - 32px);
              background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px; min-width: 0; }
.trace-tabs { display: flex; gap: 4px; }
.tt { flex: 1; font: 500 var(--step--1)/1 var(--font-body); padding: 8px; border-radius: 6px; border: 1px solid var(--line); background: var(--surface-2);
      color: var(--muted); cursor: pointer; }
.tt[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.trace-side input { font: inherit; font-size: var(--step--1); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--line-2);
                    background: var(--surface); color: var(--fg); min-width: 0; }
.trace-list { overflow-y: auto; min-height: 0; display: grid; gap: 10px; align-content: start; }
.trace-list h4 { font: 600 .6875rem/1 var(--font-mono); letter-spacing: .08em; text-transform: uppercase; color: var(--faint); padding: 6px 6px 2px; }
.trace-list ul { list-style: none; padding: 0; display: grid; gap: 1px; }
.trace-list button { width: 100%; text-align: left; background: none; border: 0; padding: 6px 8px; border-radius: 6px; cursor: pointer; color: var(--fg);
                     font: 500 .8125rem/1.35 var(--font-mono); display: grid; gap: 2px; overflow-wrap: anywhere; }
.trace-list button span { font: 400 .75rem/1.3 var(--font-body); color: var(--faint); }
.trace-list button:hover { background: var(--surface-2); }
.trace-list button[aria-current="true"] { background: var(--accent-soft); color: var(--accent); }
.trace-list .more { font-size: .75rem; color: var(--faint); padding: 4px 8px; }
.trace-main { display: grid; gap: 14px; min-width: 0; }
.trace-head { display: grid; gap: 4px; }
.trace-head h2 { font: 600 var(--step-1)/1.3 var(--font-mono); overflow-wrap: anywhere; }
.trace-sum { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 10px; }
.trace-sum .card { padding: 12px 14px; gap: 6px; }
.trace-sum h4 { font: 600 .6875rem/1 var(--font-mono); letter-spacing: .08em; text-transform: uppercase; color: var(--faint); }
.trace-sum .chips { gap: 4px; }
.entry-list { display: flex; flex-wrap: wrap; gap: 6px; }
.entry-list button, .lnkbtn { font: 500 .75rem/1.3 var(--font-mono); padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line);
                              background: var(--surface); color: var(--accent); cursor: pointer; }
ul.ttree, ul.ttree ul { list-style: none; margin: 0; padding-left: 0; }
ul.ttree { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 8px; overflow-x: auto; }
ul.ttree ul { padding-left: 16px; border-left: 1px dashed var(--line-2); margin-left: 10px; }
.tn > summary, .tn.leaf { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; padding: 4px 6px; border-radius: 6px; list-style: none; }
.tn > summary { cursor: pointer; }
.tn > summary::-webkit-details-marker { display: none; }
.tn > summary::before { content: "▸"; color: var(--faint); width: 10px; flex: none; }
.tn[open] > summary::before { content: "▾"; }
.tn.leaf { padding-left: 24px; }
.tn > summary:hover { background: var(--surface-2); }
.ek { font: 600 .6875rem/1.4 var(--font-mono); color: var(--faint); min-width: 4.5em; }
.ek-dispatch, .ek-event, .ek-listener, .ek-mail, .ek-notify { color: var(--role-job); }
.ek-middleware, .ek-validate, .ek-authorize { color: var(--role-middleware); }
.ek-observer { color: var(--role-observer); }
.nl { font: 500 .8125rem/1.4 var(--font-mono); display: inline-flex; gap: 6px; align-items: baseline; overflow-wrap: anywhere; color: var(--fg); }
.nl::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--dot, var(--faint)); flex: none; align-self: center; }
.fx { font: 500 .6875rem/1.4 var(--font-mono); padding: 0 6px; border-radius: 4px; background: var(--surface-2); color: var(--muted); border: 1px solid var(--line); max-width: 100%; overflow-wrap: anywhere; }
.fx-db-write { color: var(--warn); background: var(--warn-bg); border-color: transparent; }
.fx-db-read { color: var(--info); background: var(--info-bg); border-color: transparent; }
.fx-http { color: var(--crit); background: var(--crit-bg); border-color: transparent; }
.tn .count { font: 500 .6875rem/1 var(--font-mono); color: var(--faint); }
@media (max-width: 900px) { .trace { grid-template-columns: minmax(0, 1fr); } .trace-side { position: static; max-height: 48vh; } }
"""

JS_TRACE = r"""
(function () {
  const dataEl = document.getElementById('trace-data');
  if (!dataEl) return;
  const G = JSON.parse(dataEl.textContent);
  const N = G.n, K = G.K, C = G.C, fx = G.x || {}, un = G.u || {};
  const out = N.map(() => []), inn = N.map(() => []);
  G.e.forEach(e => { out[e[0]].push(e); inn[e[1]].push(e); });
  const ORDER = { middleware: 0, validate: 1, authorize: 2, action: 3 };
  const rank = e => { const k = K[e[2]]; return k in ORDER ? ORDER[k] : 4; };
  out.forEach(a => a.sort((x, y) => rank(x) - rank(y) || x[4] - y[4]));
  const rootOf = new Map(); G.r.forEach((r, i) => { if (!rootOf.has(r[0])) rootOf.set(r[0], i); });
  const KL = { call: 'calls', relation: 'relation', scope: 'scope', new: 'new', action: 'runs', middleware: 'middleware', validate: 'validates',
    authorize: 'authorises', dispatch: 'dispatches', event: 'fires', listener: 'listener', observer: 'observer', mail: 'sends mail', notify: 'notifies' };
  const FXL = { 'db-read': 'reads', 'db-write': 'writes', http: 'HTTP', storage: 'storage', cache: 'cache', view: 'view', page: 'page', volt: 'Volt',
    redirect: 'redirect to', process: 'process', artisan: 'artisan', channel: 'via' };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const list = document.getElementById('trace-list'), main = document.getElementById('trace-main'), q = document.getElementById('trace-q');
  let mode = 'roots', current = null;

  function ref(n) {
    if (!n[3]) return '';
    const t = n[3] + (n[4] ? ':' + n[4] : '');
    if (G.ed) return '<a class="ref" href="' + esc(G.ed.replace('{path}', G.root + '/' + n[3]).replace('{line}', n[4] || 1)) + '">' + esc(t) + '</a>';
    return '<span class="ref">' + esc(t) + '</span>';
  }
  function chips(i) { return (fx[i] || []).map(f => '<span class="fx fx-' + esc(f[0]) + '">' + esc(FXL[f[0]] || f[0]) + ' ' + esc(f[1]) + '</span>').join(''); }
  function row(i, e, note, rev) {
    const n = N[i], k = e ? K[e[2]] : '', conf = e ? C[e[3]] : 'exact';
    return (e ? '<span class="ek ek-' + k + '">' + esc(rev ? (KL[k] || k) + ' ←' : (KL[k] || k)) + '</span>' : '') +
      '<span class="nl" style="--dot: var(--role-' + esc(n[5] || 'other') + ')">' + esc(n[2]) + '</span>' +
      (conf !== 'exact' ? '<span class="badge ' + (conf === 'possible' ? 'warn' : 'info') + '" title="' + (conf === 'possible' ? 'One of several implementations' : 'Worked out from types or Laravel conventions') + '">' + conf + '</span>' : '') +
      (e && e[5] ? '<span class="badge info">queued</span>' : '') + (rootOf.has(i) && rev ? '<span class="badge ok">entry point</span>' : '') +
      (note ? '<span class="faint small">' + esc(note) + '</span>' : '') + ref(n) + (rev ? '' : chips(i)) +
      (!rev && un[i] ? '<span class="badge" title="' + esc(un[i].map(u => u[0]).join(', ')) + '">' + un[i].length + ' not followed</span>' : '');
  }
  function tree(i, e, depth, path, seen, rev) {
    const adj = rev ? inn[i] : out[i];
    const li = document.createElement('li');
    const leaf = (note) => { li.innerHTML = '<div class="tn leaf">' + row(i, e, note, rev) + '</div>'; return li; };
    if (!adj.length) return leaf('');
    if (path.has(i)) return leaf('↺ calls back into itself');
    if (seen.has(i)) return leaf('(expanded above)');
    seen.add(i);
    const d = document.createElement('details'); d.className = 'tn';
    const s = document.createElement('summary'); s.innerHTML = row(i, e, '', rev) + '<span class="count">' + adj.length + '</span>';
    d.appendChild(s); li.appendChild(d);
    let filled = false;
    const fill = () => {
      if (filled) return; filled = true;
      const ul = document.createElement('ul'); const np = new Set(path); np.add(i);
      adj.forEach(x => ul.appendChild(tree(rev ? x[0] : x[1], x, depth + 1, np, seen, rev)));
      d.appendChild(ul);
    };
    d.addEventListener('toggle', () => { if (d.open) fill(); });
    if (depth < (rev ? 5 : 4)) { d.open = true; fill(); }
    return li;
  }
  function reach(start) {
    const seen = new Set([start]), qu = [start];
    while (qu.length) { const i = qu.shift(); out[i].forEach(e => { if (!seen.has(e[1]) && seen.size < 6000) { seen.add(e[1]); qu.push(e[1]); } }); }
    return seen;
  }
  function summary(root) {
    const seen = reach(root), agg = {}, jobs = new Map(), events = new Set(), sends = new Set(), unres = [];
    let methods = 0;
    seen.forEach(i => {
      if (N[i][1] === 'method' || N[i][1] === 'closure') methods++;
      (fx[i] || []).forEach(f => { const key = f[0], val = key === 'db-write' ? f[1] : f[1]; (agg[key] = agg[key] || new Set()).add(val); });
      (un[i] || []).forEach(u => unres.push([i, u]));
      out[i].forEach(e => { const k = K[e[2]];
        if (k === 'dispatch') jobs.set(N[e[1]][2].replace('::handle()', '').replace('::__invoke()', ''), e[5]);
        if (k === 'event') events.add(N[e[1]][2]);
        if (k === 'mail' || k === 'notify') sends.add(N[e[1]][2] + (e[5] ? ' (queued)' : '')); });
    });
    const box = (title, items, cls) => '<div class="card"><h4>' + title + '</h4>' + (items.length ? '<div class="chips">' +
      items.map(x => '<span class="fx ' + (cls || '') + '">' + esc(x) + '</span>').join('') + '</div>' : '<p class="faint small">none</p>') + '</div>';
    const S = k => Array.from(agg[k] || []).sort();
    let h = '<div class="trace-sum">' + box('Writes', S('db-write'), 'fx-db-write') + box('Reads', S('db-read'), 'fx-db-read') +
      box('Queues jobs', Array.from(jobs).map(([j, qd]) => j + (qd ? ' (queued)' : ' (sync)'))) + box('Fires events', Array.from(events).sort()) +
      box('Sends', Array.from(sends).sort()) + box('External calls', S('http').concat(S('storage').map(x => 'storage ' + x)).concat(S('process')), 'fx-http') +
      box('Renders', S('page').map(x => 'page ' + x).concat(S('view').map(x => 'view ' + x)).concat(S('volt').map(x => 'Volt ' + x)).concat(S('redirect').map(x => '→ ' + x))) +
      box('Cache', S('cache')) + '</div>';
    h += '<p class="small muted">' + methods + ' methods reachable.' + (unres.length ? ' ' + unres.length + ' call(s) could not be followed (untyped variables): see the list under the tree.' : '') + '</p>';
    return [h, unres];
  }
  function setHash(h) { try { history.replaceState(null, '', '#' + h); } catch (e) { try { location.hash = h; } catch (e2) {} } }
  const focusMain = () => { if (window.innerWidth < 900) main.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  function showRoot(ri) {
    const r = G.r[ri], i = r[0];
    current = 'x' + ri;
    const [sum, unres] = summary(i);
    main.innerHTML = '<div class="trace-head"><div class="crumb">' + esc(r[1]) + '</div><h2>' + esc(r[2]) + '</h2>' +
      (r[3] ? '<p class="muted mono small">' + esc(r[3]) + '</p>' : '') + '</div>' + sum +
      '<h3>Call tree</h3><p class="small muted">Rows open three levels deep; click to go further. Blue badges are links worked out from types or Laravel conventions rather than read directly.</p>';
    const ul = document.createElement('ul'); ul.className = 'ttree';
    ul.appendChild(tree(i, null, 0, new Set(), new Set(), false)); main.appendChild(ul);
    if (unres.length) {
      const d = document.createElement('details'); d.className = 'box';
      d.innerHTML = '<summary>Calls that could not be followed (' + unres.length + ')</summary><div class="body"><ul>' +
        unres.map(([n, u]) => '<li><code>' + esc(u[0]) + '</code> in <span class="mono small">' + esc(N[n][2]) + '</span> ' + ref([0, 0, 0, N[n][3], u[1]]) + '</li>').join('') +
        '</ul><p class="small muted">Add a type hint or a <code>/** @var Foo $x */</code> comment and these become traceable.</p></div>';
      main.appendChild(d);
    }
    setHash(r[4] != null ? 'r-' + r[4] : 'x-' + ri);
    mark();
  }
  function entryPoints(i) {
    const seen = new Set([i]), qu = [i], found = [];
    while (qu.length) { const j = qu.shift(); if (rootOf.has(j) && j !== i) found.push(rootOf.get(j));
      inn[j].forEach(e => { if (!seen.has(e[0]) && seen.size < 6000) { seen.add(e[0]); qu.push(e[0]); } }); }
    return found;
  }
  function showMethod(i) {
    current = 'm' + i;
    const n = N[i], eps = entryPoints(i);
    main.innerHTML = '<div class="trace-head"><div class="crumb">Who calls</div><h2>' + esc(n[2]) + '</h2>' + ref(n) + '</div>' +
      '<div class="card"><h4>Reached from ' + eps.length + ' entry point' + (eps.length === 1 ? '' : 's') + '</h4>' +
      (eps.length ? '<div class="entry-list">' + eps.slice(0, 80).map(ri => '<button type="button" data-ri="' + ri + '">' + esc(G.r[ri][2]) + '</button>').join('') + '</div>'
        : '<p class="faint small">No route, command, job or component reaches this method through calls this map can see.</p>') + '</div>' +
      '<h3>Called by</h3>';
    if (!inn[i].length) main.insertAdjacentHTML('beforeend', '<p class="empty">No callers found. It may be unused, called from Blade or JavaScript, or called dynamically.</p>');
    else { const ul = document.createElement('ul'); ul.className = 'ttree'; ul.appendChild(tree(i, null, 0, new Set(), new Set(), true)); main.appendChild(ul); }
    main.querySelectorAll('[data-ri]').forEach(b => b.addEventListener('click', () => { setMode('roots'); showRoot(+b.getAttribute('data-ri')); }));
    setHash('m-' + i);
    mark();
  }
  function mark() { list.querySelectorAll('button[data-k]').forEach(b => b.setAttribute('aria-current', b.getAttribute('data-k') === current ? 'true' : 'false')); }
  function renderList() {
    const terms = q.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const hit = s => terms.every(t => s.toLowerCase().includes(t));
    let h = '';
    if (mode === 'roots') {
      const groups = new Map();
      G.r.forEach((r, ri) => { if (hit(r[2] + ' ' + r[3] + ' ' + r[1])) { if (!groups.has(r[1])) groups.set(r[1], []); groups.get(r[1]).push(ri); } });
      groups.forEach((ris, g) => {
        h += '<div><h4>' + esc(g) + ' · ' + ris.length + '</h4><ul>' + ris.slice(0, 300).map(ri => '<li><button type="button" data-k="x' + ri + '" data-ri="' + ri + '">' +
          esc(G.r[ri][2]) + (G.r[ri][3] ? '<span>' + esc(String(G.r[ri][3]).split('\\').pop()) + '</span>' : '') + '</button></li>').join('') +
          (ris.length > 300 ? '<li class="more">+' + (ris.length - 300) + ' more: refine the filter</li>' : '') + '</ul></div>';
      });
    } else {
      const ms = [];
      N.forEach((n, i) => { if (n[1] === 'method' && inn[i].length && hit(n[2])) ms.push(i); });
      ms.sort((a, b) => N[a][2].localeCompare(N[b][2]));
      h += '<div><h4>Methods with callers · ' + ms.length + '</h4><ul>' + ms.slice(0, 400).map(i => '<li><button type="button" data-k="m' + i + '" data-mi="' + i + '">' +
        esc(N[i][2]) + '<span>' + inn[i].length + ' caller' + (inn[i].length === 1 ? '' : 's') + '</span></button></li>').join('') +
        (ms.length > 400 ? '<li class="more">+' + (ms.length - 400) + ' more: refine the filter</li>' : '') + '</ul></div>';
    }
    list.innerHTML = h || '<p class="empty">Nothing matches.</p>';
    list.querySelectorAll('[data-ri]').forEach(b => b.addEventListener('click', () => { showRoot(+b.getAttribute('data-ri')); focusMain(); }));
    list.querySelectorAll('[data-mi]').forEach(b => b.addEventListener('click', () => { showMethod(+b.getAttribute('data-mi')); focusMain(); }));
    mark();
  }
  function setMode(m) {
    mode = m;
    document.querySelectorAll('.tt').forEach(b => b.setAttribute('aria-pressed', b.getAttribute('data-mode') === m ? 'true' : 'false'));
    q.placeholder = m === 'roots' ? 'Filter routes, commands, jobs, components…' : 'Find a method, e.g. Order::ship';
    renderList();
  }
  document.querySelectorAll('.tt').forEach(b => b.addEventListener('click', () => setMode(b.getAttribute('data-mode'))));
  q.addEventListener('input', renderList);
  function fromHash() {
    const h = (location.hash || '').slice(1);
    let m;
    if ((m = h.match(/^r-(\d+)$/))) { const ri = G.r.findIndex(r => r[4] === +m[1]); if (ri >= 0) { showRoot(ri); return true; } }
    if ((m = h.match(/^x-(\d+)$/)) && G.r[+m[1]]) { showRoot(+m[1]); return true; }
    if ((m = h.match(/^m-(\d+)$/)) && N[+m[1]]) { setMode('methods'); showMethod(+m[1]); return true; }
    return false;
  }
  setMode('roots');
  if (!fromHash()) {
    let best = 0, score = -1;
    G.r.forEach((r, ri) => { if (r[1] !== 'Routes') return; const s = reach(r[0]).size; if (s > score) { score = s; best = ri; } });
    if (G.r.length) showRoot(best);
  }
  window.addEventListener('hashchange', fromHash);
})();
"""


def page_trace(data, h, pages):
    g = data.get("calls")
    if not g or not g["r"]:
        return ("Request traces", "Follow what a request, command or job does.",
                callout("info", "No entry points found", "No routes, commands or jobs with PHP handlers were found to trace."))
    st = g["stats"]
    total = max(1, st["exact"] + st["inferred"] + st["possible"])
    pct = lambda n: f"{round(100 * n / total)}%"  # noqa: E731
    intro = callout("info", f"{st['edges']} call links between {st['methods']} methods",
                    f"{pct(st['exact'])} read directly from the code, {pct(st['inferred'])} worked out from type hints, return types or Laravel conventions "
                    f"(events → listeners, model writes → observers, authorize() → policies), {pct(st['possible'])} “possible” (one of several implementations). "
                    f"{st['unresolved']} call(s) on untyped variables couldn't be followed; each trace lists the ones it hits.")
    payload = {k: v for k, v in g.items() if k not in ("pos", "unused", "routes")}
    payload["ed"] = h.editor or ""
    payload["root"] = h.root if h.editor else ""
    js = json.dumps(payload, separators=(",", ":"), default=str).replace("</", "<\\/")
    body = (intro + '<div class="trace"><aside class="trace-side" aria-label="Entry points">'
            '<div class="trace-tabs"><button type="button" class="tt" data-mode="roots" aria-pressed="true">Entry points</button>'
            '<button type="button" class="tt" data-mode="methods" aria-pressed="false">Who calls…</button></div>'
            '<input type="search" id="trace-q" aria-label="Filter">'
            '<div class="trace-list" id="trace-list"></div></aside>'
            '<section class="trace-main" id="trace-main" aria-live="polite"><p class="muted">Pick an entry point.</p></section></div>'
            f'<script type="application/json" id="trace-data">{js}</script>')
    return ("Request traces", "Pick a route, command, job or Livewire component and follow every method it reaches, the tables it reads and writes, "
                              "and what it hands to the queue. Switch to “Who calls…” to go the other way.", body)


# =====================================================================================================
# 27. Changes baseline, output, CLI
# =====================================================================================================

GENERIC_DIR_NAMES = {"html", "www", "app", "src", "code", "project", "projects", "site", "web", "laravel", "repo", "public_html", "current"}


def slugify(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip()).strip("-.").lower()
    return s or "laravel-app"


def app_slug(root, composer):
    base = os.path.basename(os.path.abspath(root).rstrip(os.sep))
    if base.lower() in GENERIC_DIR_NAMES or not base:
        cn = (composer or {}).get("name", "")
        if cn and cn != "laravel/laravel":
            return slugify(cn.split("/")[-1])
    return slugify(base)


def resolve_out_dir(args, root):
    if args.out:
        return os.path.abspath(args.out), "given with --out"
    cwd = os.path.realpath(os.getcwd())
    if args.path is not None and os.path.realpath(root) != cwd:
        name = app_slug(root, read_json(os.path.join(root, "composer.json")))
        return os.path.join(cwd, f"{name}-map"), "current directory, named after the app"
    return os.path.join(root, OUT_DIR_NAME), "project root (git-ignored)"


def load_snapshots(snap_dir):
    out = []
    if not os.path.isdir(snap_dir):
        return out
    for f in sorted(os.listdir(snap_dir)):
        if f.endswith(".json"):
            d = read_json(os.path.join(snap_dir, f))
            if isinstance(d, dict) and "meta" in d:
                out.append((f, d))
    return out


def snapshot_from_commit(root, sha):
    tmp = extract_commit(root, sha)
    if not tmp:
        return None
    try:
        old, _ = analyze(tmp, light=True)
        return make_snapshot(old)
    except Exception as ex:  # noqa: BLE001 - a failed baseline must not kill the run
        log(f"could not analyse {sha[:8]}: {ex}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def commit_desc(root, sha):
    s = git(root, "log", "-1", "--format=%h%x1f%aI%x1f%an%x1f%s", sha) or ""
    p = s.strip().split("\x1f")
    if len(p) == 4:
        return {"sha": p[0], "date": p[1], "author": p[2], "subject": p[3]}
    return {"sha": sha[:8], "date": "", "author": "", "subject": ""}


def build_changes(data, out_dir, root, since):
    current = make_snapshot(data)
    head = (data.get("git") or {}).get("head")
    in_git = bool(data.get("git"))
    old, base_sha, baseline = None, None, None
    if since:
        if not in_git:
            data["notes"].append(f"--since {since} needs a git repository; skipped.")
        else:
            sha, desc = resolve_since(root, since)
            if sha:
                log(f"comparing with {sha[:8]} ({desc}) …")
                old = snapshot_from_commit(root, sha)
                base_sha = sha
                c = commit_desc(root, sha)
                baseline = {"label": f"{desc} (commit {c['sha']})", "detail": f"Committed {c['date'][:10]} by {c['author']}: “{c['subject']}”. Your working tree, including uncommitted edits, is compared with that commit."}
            else:
                data["notes"].append(desc)
    if old is None and base_sha is None:
        snaps = load_snapshots(os.path.join(out_dir, "snapshots"))
        pick = None
        for f, s in reversed(snaps):
            if s["meta"].get("git_sha") != head or not head:
                pick = (f, s)
                break
        if pick is None and snaps:
            pick = snaps[-1]
        if pick:
            f, old = pick
            sm = old["meta"]
            sha = sm.get("git_sha")
            if sha and in_git and git(root, "cat-file", "-e", f"{sha}^{{commit}}") is not None:
                base_sha = sha
            baseline = {"label": f"your previous map from {sm['generated'][:16].replace('T', ' ')} UTC ({rel_time(sm['generated'])})",
                        "detail": (f"That map was taken at commit {sha[:8]} on {sm.get('git_branch')}." if sha else "That map was taken outside git.")}
        elif in_git:
            sha = (git(root, "rev-list", "-1", "--before=30 days ago", "HEAD") or "").strip()
            label = "30 days ago (no earlier map of this checkout was found)"
            if not sha:
                roots = (git(root, "rev-list", "--max-parents=0", "HEAD") or "").split()
                sha = roots[0] if roots else ""
                label = "the first commit (the repository is younger than 30 days)"
            if sha and sha != head:
                log(f"no previous map, comparing with {sha[:8]} ({label}) …")
                old = snapshot_from_commit(root, sha)
                base_sha = sha
                c = commit_desc(root, sha)
                baseline = {"label": label, "detail": f"Baseline commit {c['sha']} from {c['date'][:10]}: “{c['subject']}”."}
    diff = diff_snapshots(old, current) if old else None
    act = git_activity(root, base_sha) if base_sha else None
    bits = []
    if act and act["commits"]:
        bits.append(f"{len(act['commits'])} commit{'s' if len(act['commits']) != 1 else ''} by {len(act['authors'])} {'person' if len(act['authors']) == 1 else 'people'}")
    if diff:
        for key, label in (("routes", "route"), ("models", "model"), ("migrations", "migration")):
            n = len(diff[key]["added"])
            if n:
                bits.append(f"{n} new {label}{'s' if n != 1 else ''}")
        n = len(diff["env"]["added"])
        if n:
            bits.append(f"{n} new env key{'s' if n != 1 else ''}")
        n = sum(len(diff[k]["added"]) + len(diff[k]["changed"]) + len(diff[k]["removed"]) for k in ("composer", "npm"))
        if n:
            bits.append(f"{n} package change{'s' if n != 1 else ''}")
        if diff["docker"]["added"] or diff["docker"]["changed"] or diff["dockerfiles"]["changed"]:
            bits.append("Docker changes")
    data["changes"] = {"baseline": baseline, "diff": diff, "git": act, "current": None,
                       "summary": (", ".join(bits) + f" since {baseline['label']}.") if bits and baseline else ""}
    data["catch_up"] = catch_up(data)
    return current


ASSETS = {"mermaid.min.js": (MERMAID_URL, "mermaid-10.9.1.min.js"), "d3.min.js": (D3_URL, "d3-7.9.0.min.js")}


def asset_cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "laravel_map")


def prepare_assets(out_dir):
    """Copy Mermaid and d3 next to the pages (downloading them once into a cache) so the map works offline."""
    import urllib.request
    cache = asset_cache_dir()
    os.makedirs(cache, exist_ok=True)
    dest = os.path.join(out_dir, "assets")
    os.makedirs(dest, exist_ok=True)
    ok = True
    for name, (url, cname) in ASSETS.items():
        cpath = os.path.join(cache, cname)
        if not os.path.exists(cpath) or os.path.getsize(cpath) < 10000:
            try:
                log(f"downloading {url} …")
                with urllib.request.urlopen(url, timeout=60) as resp, open(cpath + ".part", "wb") as fh:
                    shutil.copyfileobj(resp, fh)
                os.replace(cpath + ".part", cpath)
            except (OSError, ValueError) as ex:
                log(f"could not download {name} ({ex}); pages will use the CDN instead")
                ok = False
                continue
        shutil.copyfile(cpath, os.path.join(dest, name))
    return ok


def write_output(data, out_dir, editor):
    os.makedirs(out_dir, exist_ok=True)
    gi = os.path.join(out_dir, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as fh:
            fh.write("# Generated by laravel_map.py: ignore this whole folder\n*\n")
    h = Html(data["meta"]["root"], editor)
    pages = {f for f, *_ in PAGES}
    if not (data["livewire"]["components"] or data["livewire"]["forms"]):
        pages.discard("livewire.html")
    if not (data["filament"]["panels"] or data["filament"]["resources"]):
        pages.discard("filament.html")
    if not data.get("calls"):
        pages.discard("trace.html")
    routes = [r for r in data["routes"] if r.get("source") != "package (inferred)"]
    crit_warn = sum(1 for i in data["insights"] if i["severity"] in ("crit", "warn"))
    counts = {"routes.html": len(routes), "models.html": len(data["models"]), "database.html": len(data["schema"]),
              "http.html": sum(1 for c in data["classes"] if c["role"] == "controller"),
              "events.html": len(data["async"]["events"]) + len(data["async"]["jobs"]) or "",
              "frontend.html": len(data["views"]) + len(data["inertia_pages"]) or "",
              "livewire.html": len(data["livewire"]["components"]), "filament.html": len(data["filament"]["resources"]),
              "trace.html": len((data.get("calls") or {}).get("r") or []) or "",
              "classes.html": len(data["classes"]), "docker.html": len([s for s in data["docker"]["services"] if not s.get("only_in")]) or "",
              "config.html": len(data["env"]["matrix"]), "insights.html": crit_warn or "",
              "changes.html": ((data.get("changes") or {}).get("diff") or {}).get("total") or ""}
    builders = {"index.html": page_index, "start.html": page_start, "changes.html": page_changes, "routes.html": page_routes,
                "http.html": page_http, "trace.html": page_trace, "models.html": page_models, "database.html": page_database, "events.html": page_events,
                "frontend.html": page_frontend, "livewire.html": page_livewire, "filament.html": page_filament,
                "classes.html": page_classes, "docker.html": page_docker, "config.html": page_config, "insights.html": page_insights}
    written = []
    for f, *_ in PAGES:
        if f not in pages:
            stale = os.path.join(out_dir, f)
            if os.path.exists(stale):
                os.remove(stale)
            continue
        try:
            title, lede, body = builders[f](data, h, pages)
        except Exception as ex:  # noqa: BLE001 - one broken page should not stop the others
            import traceback
            traceback.print_exc()
            title, lede, body = f.replace(".html", "").title(), "This page could not be generated.", callout("crit", "Error while building this page", e(repr(ex)))
        doc = page_shell(data, f, title, lede, body, counts, pages, with_graph='data-graph' in body)
        with open(os.path.join(out_dir, f), "w", encoding="utf-8") as fh:
            fh.write(doc)
        written.append(f)
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as fh:
        slim = {k: v for k, v in data.items() if k not in ("file_hashes", "_assets_local", "calls")}
        if data.get("calls"):
            slim["calls"] = {k: v for k, v in data["calls"].items() if k != "pos"}
        json.dump(slim, fh, indent=1, default=str)
    return written


def save_snapshot(out_dir, snap, keep=20):
    d = os.path.join(out_dir, "snapshots")
    os.makedirs(d, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    sha = (snap["meta"].get("git_sha") or "nogit")[:8]
    with open(os.path.join(d, f"{stamp}_{sha}.json"), "w", encoding="utf-8") as fh:
        json.dump(snap, fh, default=str)
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    for f in files[:-keep]:
        os.remove(os.path.join(d, f))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="laravel_map.py", description="Explore, explain and visualise a Laravel codebase and its Docker dev environment as linked HTML pages.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="examples:\n"
                                        "  python3 laravel_map.py                       # inside a Laravel repo -> ./laravel-map/\n"
                                        "  python3 laravel_map.py ~/code/shop-app       # -> ./shop-app-map/ in the current directory\n"
                                        "  python3 laravel_map.py --since main          # what changed compared with main\n"
                                        "  python3 laravel_map.py --since \"2026-09-01\"  # back from leave: everything since that date\n"
                                        "  python3 laravel_map.py --artisan auto --db   # add live routes/migrations/columns from the running containers\n")
    ap.add_argument("path", nargs="?", default=None, help="Laravel project directory (default: current directory)")
    ap.add_argument("-o", "--out", help="output directory (default: <project>/laravel-map, or ./<app>-map when PATH is given)")
    ap.add_argument("--since", metavar="REF_OR_DATE", help='baseline for "What changed": branch, tag, sha, or a date like 2026-09-01 / "3 weeks ago"')
    ap.add_argument("--artisan", nargs="?", const="auto", metavar="CMD",
                    help='enrich with live data via artisan: "auto" (default when the flag is given) or a command prefix, e.g. "docker compose exec -T app php artisan"')
    ap.add_argument("--db", action="store_true", help="with --artisan: read real columns from the database via `artisan model:show`")
    ap.add_argument("--editor", default="auto", help="clickable file links: auto, vscode, cursor, phpstorm, idea, sublime, zed, none, or a URL template with {path} and {line}")
    ap.add_argument("--no-snapshot", action="store_true", help="don't save this run as the baseline for the next one")
    ap.add_argument("--offline", action="store_true", help="bundle Mermaid and d3 into <out>/assets so diagrams work without internet (downloaded once, then cached)")
    ap.add_argument("--open", action="store_true", help="open index.html in your browser when done")
    ap.add_argument("--version", action="version", version=f"laravel_map.py {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(os.path.expanduser(args.path or "."))
    if not os.path.isdir(root):
        ap.error(f"{root} is not a directory")
    looks_laravel = os.path.exists(os.path.join(root, "artisan")) or "laravel/framework" in json.dumps((read_json(os.path.join(root, "composer.json")) or {}).get("require", {}))
    if not looks_laravel:
        if not os.path.exists(os.path.join(root, "composer.json")):
            ap.error(f"{root} doesn't look like a Laravel project (no artisan file and no composer.json)")
        log("warning: laravel/framework not found in composer.json, mapping anyway")
    out_dir, why = resolve_out_dir(args, root)
    if os.path.realpath(out_dir) == os.path.realpath(root):
        ap.error("the output directory can't be the project directory itself")
    print(f"Mapping {root}", file=sys.stderr)
    data, proj = analyze(root, artisan=args.artisan, want_db=args.db)
    snap = build_changes(data, out_dir, root, args.since)
    editor = pick_editor(args.editor, root)
    os.makedirs(out_dir, exist_ok=True)
    data["_assets_local"] = prepare_assets(out_dir) if args.offline else os.path.exists(os.path.join(out_dir, "assets", "mermaid.min.js"))
    written = write_output(data, out_dir, editor)
    if not args.no_snapshot:
        save_snapshot(out_dir, snap)
    idx_path = os.path.join(out_dir, "index.html")
    routes = [r for r in data["routes"] if r.get("source") != "package (inferred)"]
    print(f"\n  {data['meta']['name']} · Laravel {data['stack']['laravel'] or '?'} · {', '.join(data['stack']['frontend'])}", file=sys.stderr)
    print(f"  {len(routes)} routes, {len(data['models'])} models, {len(data['schema'])} tables, {len(data['classes'])} classes, "
          f"{len([s for s in data['docker']['services'] if not s.get('only_in')])} Docker services", file=sys.stderr)
    ch = data.get("changes") or {}
    if ch.get("summary"):
        print(f"  Changes: {ch['summary']}", file=sys.stderr)
    for st in (data.get("catch_up") or [])[:6]:
        print(f"  → {st['title']}" + (f": {st['command']}" if st.get("command") else ""), file=sys.stderr)
    crit = [i for i in data["insights"] if i["severity"] == "crit"]
    for i in crit[:5]:
        print(f"  ! {i['title']}", file=sys.stderr)
    for n in data["notes"][:8]:
        print(f"  note: {n}", file=sys.stderr)
    print(f"\n  Wrote {len(written)} pages + data.json to {out_dir} ({why})", file=sys.stderr)
    print(f"  Open: {idx_path}", file=sys.stderr)
    if args.open:
        webbrowser.open("file://" + idx_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
