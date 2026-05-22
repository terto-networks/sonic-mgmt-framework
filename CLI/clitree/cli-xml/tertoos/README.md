# TertoOS — KLISH overlay (IOS-XR style)

Esta árvore é o **fork TertoOS** sobre `sonic-mgmt-framework`. Os XMLs aqui
implementam a CLI 100% IOS-XR para o NOS. Não tocamos nos XMLs originais
do upstream em [`../`](../) para manter rebases simples; em vez disso esta
pasta substitui completamente as views de exec/privileged/config quando
o build flag `TERTOOS_CLI=y` está ativo.

## Estrutura

| Arquivo | Conteúdo | Sprint |
|---|---|---|
| `00-types.xml`           | PTYPEs (regex) IOS-XR (NET, Bundle-Ether, asn etc.) | S1 |
| `01-exec-view.xml`       | View `exec-view` (`tertoos>`), enable, ping, show básico | S1 |
| `02-privileged-view.xml` | `privileged-view` (`tertoos#`), show *, clear *, configure | S1 |
| `03-config-view.xml`     | Candidate `config-view` + commit/abort/rollback/show config | S1 |
| `04-config-interface.xml`| `config-if-view` (interface, Bundle-Ether, subif) | S2 |
| `05-config-vrf.xml`      | `config-vrf-view` + RD/RT | S2 |
| `06-config-bgp.xml`      | `config-bgp-view` + AF + neighbor groups | S4 |
| `07-config-isis.xml`     | `config-isis-view` (incl. SR) | S5 |
| `08-config-ospf.xml`     | `config-ospf-view` / `config-ospfv3-view` | S6 |
| `09-config-ldp.xml`      | `config-ldp-view` (MPLS LDP) | S7 |
| `10-config-sr.xml`       | `config-sr-view` (SRGB, SR-TE) | S8–S9 |
| `11-config-l2vpn.xml`    | `config-l2vpn-view` (xconnect/VPWS/VFI) | S11 |
| `12-config-evpn.xml`     | `config-evpn-view` (evi, ESI) | S10 |
| `13-config-rpl.xml`      | `config-rpl-view` + prefix-set/community-set/as-path-set | S3 |
| `14-config-acl.xml`      | `config-ipv4-acl`, `config-ipv6-acl`, `config-l2-acl` | S3 |
| `15-config-qos.xml`      | class-map / policy-map | S12 |
| `99-horizon.xml`         | `horizon broker / enrollment-token / enable` | S13 |

## Princípios da overlay

1. **Two-stage commit obrigatório**. Toda mutação em `config-view` (e suas
   subviews) escreve em **candidate datastore** local — nunca direto em
   `CONFIG_DB`. O `commit` chama o **GCU (Generic Config Updater)** para
   aplicar atomicamente.
2. **Hierarquia em árvore**, não comandos planos. `show configuration`
   renderiza a árvore inteira, não a sequência de comandos digitados.
3. **RPL é a única forma de policy**. Não expor `route-map`. Internamente
   um tradutor compila RPL → estrutura FRR.
4. **Bundle-Ether substitui PortChannel** na superfície externa. YANG
   internamente reusa `sonic-portchannel`, mas o nome operacional é
   `Bundle-EtherN` (parser deve aceitar `Bundle-Ether 1` ou `BE1`).
5. **PTYPEs centralizados** em `00-types.xml` — qualquer regex de validação
   (asn, ipv4, ipv6, NET, label, vlan, prefix-set name, RD, RT, ESI) vive
   ali, nunca duplicado.

## Build

O `Makefile` ([`../../Makefile`](../../Makefile)) precisa ser instruído a
incluir esta pasta quando `TERTOOS_CLI=y`. Item de trabalho do S1 (ainda
não aplicado neste commit — só os XMLs).

## Referências externas

- IOS-XR Configuration Guides (Cisco) — referência de hierarquia e nomes.
- ietf-routing / openconfig-* — fonte de inspiração para YANG quando
  `sonic-*.yang` não cobrir.
