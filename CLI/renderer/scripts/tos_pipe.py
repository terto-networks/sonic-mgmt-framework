#!/usr/bin/env python3
"""Filtro de saida dos `show` do klish TertoOS: `show ... | include X | exclude Y | count`.

Chamado pela ACTION embrulhada (CLI/clitree/scripts/klish_insert_pipe.py) com 3 trincas
de argumentos, uma por estagio do include/pipe.xml:

    tos_pipe.py <op1> <regex1> <icase1> <op2> <regex2> <icase2> <op3> <regex3> <icase3>

op    = include|exclude|begin|count|no-more (ou os apelidos grep|except|find); vazio = sem estagio
regex = expressao regular (Python `re`, busca em qualquer parte da linha)
icase = "ignore-case" para nao diferenciar maiusculas/minusculas; vazio = diferencia

Le stdin linha a linha e escreve na hora (saida longa nao espera o fim), exceto `count`.
"""
import re
import sys

ALIASES = {"grep": "include", "except": "exclude", "find": "begin"}
WITH_REGEX = ("include", "exclude", "begin")


class PipeError(Exception):
    """Erro de uso (regex invalido, operacao desconhecida) - vira mensagem `% ...`."""


def parse_stages(argv):
    """Converte as trincas de argumentos em [(op, regex compilado ou None)]."""
    stages = []
    for i in range(0, len(argv) - len(argv) % 3, 3):
        op, pattern, icase = argv[i], argv[i + 1], argv[i + 2]
        if not op:
            continue
        op = ALIASES.get(op, op)
        if op == "no-more":
            continue
        if op == "count":
            stages.append(("count", None))
            continue
        if op not in WITH_REGEX:
            raise PipeError("unknown filter '%s'" % op)
        if not pattern:
            raise PipeError("filter '%s' needs a regular expression" % op)
        try:
            rx = re.compile(pattern, re.IGNORECASE if icase == "ignore-case" else 0)
        except re.error as e:
            raise PipeError("invalid regular expression '%s': %s" % (pattern, e))
        stages.append((op, rx))
    return stages


def apply(stages, lines):
    """Gerador: aplica os estagios em ordem sobre um iteravel de linhas (com ou sem '\\n')."""
    for op, rx in stages:
        lines = _stage(op, rx, lines)
    return lines


def _stage(op, rx, lines):
    if op == "include":
        return (l for l in lines if rx.search(l))
    if op == "exclude":
        return (l for l in lines if not rx.search(l))
    if op == "begin":
        return _begin(rx, lines)
    if op == "count":
        return _count(lines)
    raise PipeError("unknown filter '%s'" % op)


def _begin(rx, lines):
    started = False
    for l in lines:
        if started or rx.search(l):
            started = True
            yield l


def _count(lines):
    n = sum(1 for _ in lines)
    yield "Count: %d line%s\n" % (n, "" if n == 1 else "s")


def main(argv):
    try:
        stages = parse_stages(argv)
    except PipeError as e:
        # drena a entrada para o comando de origem nao morrer com SIGPIPE no meio
        for _ in sys.stdin:
            pass
        sys.stdout.write("% " + str(e) + "\n")
        return 1
    try:
        for line in apply(stages, sys.stdin):
            sys.stdout.write(line)
            sys.stdout.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    return 0


if __name__ == "__main__":
    sys.stdin.reconfigure(errors="replace")
    sys.exit(main(sys.argv[1:]))
