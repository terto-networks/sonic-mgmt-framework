#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste dos PTYPEs regexp do klish TertoOS (cli-xml/tertoos/*.xml).

Por que existe: o clish monta a regex de validacao como "^" + pattern + "$"
(klish 2.1.4, clish/ptype/ptype.c, clish_ptype__set_pattern) e compila com
regcomp(REG_EXTENDED | REG_NOSUB) (method="regexp") ou regcomp(REG_EXTENDED)
(method="regexp_select", patch Dell ptype.c.diff). Um pattern com "|" no
nivel de topo SEM grupo externo vira "^a|b|c$": o ^ so ancora a 1a
alternativa, o $ so a ultima e as do meio casam em qualquer posicao. Foi
assim que TERTOOS_RANGE_1_16 aceitava "17" e TERTOOS_RANGE_0_65535 "70000".

O que o teste faz (sem dependencia externa, so python3 da stdlib):
  1. LINT: nenhum pattern regexp/regexp_select pode ter "|" no nivel de topo.
  2. RANGES: todo TERTOOS_RANGE_<min>_<max> (e os ranges com nome proprio:
     VLAN, MTU, MPLS label, VRF table id, prioridades STP) e testado de forma
     EXAUSTIVA de 0 ate max+1 (limitado a EXHAUSTIVE_LIMIT) e nas fronteiras
     min, max, min-1, max+1, um valor grande, zero a esquerda e lixo colado.
  3. ENUMS: todo regexp_select com ext_pattern estatico aceita cada item e
     rejeita o item com lixo colado antes/depois.
  4. OUTROS: casos manuais e gerados (ASN asplain+asdot, RD/RT, IFNUM,
     IPv4 addr/prefix com octeto 0..300 em cada posicao, WireGuard key).

Motor de regex: por padrao usa o regcomp/regexec da libc via ctypes (POSIX
ERE de verdade, o MESMO que o clish usa) quando disponivel (Linux/glibc);
senao cai no modulo `re` do Python (os construtos usados nestes patterns —
classes, {m,n}, grupos, | — tem a mesma semantica de aceitar/rejeitar numa
regex ancorada). O motor usado e impresso na saida.

Uso:
  python3 CLI/clitree/scripts/test_ptype_patterns.py            # arvore do repo
  python3 CLI/clitree/scripts/test_ptype_patterns.py --xml X.xml # outro arquivo
  python3 CLI/clitree/scripts/test_ptype_patterns.py --engine re # forca o `re`
  make -C CLI/clitree test-ptypes
Sai com 0 se tudo passa, 1 se algo falha.
"""

import argparse
import base64
import ctypes
import ctypes.util
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GLOB = os.path.join(HERE, "..", "cli-xml", "tertoos", "*.xml")

# Varredura exaustiva ate este valor (acima disso, so fronteiras).
EXHAUSTIVE_LIMIT = 70000

# Falhas ESPERADAS e ja consertadas em outro PR ainda nao mergeado.
# Nao-estrito: se o item passar (o outro PR entrou), so avisa para remover.
#   (vazio: o TERTOOS_RANGE_0_65535 entrou com o PR #82)
XFAIL = {}

# Ranges com nome proprio: nome -> conjunto valido (lista de (min, max)).
NAMED_RANGES = {
    "TERTOOS_MPLS_LABEL": [(16, 1048575)],
    "TERTOOS_VLAN_ID": [(1, 4094)],
    "TERTOOS_MTU": [(64, 9216)],
    "TERTOOS_VRF_TABLE_ID": [(1, 252), (256, 4294967295)],
    # forma asplain do ASN (a asdot X.Y vai nos casos MANUAL e no check_asdot)
    "TERTOOS_ASN": [(1, 4294967295)],
    "TERTOOS_PW_ID": [(1, 4294967295)],
    "TERTOOS_STP_COST": [(1, 200000000)],
}

# Conjuntos discretos: nome -> valores validos.
NAMED_SETS = {
    "TERTOOS_STP_PRIORITY": {k * 4096 for k in range(16)},
    "TERTOOS_STP_PORT_PRIORITY": {k * 16 for k in range(16)},
}

# Casos manuais: nome -> (validos, invalidos).
MANUAL = {
    "TERTOOS_ASN": (
        # asdot (RFC 5396) como o FRR aceita: X e Y 0..65535, exceto 0.0
        ["1", "65000", "4200000000", "4294967295", "1.0", "0.1", "0.65535",
         "65535.0", "65535.65535"],
        ["0", "abc", "1abc", "65000x", "1.2.3", "x1.0", "01", "0.0",
         "65536.0", "1.65536", "01.1", "1.01", "1.", ".1", "4294967296",
         "99999999999"],
    ),
    "TERTOOS_IPV4_ADDR": (
        ["0.0.0.0", "10.0.0.1", "192.168.1.255", "255.255.255.255", "1.2.3.4"],
        ["256.0.0.1", "1.2.3.256", "999.999.999.999", "01.2.3.4", "1.2.3.04",
         "1.2.3", "1.2.3.4.5", "1.2.3.4x", "1.2.3.4/24", "a.b.c.d", ""],
    ),
    "TERTOOS_IPV4_PREFIX": (
        ["0.0.0.0/0", "10.0.0.0/8", "192.168.1.0/24", "10.255.30.2/32",
         "255.255.255.255/32"],
        ["10.0.0.0/33", "10.0.0.0/08", "256.0.0.0/8", "10.0.0.00/8",
         "999.1.1.1/24", "10.0.0.0", "10.0.0.0/", "10.0.0.0/24x", "10.0.0.0/-1"],
    ),
    "TERTOOS_RD": (
        ["65000:100", "0:0", "10.0.0.1:5"],
        ["65000:100x", "x65000:100", "65000", "10.0.0.1:5x", "1:2:3"],
    ),
    "TERTOOS_RT": (
        ["65000:100", "10.0.0.1:5"],
        ["65000:100x", "x65000:100", "65000"],
    ),
    "TERTOOS_IFNUM": (
        ["0", "1", "0.100", ".100", "26"],
        ["0abc", "1.2.3", "x1", ".", "1."],
    ),
}

# WireGuard: 32 bytes em base64 = 44 chars (43 + "="); o 43o char so carrega
# 4 bits (os 2 de enchimento sao zero), logo e um de [AEIMQUYcgkosw048].
_WG_VALID = [base64.b64encode(bytes((i * k) % 256 for i in range(32))).decode()
             for k in (0, 1, 7, 13, 255)]
MANUAL["TERTOOS_WGKEY"] = (
    _WG_VALID + ["YAnz0sGpUeLlsh3PJ6TEobyzn6TQP8VFXXa0+V+Zs3k="],
    [_WG_VALID[1][:43],              # 43 chars, sem "="
     _WG_VALID[1] + "=",             # 45 chars
     _WG_VALID[1][:42] + "==",       # padding de 2 bytes (nao sao 32 bytes)
     _WG_VALID[1][:42] + "B=",       # 43o char com bits de enchimento != 0
     _WG_VALID[1][:43] + "A",        # 44 chars sem "="
     "x" + _WG_VALID[1],
     _WG_VALID[1][:41] + "-A=",      # char fora do alfabeto base64
     ""],
)


def octet_cases():
    """IPv4 com octeto 0..300 em cada posicao + zero a esquerda."""
    cases = []
    for o in range(0, 301):
        for tpl in ("%d.0.0.1", "10.%d.0.1", "10.0.%d.1", "10.0.0.%d"):
            cases.append((tpl % o, o <= 255))
    for o in ("00", "01", "001", "010", "0255"):
        cases.append(("10.0.0.%s" % o, False))
        cases.append(("%s.0.0.1" % o, False))
    return cases


def asdot_cases():
    """asdot X.Y nas fronteiras de X e Y (0, 1, 65535, 65536)."""
    cases = []
    for x in (0, 1, 2, 9, 10, 65534, 65535, 65536, 99999):
        for y in (0, 1, 2, 9, 10, 65534, 65535, 65536, 99999):
            ok = x <= 65535 and y <= 65535 and not (x == 0 and y == 0)
            cases.append(("%d.%d" % (x, y), ok))
    return cases


# ---------------------------------------------------------------- motores
class PosixEngine:
    """regcomp/regexec da libc — exatamente o que o clish chama."""

    REG_EXTENDED = 1
    REG_NOSUB = 8  # glibc

    def __init__(self):
        name = ctypes.util.find_library("c")
        if not name or not sys.platform.startswith("linux"):
            raise OSError("libc POSIX regex not available")
        self.libc = ctypes.CDLL(name)
        self.libc.regcomp.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.libc.regexec.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int
        ]
        self.libc.regfree.argtypes = [ctypes.c_void_p]
        self.name = "posix-libc (%s)" % name

    def compile(self, anchored):
        buf = ctypes.create_string_buffer(256)  # regex_t (64 bytes na glibc x86_64/arm64)
        rc = self.libc.regcomp(buf, anchored.encode(), self.REG_EXTENDED | self.REG_NOSUB)
        if rc != 0:
            raise ValueError("regcomp failed (%d) for %r" % (rc, anchored))
        libc = self.libc

        def match(text):
            return libc.regexec(buf, text.encode(), 0, None, 0) == 0

        match._keep = buf  # mantem o buffer vivo
        return match


class PyReEngine:
    name = "python-re (fallback)"

    def compile(self, anchored):
        rx = re.compile(anchored)
        return lambda text: rx.search(text) is not None


def make_engine(kind):
    if kind in ("auto", "posix"):
        try:
            return PosixEngine()
        except OSError:
            if kind == "posix":
                raise
    return PyReEngine()


# ---------------------------------------------------------------- helpers
def toplevel_bar(pattern):
    """True se o pattern tem '|' fora de qualquer grupo/classe."""
    depth, in_class, i = 0, False, 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
            if pattern[i + 1:i + 2] == "^":
                i += 1
            if pattern[i + 1:i + 2] == "]":
                i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            return True
        i += 1
    return False


def load_ptypes(paths):
    out = []
    for path in paths:
        for el in ET.parse(path).getroot().iter():
            if el.tag.split("}")[-1] != "PTYPE":
                continue
            if el.get("method") not in ("regexp", "regexp_select"):
                continue
            if el.get("pattern") is None:
                continue
            out.append((os.path.basename(path), el))
    return out


def in_ranges(v, ranges):
    return any(lo <= v <= hi for lo, hi in ranges)


def range_cases(ranges):
    """Valores de fronteira + exaustivo ate EXHAUSTIVE_LIMIT."""
    lo = min(r[0] for r in ranges)
    hi = max(r[1] for r in ranges)
    vals = set(range(0, min(hi + 1, EXHAUSTIVE_LIMIT) + 1))
    for a, b in ranges:
        vals.update({a, b, a - 1, b + 1})
    vals.update({hi * 10 + 7, 99999999999, 10 ** 12})
    cases = [(str(v), in_ranges(v, ranges)) for v in sorted(vals) if v >= 0]
    # lixo e formato: zero a esquerda, sufixo/prefixo nao numerico,
    # max concatenado com ele mesmo, sinal.
    cases += [
        ("0" + str(lo), False) if lo > 0 else ("00", False),
        (str(lo) + "x", False),
        ("x" + str(hi), False),
        (str(hi) + str(hi), in_ranges(int(str(hi) + str(hi)), ranges)),
        ("-" + str(lo), False),
        ("", False),
    ]
    return cases


def enum_items(el):
    ext = el.get("ext_pattern")
    if not ext or el.get("ext_pattern_cmd"):
        return None
    items = []
    for tok in ext.split():
        m = re.match(r"^[^()]*\(([^()]*)\)$", tok)
        items.append(m.group(1) if m else tok)
    return items


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--xml", action="append", help="XML file(s) to check (default: cli-xml/tertoos/*.xml)")
    ap.add_argument("--engine", choices=["auto", "posix", "re"], default="auto")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    paths = args.xml or sorted(glob.glob(DEFAULT_GLOB))
    engine = make_engine(args.engine)
    ptypes = load_ptypes(paths)
    print("engine: %s" % engine.name)
    print("ptypes regexp/regexp_select: %d (files: %d)" % (len(ptypes), len(paths)))

    failures = {}   # nome -> [mensagens]
    checked = {"lint": 0, "range": 0, "set": 0, "enum": 0, "manual": 0}

    def fail(name, msg):
        failures.setdefault(name, []).append(msg)

    for fname, el in ptypes:
        name, pattern = el.get("name"), el.get("pattern")
        anchored = "^" + pattern + "$"   # exatamente como o clish
        match = engine.compile(anchored)

        checked["lint"] += 1
        if toplevel_bar(pattern):
            fail(name, "top-level '|' without an outer group: ^%s$" % pattern)

        m = re.match(r"^TERTOOS_RANGE_(\d+)_(\d+)$", name)
        ranges = [(int(m.group(1)), int(m.group(2)))] if m else NAMED_RANGES.get(name)
        if ranges:
            checked["range"] += 1
            bad = [(t, exp) for t, exp in range_cases(ranges) if match(t) != exp]
            for t, exp in bad[:5]:
                fail(name, "%r should be %s" % (t, "ACCEPTED" if exp else "REJECTED"))
            if len(bad) > 5:
                fail(name, "... and %d more wrong values" % (len(bad) - 5))

        if name in NAMED_SETS:
            checked["set"] += 1
            valid = NAMED_SETS[name]
            probe = set(range(0, max(valid) + 2)) | {max(valid) * 10, 99999999}
            probe_s = [str(v) for v in sorted(probe)] + ["0" + str(max(valid)), str(max(valid)) + "x"]
            bad = [t for t in probe_s if match(t) != (t.isdigit() and t == str(int(t)) and int(t) in valid)]
            for t in bad[:5]:
                fail(name, "%r wrong (accepted=%s)" % (t, match(t)))

        items = enum_items(el)
        if items is not None and el.get("method") == "regexp_select":
            checked["enum"] += 1
            for it in items:
                if not match(it):
                    fail(name, "enum item %r REJECTED" % it)
                # So para enums fechados (pattern = alternancia). Um pattern
                # livre de proposito (ex.: TERTOOS_IMAGE_SLOT aceita nome de
                # imagem) nao e enum fechado.
                if "|" not in pattern:
                    continue
                for junk in (it + "x", "x" + it, it + "-" + it):
                    if junk not in items and match(junk):
                        fail(name, "%r should be REJECTED" % junk)

        extra = []
        if name == "TERTOOS_IPV4_ADDR":
            extra = octet_cases()
        elif name == "TERTOOS_IPV4_PREFIX":
            extra = [(a + "/24", ok) for a, ok in octet_cases()]
            extra += [("10.0.0.0/%d" % m, m <= 32) for m in range(0, 40)]
        elif name == "TERTOOS_ASN":
            extra = asdot_cases()
        if extra:
            checked["generated"] = checked.get("generated", 0) + 1
            bad = [(t, exp) for t, exp in extra if match(t) != exp]
            for t, exp in bad[:5]:
                fail(name, "%r should be %s" % (t, "ACCEPTED" if exp else "REJECTED"))
            if len(bad) > 5:
                fail(name, "... and %d more wrong values" % (len(bad) - 5))

        if name in MANUAL:
            checked["manual"] += 1
            good, bad = MANUAL[name]
            for t in good:
                if not match(t):
                    fail(name, "%r should be ACCEPTED" % t)
            for t in bad:
                if match(t):
                    fail(name, "%r should be REJECTED" % t)

    print("checked: " + ", ".join("%s=%d" % kv for kv in checked.items()))

    rc = 0
    xfailed = []
    for name in sorted(failures):
        if name in XFAIL:
            xfailed.append(name)
            print("XFAIL %s (%s)" % (name, XFAIL[name]))
            if args.verbose:
                for msg in failures[name]:
                    print("      %s" % msg)
            continue
        rc = 1
        print("FAIL  %s" % name)
        for msg in failures[name]:
            print("      %s" % msg)
    for name in sorted(set(XFAIL) - set(failures)):
        if any(el.get("name") == name for _, el in ptypes):
            print("XPASS %s - it is fixed now: remove it from XFAIL in %s" % (name, os.path.basename(__file__)))

    bad = len([n for n in failures if n not in XFAIL])
    print("%s: %d ptype(s) failing, %d xfail" % ("FAILED" if rc else "OK", bad, len(xfailed)))
    return rc


if __name__ == "__main__":
    sys.exit(main())
