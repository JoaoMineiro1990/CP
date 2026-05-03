import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from coordenacao import RelogioLamport

def separador(titulo=""):
    linha = "─" * 55
    if titulo:
        print(f"\n{'─'*10} {titulo} {'─'*(44 - len(titulo))}")
    else:
        print(linha)

def estado(nos):
    """Imprime o estado atual do relógio de cada nó."""
    valores = "  |  ".join(f"Nó {nid}: t={r.obter()}" for nid, r in nos.items())
    print(f"   [{valores}]")

def evento(descricao, nos):
    print(f"\n>> {descricao}")
    estado(nos)


# ─────────────────────────────────────────────
#  Simulação
# ─────────────────────────────────────────────

def simular_envio(remetente_id, destinatario_id, relogios, descricao=""):
 
    ts = relogios[remetente_id].antes_de_enviar()
    msg = {
        "tipo": "TESTE",
        "remetente_id": remetente_id,
        "timestamp_lamport": ts,
        "conteudo": {"texto": descricao}
    }

    relogios[destinatario_id].ao_receber(msg["timestamp_lamport"])

    print(f"\n   Nó {remetente_id} → Nó {destinatario_id}  "
          f"[msg ts={ts}]  |  "
          f"Nó {remetente_id}: t={relogios[remetente_id].obter()}  "
          f"Nó {destinatario_id}: t={relogios[destinatario_id].obter()}")
    return ts

def verificar_nao_regressao(historico):
    """Verifica que nenhum relógio regrediu ao longo do tempo."""
    for nid, valores in historico.items():
        for i in range(1, len(valores)):
            assert valores[i] >= valores[i - 1], (
                f"FALHA: relógio do Nó {nid} regrediu de {valores[i-1]} para {valores[i]}"
            )
    print("\n   Nenhum relógio regrediu em nenhum momento.")

def main():
    separador("Inicialização")
    relogios = {1: RelogioLamport(), 2: RelogioLamport(), 3: RelogioLamport()}
    print("   Três nós criados. Relógios zerados.")
    estado(relogios)

    historico = {nid: [r.obter()] for nid, r in relogios.items()}

    def registrar():
        for nid, r in relogios.items():
            historico[nid].append(r.obter())

    # ── Bloco 1: Eventos locais ──────────────────────────────
    separador("Bloco 1 — Eventos locais (sem comunicação)")

    relogios[1].evento_interno()
    print(f"\n   Nó 1 evento interno  →  t={relogios[1].obter()}")
    registrar()

    relogios[2].evento_interno()
    relogios[2].evento_interno()
    print(f"   Nó 2 dois eventos internos  →  t={relogios[2].obter()}")
    registrar()

    relogios[3].evento_interno()
    print(f"   Nó 3 evento interno  →  t={relogios[3].obter()}")
    registrar()

    estado(relogios)

    # ── Bloco 2: Envios simples ──────────────────────────────
    separador("Bloco 2 — Envios diretos entre nós")

    simular_envio(1, 2, relogios, "Nó 1 inicia conversa com Nó 2")
    registrar()

    simular_envio(2, 3, relogios, "Nó 2 repassa para Nó 3")
    registrar()

    simular_envio(3, 1, relogios, "Nó 3 responde ao Nó 1")
    registrar()

    # ── Bloco 3: Mensagem atrasada (chegada fora de ordem) ───
    separador("Bloco 3 — Mensagem com timestamp alto chegando a nó atrasado")

    # Nó 2 avança muito o seu relógio com eventos internos
    for _ in range(10):
        relogios[2].evento_interno()
    print(f"\n   Nó 2 avançou com 10 eventos internos  →  t={relogios[2].obter()}")
    registrar()

    # Nó 2 envia para Nó 1 (que está muito atrás)
    print(f"\n   Nó 1 antes de receber:  t={relogios[1].obter()}")
    simular_envio(2, 1, relogios, "Mensagem de Nó 2 (timestamp alto) para Nó 1")
    registrar()
    print(f"   Nó 1 após receber mensagem atrasada:  t={relogios[1].obter()}")
    print("   Nó 1 ajustou para max(local, recebido) + 1 — não regrediu.")

    # ── Bloco 4: Cadeia de 3 nós em sequência ───────────────
    separador("Bloco 4 — Cadeia: 1 → 2 → 3 → 1 (rodada completa)")

    simular_envio(1, 2, relogios, "Rodada 2 — 1→2")
    registrar()
    simular_envio(2, 3, relogios, "Rodada 2 — 2→3")
    registrar()
    simular_envio(3, 1, relogios, "Rodada 2 — 3→1")
    registrar()

    simular_envio(1, 2, relogios, "Rodada 3 — 1→2")
    registrar()
    simular_envio(2, 3, relogios, "Rodada 3 — 2→3")
    registrar()
    simular_envio(3, 1, relogios, "Rodada 3 — 3→1")
    registrar()

    # ── Bloco 5: Envios simultâneos (sem coordenação) ────────
    separador("Bloco 5 — Envios cruzados (1→3 e 2→3 sem coordenação)")

    ts1 = relogios[1].antes_de_enviar()
    ts2 = relogios[2].antes_de_enviar()
    print(f"\n   Nó 1 prepara mensagem  ts={ts1}   Nó 2 prepara mensagem  ts={ts2}")

    relogios[3].ao_receber(ts1)
    print(f"   Nó 3 recebe de Nó 1 (ts={ts1})  →  t={relogios[3].obter()}")
    registrar()

    relogios[3].ao_receber(ts2)
    print(f"   Nó 3 recebe de Nó 2 (ts={ts2})  →  t={relogios[3].obter()}")
    registrar()

    # ── Verificação final ────────────────────────────────────
    separador("Verificação final")
    print("\n   Histórico de timestamps por nó:")
    for nid, vals in historico.items():
        print(f"   Nó {nid}: {vals}")

    verificar_nao_regressao(historico)

    separador()
    print("\n   Estado final dos relógios:")
    estado(relogios)
    separador()
    print("\n   Teste concluído com sucesso.\n")


if __name__ == "__main__":
    main()