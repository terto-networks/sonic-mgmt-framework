#!/usr/bin/env python3
"""Inject parent COMMAND placeholders for tertoos multi-word commands.

Klish requires <COMMAND name="X"/> as a placeholder before
<COMMAND name="X Y"/>; without it, multi-word commands with a PARAM
are unparseable at runtime ("Invalid input detected at ^") even
though xmllint passes. Legacy Dell SONiC XMLs encode the placeholders
by hand (e.g. cli-xml/ipv4.xml has <COMMAND name="ip"/> before
<COMMAND name="ip address">). The tertoos IOS-XR overlay was authored
without parents.

This pass runs AFTER klish_ins_def_cmd and BEFORE xmllint. It only
processes the numbered tertoos files (NN-*.xml) and skips placeholders
whose name already exists as a standalone COMMAND anywhere in the
command-tree (avoiding dup-merge errors when the same VIEW is declared
in multiple files).
"""
import sys
import os
import re
from lxml import etree

NS = "http://www.dellemc.com/sonic/XMLSchema"
VIEW_T = f"{{{NS}}}VIEW"
CMD_T = f"{{{NS}}}COMMAND"


def collect_global_view_cmds(target):
    """Map view_name -> set of cmd names already present in any XML."""
    res = {}
    for fn in os.listdir(target):
        if not fn.endswith(".xml"):
            continue
        try:
            tree = etree.parse(os.path.join(target, fn),
                               etree.XMLParser(resolve_entities=False))
        except Exception:
            continue
        for view in tree.iter(VIEW_T):
            vn = view.get("name")
            if not vn:
                continue
            s = res.setdefault(vn, set())
            for child in view:
                if child.tag == CMD_T and child.get("name"):
                    s.add(child.get("name"))
    return res


def fix_view(view, global_view_cmds):
    vn = view.get("name")
    if not vn:
        return 0
    have_here = set()
    for child in view:
        if child.tag == CMD_T and child.get("name"):
            have_here.add(child.get("name"))
    needed = set()
    for n in list(have_here):
        toks = n.split()
        for i in range(1, len(toks)):
            needed.add(" ".join(toks[:i]))
    global_here = global_view_cmds.setdefault(vn, set())
    to_add = sorted(needed - global_here,
                    key=lambda x: (x.count(" "), x))
    for name in to_add:
        ph = etree.SubElement(view, CMD_T)
        ph.set("name", name)
        ph.set("help", f"({name} commands)")
        view.insert(0, ph)
        global_here.add(name)
    return len(to_add)


def fix_file(path, global_view_cmds):
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    tree = etree.parse(path, parser)
    total = sum(fix_view(v, global_view_cmds) for v in tree.iter(VIEW_T))
    if total:
        tree.write(path, xml_declaration=True,
                   encoding=tree.docinfo.encoding, pretty_print=True)
    return total


TERTOOS_FILE_RE = re.compile(r"^[0-3][0-9][-]")


def inject_parents(target, debug=False):
    """Walk every tertoos NN-*.xml in target and add parent placeholders."""
    global_view_cmds = collect_global_view_cmds(target)
    grand = 0
    for fn in sorted(os.listdir(target)):
        if not fn.endswith(".xml"):
            continue
        if not TERTOOS_FILE_RE.match(fn):
            continue
        n = fix_file(os.path.join(target, fn), global_view_cmds)
        if n and debug:
            print(f"{fn}: +{n}")
        grand += n
    if debug:
        print(f"klish_inject_parents: total {grand}")
    return grand


if __name__ == "__main__":
    inject_parents(sys.argv[1], debug=True)
