import time
import threading
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rede import Rede
from coordenacao import RelogioLamport, EleicaoLider

NOS = {
    1: ("localhost", 5001),
    2: ("localhost", 5002),
    3: ("localhost", 5003),
}

TODOS_IDS = list(NOS.keys())

CICLO = 0.2
HEARTBEAT_INTERVALO = 1.0
HEARTBEAT_FALHAS_MAX = 2

def log(no_id, msg):
    print(f"  [Nó {no_id}] {msg}", flush=True)

class No:
    def __init__(self, meu_id: int):
        self.meu_id = meu_id
        self.rede = Rede(meu_id, NOS[meu_id][1], NOS)
        self.relogio = RelogioLamport()
        self.eleicao = EleicaoLider(meu_id, TODOS_IDS)

        self._ativo = False
        self._thread_loop = None
        self._thread_heartbeat = None
        self._falhas_heartbeat = {}

    def iniciar(self, lider_inicial: int = None):
        self._ativo = True
        self.rede.iniciar_servidor()

        if lider_inicial is not None:
            self.eleicao.ao_receber_lider(lider_inicial)
            log(self.meu_id, f"Líder inicial definido: Nó {lider_inicial}")

        self._thread_loop = threading.Thread(target=self._loop_principal, daemon=True)
        self._thread_loop.start()

        self._thread_heartbeat = threading.Thread(target=self._loop_heartbeat, daemon=True)
        self._thread_heartbeat.start()

    def parar(self):
        log(self.meu_id, "Encerrando...")
        self._ativo = False
        self.rede.parar()

    def _loop_principal(self):
        while self._ativo:
            while True:
                msg = self.rede.receber_proxima()
                if msg is None:
                    break
                self.relogio.ao_receber(msg.get("timestamp_lamport", 0))
                self._processar_mensagem(msg)

            mensagens_lider = self.eleicao.verificar_timeout_ok()

            for m in mensagens_lider:
                self._enviar(m["destino_id"], m)

            if mensagens_lider:
                log(self.meu_id,
                    f"Timeout — me declaro LÍDER. t={self.relogio.obter()}")

            time.sleep(CICLO)

    def _loop_heartbeat(self):
        while self._ativo:
            time.sleep(HEARTBEAT_INTERVALO)

            if self.eleicao.em_eleicao():
                continue

            lider = self.eleicao.obter_lider()

            if lider is None or lider == self.meu_id:
                continue

            ts = self.relogio.antes_de_enviar()

            msg_hb = {
                "tipo": "HEARTBEAT",
                "remetente_id": self.meu_id,
                "timestamp_lamport": ts,
                "conteudo": {}
            }

            sucesso = self.rede.enviar_mensagem(lider, msg_hb)

            if sucesso:
                self._falhas_heartbeat[lider] = 0
            else:
                falhas = self._falhas_heartbeat.get(lider, 0) + 1
                self._falhas_heartbeat[lider] = falhas

                log(self.meu_id,
                    f"Heartbeat falhou para Nó {lider} ({falhas}).")

                if falhas >= HEARTBEAT_FALHAS_MAX:
                    log(self.meu_id,
                        f"Líder {lider} caiu → iniciando eleição.")
                    self.eleicao.resetar_lider()
                    self._iniciar_eleicao()

    def _processar_mensagem(self, msg: dict):
        tipo = msg.get("tipo")
        remetente = msg.get("remetente_id")

        if tipo == "HEARTBEAT":
            ts = self.relogio.antes_de_enviar()
            self.rede.enviar_mensagem(remetente, {
                "tipo": "HEARTBEAT_ACK",
                "remetente_id": self.meu_id,
                "timestamp_lamport": ts,
                "conteudo": {}
            })

        elif tipo == "HEARTBEAT_ACK":
            self._falhas_heartbeat[remetente] = 0

        elif tipo == "ELEICAO":
            log(self.meu_id, f"Recebi ELEICAO de Nó {remetente}")

            resultado = self.eleicao.ao_receber_eleicao(remetente)

            ok = resultado["ok"]
            ts = self.relogio.antes_de_enviar()
            ok["timestamp_lamport"] = ts
            self.rede.enviar_mensagem(ok["destino_id"], ok)

            for m in resultado["eleicao"]:
                ts = self.relogio.antes_de_enviar()
                m["timestamp_lamport"] = ts
                self.rede.enviar_mensagem(m["destino_id"], m)

            if not resultado["eleicao"]:
                log(self.meu_id,
                    "Sou o maior nó — aguardando timeout para virar líder")

        elif tipo == "OK":
            log(self.meu_id, f"Recebi OK de Nó {remetente}")
            self.eleicao.ao_receber_ok(remetente)

        elif tipo == "LIDER":
            novo = msg["conteudo"]["lider_id"]
            self.eleicao.ao_receber_lider(novo)
            log(self.meu_id, f"Novo líder: Nó {novo}")

    def _iniciar_eleicao(self):
        mensagens = self.eleicao.iniciar_eleicao()

        if not mensagens:
            log(self.meu_id,
                "Sou o maior — aguardando timeout para ser líder")

        for m in mensagens:
            ts = self.relogio.antes_de_enviar()
            m["timestamp_lamport"] = ts
            self.rede.enviar_mensagem(m["destino_id"], m)

    def _enviar(self, destino_id, msg):
        if "timestamp_lamport" not in msg:
            msg["timestamp_lamport"] = self.relogio.antes_de_enviar()
        self.rede.enviar_mensagem(destino_id, msg)

    def status(self):
        lider = self.eleicao.obter_lider()
        return f"Nó {self.meu_id} | líder={lider}"


def aguardar_lider(nos_ids: list, nos: dict, lider_esperado: int,
                   timeout: float = 12.0, intervalo: float = 0.3) -> bool:
    inicio = time.time()
    while time.time() - inicio < timeout:
        todos_ok = all(
            nos[nid].eleicao.obter_lider() == lider_esperado
            for nid in nos_ids
        )
        if todos_ok:
            return True
        time.sleep(intervalo)
    return False


def main():
    print("\n=== TESTE BULLY ===\n")

    nos = {nid: No(nid) for nid in TODOS_IDS}

    for nid, no in nos.items():
        no.iniciar(lider_inicial=3)

    time.sleep(2)

    print("\n--- Derrubando Nó 3 ---\n")
    nos[3].parar()

    print("Aguardando eleição...")
    sucesso = aguardar_lider([1, 2], nos, lider_esperado=2, timeout=12.0)

    print("\nSTATUS:")
    for nid in [1, 2]:
        print(nos[nid].status())

    if not sucesso:
        print("\n✘ Timeout: Nó 2 não virou líder a tempo")
        nos[1].parar()
        nos[2].parar()
        return

    assert nos[2].eleicao.obter_lider() == 2, \
        f"Esperado líder=2, obtido={nos[2].eleicao.obter_lider()}"
    assert nos[1].eleicao.obter_lider() == 2, \
        f"Nó 1 deveria reconhecer líder=2, obtido={nos[1].eleicao.obter_lider()}"
    print("\n Nó 2 virou líder (reconhecido por todos)")

    print("\n--- Derrubando Nó 2 ---\n")
    nos[2].parar()

    print("Aguardando eleição...")
    sucesso = aguardar_lider([1], nos, lider_esperado=1, timeout=12.0)

    print("\nSTATUS:")
    print(nos[1].status())

    if not sucesso:
        print("\n✘ Timeout: Nó 1 não virou líder a tempo")
        nos[1].parar()
        return

    assert nos[1].eleicao.obter_lider() == 1, \
        f"Esperado líder=1, obtido={nos[1].eleicao.obter_lider()}"
    print("\n Nó 1 virou líder")

    nos[1].parar()

    print("\n TESTE FINALIZADO COM SUCESSO \n")

if __name__ == "__main__":
    main()