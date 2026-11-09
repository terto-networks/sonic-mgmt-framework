#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auditoria das variaveis de view (viewid) do klish TertoOS (cli-xml/tertoos/*.xml).

Por que existe: no klish 2.1.4 as variaveis de view vivem no nivel do pwd
(clish/shell/shell_pwd.c, clish_shell__set_pwd). TODA troca de view por um
COMMAND (ou PARAM, patch Dell) com `view=` cria um pwd NOVO cujas variaveis
sao SO as do `viewid` desse comando — expandido no contexto da view de
ORIGEM antes da troca (shell_var.c, find_viewid_var le so pwdv[depth]).
Um `exit` com `view="pai"` e SEM viewid volta para o pai com as variaveis
ZERADAS. Foi assim (HW 09/11, v0.12.229) que:

  l2vpn xconnect group INTERATIVA
   p2p pw-502
    exit
   p2p pw-503          -> gravou l2vpn/xconnect//pw-503 (grupo vazio)

  router ospf 1
   area 0.0.0.0
    exit
   area 0.0.0.1        -> gravou ospf//area/0.0.0.1/... (vrf vazia)

O que o teste faz (sem dependencia externa, so python3 da stdlib):
  1. Para cada VIEW, PROVIDED = nomes de variavel que algum comando de
     entrada atribui no viewid; REQUIRED = os ${x} de PROVIDED que a view
     usa (prompt, ACTION, viewid dos seus comandos, qualquer atributo).
  2. TODO comando/PARAM com `view=V` precisa ter no seu viewid TODAS as
     REQUIRED(V). Falta = erro "missing" (o bug do exit acima).
  3. Cada ${y} usado no VALOR de um viewid precisa existir na view de
     origem: ser PARAM do proprio comando ou ser atribuido por TODAS as
     entradas da view de origem. Senao = erro "unavailable" (ex.: exit da
     area querendo ${ospfid} sem a area carregar ospfid).

Uso:
  python3 CLI/clitree/scripts/test_view_vars.py            # arvore do repo
  python3 CLI/clitree/scripts/test_view_vars.py --xml X.xml [--xml Y.xml]
  make -C CLI/clitree test-viewvars
Sai com 0 se tudo passa, 1 se algo falha.
"""

import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GLOB = os.path.join(HERE, "..", "cli-xml", "tertoos", "*.xml")

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")


def local(tag):
    return tag.split("}")[-1]


def parse_viewid(viewid):
    """'a=${x};b=lit' -> {'a': '${x}', 'b': 'lit'}"""
    out = {}
    if not viewid:
        return out
    for part in viewid.split(";"):
        part = part.strip()
        if not part:
            continue
        key, _, val = part.partition("=")
        out[key.strip()] = val.strip()
    return out


def text_vars(el):
    """Todos os ${x} de um elemento: atributos e texto, recursivo."""
    found = set()
    for node in el.iter():
        for val in node.attrib.values():
            found.update(VAR_RE.findall(val))
        if node.text:
            found.update(VAR_RE.findall(node.text))
    return found


def param_names(cmd):
    return {p.get("name") for p in cmd.iter() if local(p.tag) == "PARAM" and p.get("name")}


class Transition:
    """Um comando (ou PARAM) que troca de view."""

    def __init__(self, src_file, src_view, cmd, target, viewid, who):
        self.src_file = src_file
        self.src_view = src_view
        self.cmd = cmd
        self.target = target
        self.viewid = parse_viewid(viewid)
        self.who = who  # nome do comando (e do PARAM, se for o caso)


def load(paths):
    views = {}  # nome -> lista de elementos VIEW (pode estar em varios arquivos)
    transitions = []
    for path in paths:
        fname = os.path.basename(path)
        for view in ET.parse(path).getroot().iter():
            if local(view.tag) != "VIEW":
                continue
            vname = view.get("name")
            views.setdefault(vname, []).append(view)
            for cmd in view:
                if local(cmd.tag) != "COMMAND":
                    continue
                cname = cmd.get("name")
                if cmd.get("view"):
                    transitions.append(Transition(fname, vname, cmd, cmd.get("view"),
                                                  cmd.get("viewid"), cname))
                # Patch Dell (shell_execute.c.diff): PARAM com view= sobrepoe a
                # view do comando; o viewid do PARAM sobrepoe so se existir.
                for p in cmd.iter():
                    if local(p.tag) == "PARAM" and p.get("view"):
                        transitions.append(Transition(
                            fname, vname, cmd, p.get("view"),
                            p.get("viewid") or cmd.get("viewid"),
                            "%s <%s>" % (cname, p.get("name"))))
    return views, transitions


def audit(paths):
    views, transitions = load(paths)

    entries = {}
    for t in transitions:
        entries.setdefault(t.target, []).append(t)

    provided = {v: set().union(*[set(t.viewid) for t in ts]) for v, ts in entries.items()}
    # O que a view de origem garantidamente tem: o que TODAS as entradas atribuem.
    available = {}
    for v, ts in entries.items():
        sets = [set(t.viewid) for t in ts]
        available[v] = set.intersection(*sets) if sets else set()

    required = {}
    for vname, els in views.items():
        used = set()
        for el in els:
            used |= text_vars(el)
        required[vname] = used & provided.get(vname, set())

    errors = []
    warnings = []
    for t in transitions:
        need = required.get(t.target, set())
        missing = sorted(need - set(t.viewid))
        if missing:
            errors.append("%s: view %s: command '%s' -> %s: missing viewid vars %s"
                          % (t.src_file, t.src_view, t.who, t.target, ", ".join(missing)))
        # Variavel que outra entrada da view atribui mas ninguem usa hoje: nao
        # quebra nada agora, mas quebra no dia em que alguem passar a usar.
        extra = sorted(provided.get(t.target, set()) - need - set(t.viewid))
        if extra:
            warnings.append("%s: view %s: command '%s' -> %s: viewid drops unused vars %s"
                            % (t.src_file, t.src_view, t.who, t.target, ", ".join(extra)))
        params = param_names(t.cmd)
        src_avail = available.get(t.src_view, set())
        for key, val in t.viewid.items():
            for ref in VAR_RE.findall(val):
                if ref in params or ref in src_avail:
                    continue
                errors.append("%s: view %s: command '%s' -> %s: viewid %s=%s uses ${%s},"
                              " not available in %s"
                              % (t.src_file, t.src_view, t.who, t.target, key, val, ref,
                                 t.src_view))
    return errors, warnings, transitions, required


# Reproducao minima do bug de HW 09/11 (exit do p2p sem viewid) — garante
# que a auditoria continua pegando o caso que motivou o teste.
SELFTEST_XML = """<?xml version="1.0"?>
<CLISH_MODULE xmlns="http://www.dellemc.com/sonic/XMLSchema">
  <VIEW name="config-view">
    <COMMAND name="group" view="g-view" viewid="grp=${name}">
      <PARAM name="name" ptype="STRING"/>
    </COMMAND>
  </VIEW>
  <VIEW name="g-view" prompt="(g-${grp})# ">
    <COMMAND name="exit" view="config-view"/>
    <COMMAND name="p2p" view="p-view" viewid="grp=${grp};p2p=${name}">
      <PARAM name="name" ptype="STRING"/>
      <ACTION>set x/${grp}/${name}</ACTION>
    </COMMAND>
  </VIEW>
  <VIEW name="p-view" prompt="(g-${grp}-p-${p2p})# ">
    <COMMAND name="exit" view="g-view"/>
  </VIEW>
</CLISH_MODULE>
"""


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "selftest.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SELFTEST_XML)
        errors = audit([path])[0]
    want = "command 'exit' -> g-view: missing viewid vars grp"
    if not any(want in e for e in errors):
        print("FAIL selftest: audit did not flag the p2p exit without viewid: %s" % errors)
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--xml", action="append", help="XML a auditar (repetivel)")
    ap.add_argument("-v", "--verbose", action="store_true", help="lista as views com variaveis")
    args = ap.parse_args()

    paths = args.xml or sorted(glob.glob(DEFAULT_GLOB))
    if not paths:
        print("no XML found", file=sys.stderr)
        return 1

    if not selftest():
        return 1
    errors, warnings, transitions, required = audit(paths)
    if args.verbose:
        for v in sorted(required):
            if required[v]:
                print("view %-40s needs %s" % (v, ", ".join(sorted(required[v]))))
    for w in warnings:
        print("WARN " + w)
    for e in errors:
        print("FAIL " + e)
    print("%d files, %d view transitions checked, %d errors, %d warnings"
          % (len(paths), len(transitions), len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
