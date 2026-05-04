from rede import Rede
from aco import ACO
from coordenacao import RelogioLamport, EleicaoLider
from data.instancia import DISTANCIAS
import sys, time, threading

MEU_ID = int(sys.argv[1])
NOS = {1: ('localhost', 5001), 2: ('localhost', 5002), 3: ('localhost', 5003)}

rede    = Rede(MEU_ID, NOS[MEU_ID][1], NOS)
aco     = ACO(DISTANCIAS)
relogio = RelogioLamport()
eleicao = EleicaoLider(MEU_ID, list(NOS.keys()))

feromonios_recebidos = {}
falhas_lider = 0


def enviar(destino_id, tipo, conteudo={}):
    msg = {
        "tipo": tipo,
        "remetente_id": MEU_ID,
        "timestamp_lamport": relogio.antes_de_enviar(),
        "conteudo": conteudo,
    }
    return rede.enviar_mensagem(destino_id, msg)


def broadcast(tipo, conteudo={}):
    msg = {
        "tipo": tipo,
        "remetente_id": MEU_ID,
        "timestamp_lamport": relogio.antes_de_enviar(),
        "conteudo": conteudo,
    }
    rede.broadcast(msg)


def iniciar_eleicao():
    global falhas_lider
    falhas_lider = 0

    eleicao.resetar_lider()

    mensagens = eleicao.iniciar_eleicao()

    if not mensagens:
        eleicao.ao_receber_lider(MEU_ID)
        broadcast("LIDER", {"lider_id": MEU_ID})
        print(f"[ELEI] Nó {MEU_ID} venceu a eleição (sem nós maiores).")
        return

    for m in mensagens:
        enviar(m["destino_id"], "ELEICAO", m["conteudo"])


def processar_mensagem(msg):
    global falhas_lider
    tipo = msg["tipo"]
    rem  = msg["remetente_id"]

    if tipo == "ELEICAO":
        resultado = eleicao.ao_receber_eleicao(rem)
        ok = resultado["ok"]
        enviar(ok["destino_id"], "OK", ok["conteudo"])
        for m in resultado["eleicao"]:
            enviar(m["destino_id"], "ELEICAO", m["conteudo"])

    elif tipo == "OK":
        eleicao.ao_receber_ok(rem)

    elif tipo == "LIDER":
        eleicao.ao_receber_lider(msg["conteudo"]["lider_id"])
        falhas_lider = 0
        print(f"[ELEI] Novo líder: Nó {eleicao.obter_lider()}")

    elif tipo == "SOLICITACAO":
        lider = eleicao.obter_lider()
        if lider and lider != MEU_ID:
            enviar(lider, "FEROMONIO", {"matriz": aco.obter_feromonio()})

    elif tipo == "FEROMONIO":
        matriz = msg["conteudo"].get("matriz")
        if eleicao.eu_sou_lider():
            feromonios_recebidos[rem] = matriz
        else:
            aco.aplicar_feromonio_externo(matriz)

    elif tipo == "HEARTBEAT":
        enviar(rem, "HEARTBEAT_ACK")

    elif tipo == "HEARTBEAT_ACK":
        falhas_lider = 0


def verificar_eleicao():
    mensagens = eleicao.verificar_timeout_ok()
    for m in mensagens:
        enviar(m["destino_id"], "LIDER", m["conteudo"])
        print(f"[ELEI] Nó {MEU_ID} venceu a eleição.")


def sincronizar():
    feromonios_recebidos.clear()
    broadcast("SOLICITACAO")

    workers = [n for n in NOS if n != MEU_ID]
    prazo = time.time() + 3
    while time.time() < prazo:
        if all(w in feromonios_recebidos for w in workers):
            break
        time.sleep(0.1)

    matrizes = list(feromonios_recebidos.values()) + [aco.obter_feromonio()]
    n = len(matrizes)
    tamanho = len(matrizes[0])
    media = [[sum(m[i][j] for m in matrizes) / n for j in range(tamanho)] for i in range(tamanho)]

    aco.aplicar_feromonio_externo(media)
    broadcast("FEROMONIO", {"matriz": media})
    print("[SYNC] Feromônio sincronizado.")


def loop_heartbeat():
    global falhas_lider
    while True:
        time.sleep(5)
        lider = eleicao.obter_lider()
        if lider and lider != MEU_ID:
            ok = enviar(lider, "HEARTBEAT")
            if not ok:
                falhas_lider += 1
                print(f"[HB] Líder {lider} falhou ({falhas_lider}/3)")
                if falhas_lider >= 3:
                    iniciar_eleicao()
            else:
                falhas_lider = 0


def _eleicao_inicial():
    time.sleep(3)
    if eleicao.obter_lider() is None:
        print(f"[INIT] Nó {MEU_ID} sem líder, iniciando eleição...")
        iniciar_eleicao()


# Inicialização
rede.iniciar_servidor()
if MEU_ID == max(NOS.keys()):
    eleicao.ao_receber_lider(MEU_ID)
    print(f"[INIT] Nó {MEU_ID} inicia como líder.")
    time.sleep(1)
    broadcast("LIDER", {"lider_id": MEU_ID})

threading.Thread(target=_eleicao_inicial, daemon=True).start()
threading.Thread(target=loop_heartbeat, daemon=True).start()

iteracao = 0
while True:
    msg = rede.receber_proxima()
    if msg:
        relogio.ao_receber(msg["timestamp_lamport"])
        processar_mensagem(msg)

    verificar_eleicao()

    aco.executar_iteracao(num_formigas=5)
    iteracao += 1

    if iteracao % 10 == 0:
        _, dist = aco.obter_melhor_global()
        print(f"[ACO] iter {iteracao} | dist {dist:.2f} | líder: {eleicao.obter_lider()}")

    if iteracao % 10 == 0 and eleicao.eu_sou_lider():
        sincronizar()

    time.sleep(0.01)