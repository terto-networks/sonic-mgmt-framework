#!/bin/bash
# test_mask_password.sh — testa o mask_password() REAL do klish (mgmt_clish_utils.c).
#
# Extrai a funcao (e as tabelas que ela usa) do arquivo de patch e compila com
# stubs minimos de lub_string_*/bool_t: o que e' testado e' o codigo que vai para
# a imagem, nao uma copia. Uso: CLI/klish/tests/test_mask_password.sh (precisa de gcc).
#
# Contexto (18/11/2026): o hook de log do klish gravava a linha CRUA no syslog
# (senha do username, community SNMP, chaves NTP/OSPF, token do Horizon) e a
# mascara so' cobria password/key. Ver hook_log.c.diff.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/../patches/klish-2.1.4/clish/plugin/mgmt_clish_utils.c"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

# Da tabela obscure_string ate' o fim do mask_password() (1a linha "}" depois dele).
tr -d '\r' < "$SRC" | awk '
  /^static char \*obscure_string/ { on = 1 }
  on { print }
  on && /^void mask_password/ { infn = 1 }
  infn && /^}/ { exit }
' > "$T/mask.inc"
grep -q '^void mask_password' "$T/mask.inc" || { echo "FAIL: mask_password nao encontrado em $SRC"; exit 1; }

cat > "$T/t.c" <<'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int bool_t;
#define BOOL_TRUE 1
#define BOOL_FALSE 0
static void lub_string_catn(char **s, const char *t, size_t n) {
    size_t a = *s ? strlen(*s) : 0;
    *s = realloc(*s, a + n + 1); memcpy(*s + a, t, n); (*s)[a + n] = 0;
}
static void lub_string_cat(char **s, const char *t) { if (t) lub_string_catn(s, t, strlen(t)); }
static void lub_string_free(char *s) { free(s); }
#include "mask.inc"
static int fails = 0;
static void check(const char *in, const char *want) {
    char *out = NULL;
    mask_password(in, &out);
    if (!out || strcmp(out, want) != 0) {
        printf("FAIL: %s\n   veio: %s\n   quer: %s\n", in, out ? out : "(null)", want);
        fails++;
    } else {
        printf("ok:   %s\n", out);
    }
    free(out);
}
int main(void) {
    /* ja' cobertos (password/key) — continuam */
    check("username noc group admin password S3cr3t", "username noc group admin password *****");
    check("tacacs-server host 10.0.0.1 key S3cr3t", "tacacs-server host 10.0.0.1 key *****");
    check("neighbor 10.0.0.2 password 0 S3cr3t", "neighbor 10.0.0.2 password 0 *****");
    check("snmp-server user nms auth-sha auth-password A1 priv-aes priv-password P1",
          "snmp-server user nms auth-sha auth-password ***** priv-aes priv-password *****");
    check("copy scp://user:pw@host/f /tmp/f", "copy scp://user:*****@host/f /tmp/f");
    check("copy https://h.example:8443/f.tos /tmp/f", "copy https://h.example:8443/f.tos /tmp/f"); /* porta, nao senha */
    /* novos (regras por frase) */
    check("snmp-server community C0mm ro source 192.0.2.30/32", "snmp-server community ***** ro source 192.0.2.30/32");
    check("no snmp-server community C0mm", "no snmp-server community *****");
    check("ntp authentication-key 77 md5 K3y", "ntp authentication-key 77 md5 *****");
    check("no ntp authentication-key 77", "no ntp authentication-key 77"); /* so' o id: nao e' segredo */
    check("ip ospf authentication-key K3y", "ip ospf authentication-key *****");
    check("ip ospf message-digest-key 1 md5 K3y", "ip ospf message-digest-key 1 md5 *****");
    check("horizon enrollment-token T0k3n", "horizon enrollment-token *****");
    check("horizon-edge adopt core https://h.example token hze_T0k", "horizon-edge adopt core https://h.example token *****");
    check("horizon-edge join peer https://a:8443 code C0de fingerprint AB:CD",
          "horizon-edge join peer https://a:8443 code ***** fingerprint AB:CD");
    /* NAO sao segredo: ficam visiveis (auditoria do BGP / comandos comuns) */
    check("set community 65000:100", "set community 65000:100");
    check("match community LISTA-X", "match community LISTA-X");
    check("community-set CS1", "community-set CS1");
    check("show running-config", "show running-config");
    check("interface Ethernet 25.1001", "interface Ethernet 25.1001");
    printf("%s (%d falha(s))\n", fails ? "FAIL" : "PASS", fails);
    return fails ? 1 : 0;
}
EOF
gcc -Wall -Wno-unused-variable -o "$T/t" "$T/t.c" -I"$T"
"$T/t"
