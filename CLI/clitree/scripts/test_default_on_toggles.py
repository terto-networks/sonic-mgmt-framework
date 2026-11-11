#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste dos comandos liga/desliga do klish TertoOS cujo leaf tem padrao LIGADO.

Por que existe: quando o padrao do produto e' "ligado", apagar o leaf do
candidate NAO desliga a funcao - o backend (cfgd) volta ao padrao. Entao o
`no <comando>` precisa GRAVAR o valor de "desligado" (candidate set ... false /
disable), e o comando positivo precisa gravar o de "ligado" (para desfazer um
`no` anterior). Se alguem trocar o `no` por um `candidate delete`, o operador
digita `no ...`, o commit passa e nada muda na caixa.

Casos cobertos:
  - mpls ldp / address-family / label local allocate host-routes
    (MPLS_LDP_AF.label-local-allocate-host-only, default true - 10/11/2026)
  - mpls ldp / install allow-broken-lsp
    (MPLS_LDP_ROUTER.allow-broken-lsp, default enable - 19/10/2026)

Sem dependencia externa (so python3 da stdlib).

Uso:
  python3 CLI/clitree/scripts/test_default_on_toggles.py
  make -C CLI/clitree test-default-on
Sai com 0 se tudo passa, 1 se algo falha.
"""

import glob
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
XML_GLOB = os.path.join(HERE, "..", "cli-xml", "tertoos", "*.xml")

# (view, comando, ACTION esperada)
CASES = [
    (
        "config-mpls-ldp-af-view",
        "label local allocate host-routes",
        "tertoos-cli candidate set mpls/ldp/${ldpvrf}/af/${ldpafi}/label-local-allocate-host-only true",
    ),
    (
        "config-mpls-ldp-af-view",
        "no label local allocate host-routes",
        "tertoos-cli candidate set mpls/ldp/${ldpvrf}/af/${ldpafi}/label-local-allocate-host-only false",
    ),
    (
        "config-mpls-ldp-view",
        "install allow-broken-lsp",
        "tertoos-cli candidate set mpls/ldp/${ldpvrf}/allow-broken-lsp enable",
    ),
    (
        "config-mpls-ldp-view",
        "no install allow-broken-lsp",
        "tertoos-cli candidate set mpls/ldp/${ldpvrf}/allow-broken-lsp disable",
    ),
]


def local(tag):
    return tag.split("}")[-1]


def load_commands():
    """{(view, comando): [ACTION, ...]} de todos os XML do TertoOS."""
    found = {}
    for path in sorted(glob.glob(XML_GLOB)):
        root = ET.parse(path).getroot()
        for view in root.iter():
            if local(view.tag) != "VIEW":
                continue
            for cmd in view:
                if local(cmd.tag) != "COMMAND":
                    continue
                actions = [
                    " ".join((a.text or "").split())
                    for a in cmd
                    if local(a.tag) == "ACTION"
                ]
                key = (view.get("name"), cmd.get("name"))
                found.setdefault(key, []).extend(actions)
    return found


def main():
    found = load_commands()
    errors = []
    for view, name, want in CASES:
        actions = found.get((view, name))
        if actions is None:
            errors.append("missing: view %s has no command `%s`" % (view, name))
            continue
        if actions != [want]:
            errors.append(
                "wrong action: `%s` in %s; want: %s; got: %s"
                % (name, view, want, actions)
            )
        if not name.startswith("no "):
            continue
        # O `no` de um padrao ligado nunca pode apagar o leaf.
        for action in actions:
            if "candidate delete" in action:
                errors.append(
                    "`%s` in %s deletes the leaf (deleting restores the default = ON)"
                    % (name, view)
                )
    for e in errors:
        print("FAIL " + e)
    print(
        "default-on toggles: %d cases, %d failures" % (len(CASES), len(errors))
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
