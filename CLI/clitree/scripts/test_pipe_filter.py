#!/usr/bin/env python3
"""Testes do filtro `show ... | include/exclude/begin/count` (TertoOS, 20/11/2026).

- tos_pipe.py (renderer/scripts): logica dos filtros;
- klish_insert_pipe.wrap_text: a ACTION embrulhada executa IGUAL ao original sem filtro
  e passa a saida pelo filtro com filtro (roda em /bin/sh, simulando a expansao do klish);
- include/pipe.xml: todo regex usa TERTOOS_PIPE_REGEX (sem aspa simples) e nao ha' `save`.

Uso: python3 scripts/test_pipe_filter.py   (de CLI/clitree; sai 1 se algo falhar)
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CLITREE = os.path.dirname(HERE)
RENDERER = os.path.join(os.path.dirname(CLITREE), "renderer", "scripts")
sys.path.insert(0, RENDERER)
sys.path.insert(0, HERE)

import tos_pipe  # noqa: E402

SAMPLE = [
    "Codes: K - kernel route, C - connected, O - OSPF\n",
    "O>* 10.255.30.2/32 [110/1] via 10.99.0.1, Ethernet25.1001\n",
    "O>* 10.255.30.3/32 [110/2] via 10.99.0.1, Ethernet25.1001\n",
    "C>* 10.99.0.0/30 is directly connected, Ethernet25.1001\n",
    "S>* 192.168.0.0/24 is directly connected, end0\n",
]


def run(argv, lines=SAMPLE):
    return list(tos_pipe.apply(tos_pipe.parse_stages(argv), iter(lines)))


def st(*ops):
    """st(("include","x",""), ...) -> argv de 9 posicoes (3 estagios)."""
    argv = []
    for op in ops:
        argv += list(op)
    argv += [""] * (9 - len(argv))
    return argv


class TestTosPipe(unittest.TestCase):
    def test_sem_filtro_passa_tudo(self):
        self.assertEqual(run(st()), SAMPLE)

    def test_include(self):
        self.assertEqual(run(st(("include", "^O", ""))), SAMPLE[1:3])

    def test_exclude(self):
        self.assertEqual(run(st(("exclude", "Ethernet25", ""))), [SAMPLE[0], SAMPLE[4]])

    def test_begin(self):
        self.assertEqual(run(st(("begin", "^C>", ""))), SAMPLE[3:])

    def test_count(self):
        self.assertEqual(run(st(("count", "", ""))), ["Count: 5 lines\n"])
        self.assertEqual(run(st(("count", "", "")), []), ["Count: 0 lines\n"])
        self.assertEqual(run(st(("count", "", "")), ["x\n"]), ["Count: 1 line\n"])

    def test_apelidos_sonic(self):
        self.assertEqual(run(st(("grep", "^O", ""))), run(st(("include", "^O", ""))))
        self.assertEqual(run(st(("except", "^O", ""))), run(st(("exclude", "^O", ""))))
        self.assertEqual(run(st(("find", "^C>", ""))), run(st(("begin", "^C>", ""))))

    def test_ignore_case(self):
        self.assertEqual(run(st(("include", "ethernet25", ""))), [])
        self.assertEqual(len(run(st(("include", "ethernet25", "ignore-case")))), 3)

    def test_tres_estagios(self):
        out = run(st(("include", "Ethernet25", ""), ("exclude", r"30\.3", ""), ("count", "", "")))
        self.assertEqual(out, ["Count: 2 lines\n"])

    def test_no_more_e_noop(self):
        self.assertEqual(run(st(("no-more", "", ""))), SAMPLE)

    def test_regex_com_espaco_e_especiais(self):
        self.assertEqual(run(st(("include", r"directly connected, end0$", ""))), [SAMPLE[4]])
        self.assertEqual(run(st(("include", r"\[110/(1|2)\]", ""))), SAMPLE[1:3])

    def test_regex_invalido(self):
        with self.assertRaises(tos_pipe.PipeError):
            tos_pipe.parse_stages(st(("include", "(", "")))

    def test_filtro_sem_regex(self):
        with self.assertRaises(tos_pipe.PipeError):
            tos_pipe.parse_stages(st(("include", "", "")))

    def test_operacao_desconhecida(self):
        with self.assertRaises(tos_pipe.PipeError):
            tos_pipe.parse_stages(st(("save", "x", "")))


def klish_expand(text, values):
    """Simula o klish p/ ${^var} (sem escape): troca pelo valor ou vazio."""
    return re.sub(r"\$\{\^([^}]+)\}", lambda m: values.get(m.group(1), ""), text)


@unittest.skipUnless(shutil.which("sh"), "precisa de /bin/sh")
class TestWrap(unittest.TestCase):
    ORIG = "printf 'linha A\\nlinha B (x)\\nfim\\n'\nfalse && echo nunca\n"

    def sh(self, text, values, script_path):
        body = klish_expand(text, values).replace(
            "python3 " + __import__("klish_insert_pipe").TOS_PIPE_SCRIPT,
            shlex.quote(sys.executable.replace("\\", "/")) + " " + shlex.quote(script_path.replace("\\", "/")))
        return subprocess.run(["sh", "-c", body], capture_output=True, text=True)

    def setUp(self):
        import klish_insert_pipe
        self.kip = klish_insert_pipe
        self.script = os.path.join(RENDERER, "tos_pipe.py")

    def test_sem_filtro_igual_ao_original(self):
        wrapped = self.kip.wrap_text(self.ORIG)
        a = self.sh(wrapped, {}, self.script)
        b = subprocess.run(["sh", "-c", self.ORIG], capture_output=True, text=True)
        self.assertEqual((a.stdout, a.returncode), (b.stdout, b.returncode))

    def test_exit_do_original_preservado(self):
        wrapped = self.kip.wrap_text("echo antes\nexit 3\necho depois\n")
        r = self.sh(wrapped, {}, self.script)
        self.assertEqual((r.stdout, r.returncode), ("antes\n", 3))

    def test_com_filtro(self):
        wrapped = self.kip.wrap_text(self.ORIG)
        r = self.sh(wrapped, {"1_switch_var": "include", "1_LINE": r"B \(x\)"}, self.script)
        self.assertEqual(r.stdout, "linha B (x)\n")

    def test_filtro_encadeado_e_stderr(self):
        wrapped = self.kip.wrap_text("echo erro-x >&2\necho ok-x\necho ok-y\n")
        r = self.sh(wrapped, {"1_switch_var": "include", "1_LINE": "-x",
                              "2_switch_var": "count"}, self.script)
        self.assertEqual(r.stdout, "Count: 2 lines\n")

    def test_regex_com_metacaracteres_de_shell_nao_executa(self):
        wrapped = self.kip.wrap_text(self.ORIG)
        r = self.sh(wrapped, {"1_switch_var": "include", "1_LINE": "$(echo PWN) `echo PWN`; | &"},
                    self.script)
        self.assertNotIn("PWN", r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")

    def test_idempotente(self):
        w1 = self.kip.wrap_text(self.ORIG)
        el = ET.Element("ACTION")
        el.text = w1
        self.kip.wrap_action(el)
        self.assertEqual(el.text, w1)

    def test_builtin_nao_embrulha(self):
        el = ET.Element("ACTION", builtin="clish_nop")
        el.text = "x"
        self.kip.wrap_action(el)
        self.assertEqual(el.text, "x")


class TestPipeXml(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(os.path.join(CLITREE, "cli-xml", "include", "pipe.xml")).getroot()
        self.params = list(self.root.iter("{http://www.dellemc.com/sonic/XMLSchema}PARAM"))

    def test_regex_usa_ptype_seguro(self):
        lines = [p for p in self.params if p.get("name", "").endswith("_LINE")]
        self.assertTrue(lines)
        for p in lines:
            self.assertEqual(p.get("ptype"), "TERTOOS_PIPE_REGEX", p.get("name"))

    def test_sem_save(self):
        self.assertFalse([p for p in self.params if p.get("name") in ("save", "filename")])

    def test_tres_estagios(self):
        names = {p.get("name") for p in self.params}
        for n in range(1, 4):
            self.assertIn("%d_switch_var" % n, names)
        self.assertNotIn("4_pipe", names)

    def test_ptype_recusa_aspa_simples(self):
        types = ET.parse(os.path.join(CLITREE, "cli-xml", "tertoos", "00-types.xml")).getroot()
        pt = [e for e in types.iter() if e.get("name") == "TERTOOS_PIPE_REGEX"]
        self.assertEqual(len(pt), 1)
        rx = re.compile("^(" + pt[0].get("pattern") + ")$")
        self.assertTrue(rx.match("Ethernet(25|26) .*$"))
        self.assertFalse(rx.match("a'b"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
