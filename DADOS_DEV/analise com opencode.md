# Requisitos para Criar um OpenCode "Browser-Based"

Este documento descreve os requisitos técnicos e arquiteturais para criar uma versão do OpenCode que rode totalmente no navegador (web-based), sem depender de cliente terminal/desktop.

---

## 1. Visão Geral da Arquitetura Atual do OpenCode

O OpenCode original possui uma arquitetura **cliente-servidor local**:

- **Servidor** (`packages/server`): Um servidor HTTP baseado em **Hono** que roda localmente na máquina do usuário (porta 4096 por padrão)
- **Cliente** (`packages/cli`, `packages/desktop`): Interface terminal (TUI) ou desktop que se comunica via HTTP com o servidor local
- **Core** (`packages/core`): Motor/runtime que gerencia agentes, ferramentas, providers, contexto, compaction, etc.
- **Frontend Web** (`packages/web`): Interface moderna em Astro/Starlight (servida pelo mesmo servidor)

Fluxo: Cliente → HTTP → Servidor (Hono) → Core → Modelos/Providers

---

## 2. Objetivo da Versão Browser-Based

Criar uma versão onde:

- Todo o código roda no navegador do usuário (client-side)
- Não há necessidade de instalar nada localmente (apenas acessar uma URL)
- Todos os dados (API keys, contexto, arquivos) permanecem no navegador/do usuário
- Comunicação opcional com APIs externas (LLM providers) via backend opcional ou diretamente do navegador (com CORS/keys)

---

## 3. Requisitos Técnicos

### 3.1 Frontend (Browser)

| Requisito | Descrição |
|-----------|-----------|
| **Framework** | Astro (já usado no `packages/web`) ou React/Vue/Svelte |
| **Runtime** | Navegador moderno com suporte a ES2024 + Web Workers |
| **Gerenciamento de Estado** | Zustand, Jotai ou Redux Toolkit |
| **Roteamento** | Astro's file-based routing ou React Router |
| **Build** | Vite ou esbuild para bundles otimizados |
| **Interface** | Baseada nos componentes do `packages/ui` e `packages/tui` |
| **Worker Principal** | Rodar o "agente loop" em um Web Worker para não bloquear a UI |

### 3.2 Agente no Navegador

| Requisito | Descrição |
|-----------|-----------|
| **Execução Local** | O loop do agente (plan/build) deve rodar no browser via JavaScript puro ou WebAssembly |
| **Web Worker** | Agente principal em worker separado; UI permanece responsiva |
| **Persistência** | IndexedDB ou LocalStorage para salvar histórico, configurações, sessões |
| **Compaction** | Algoritmo de compaction adaptado para memória do navegador |
| **Snapshot** | Versão adaptada do sistema de snapshots (ou usar git local do navegador) |

### 3.3 Comunicação com Provedores de IA (API Keys)

| Requisito | Descrição |
|-----------|-----------|
| **Armazenamento de Keys** | Web Crypto API + IndexedDB; chaves nunca saem do navegador |
| **Provider Options** | Suporte a `{env:}`, `{file:}` substituído por input direto no UI + storage local |
| **Proxy/Backend Opcional** | Endpoint próprio para chamadas de API (evita expor keys em código client-side) |
| **CORS** | Configuração para permitir chamadas diretas a APIs (ex: OpenAI, Anthropic, OpenRouter) |
| **Alternativa:** Backend Local | Opcionalmente, o usuário pode rodar um servidor `opencode serve` local e o browser se conecta nele |

### 3.4 Servidor (Opcional - para backend)

| Requisito | Descrição |
|-----------|-----------|
| **Hono Framework** | Opcional: manter o servidor Hono local como proxy/bridge |
| **Autenticação** | Chaves armazenadas no backend do usuário (se optar por não enviar keys para o browser) |
| **API Routes** | Rotas para: `/auth`, `/models`, `/execute`, `/files`, `/config` |
| **Docker/Deploy** | Opcional: deploy no Vercel/Netlify para versões hospedadas |

### 3.5 Funcionalidades Principais

| Funcionalidade | Status Atual | Necessário para Browser |
|----------------|--------------|-------------------------|
| **TUI/Interface** | Terminal (packages/tui) | Reescrever em component(es) web |
| **Agents (build/plan/general)** | Em execução no processo terminal | Runner no Web Worker |
| **Tools (write, bash, edit, etc.)** | Acesso ao filesystem local | API de escrita de arquivos do browser + sandbox |
| **MCP Servers** | Configurados global/localmente | Conexão via websocket/HTTP para servidores remotos |
| **Providers Management** | Via `opencode auth login` / config.json | Input de API keys no UI + storage local |
| **Snapshot/Undo** | Sistema git-based | Versão IndexedDB ou localForage |
| **Custom Commands/Plugins** | Markdown files em `.opencode/` | Sistema de extensões do browser |

### 3.6 Segurança

| Aspecto | Consideração |
|---------|--------------|
| **Vazamento de Keys** | Nunca armazenar chaves em código público; usar env do usuário |
| **Sandbox de Execução** | Executar código do agente em contexto isolado (iframe + sandbox) |
| **Permissions** | API do browser para pedir aprovação de ações (arquivos, rede) |
| **Data Privacy** | Todo contexto fica no navegador do usuário; opcional upload/backup |

---

## 4. Pilha de Tecnologias Sugerida

```text
Frontend:
- Astro 4.x (ou Next.js 14 App Router)
- React (ou Preact/Inferno para menor bundle)
- TailwindCSS + shadcn-ui (estilização consistente)
- Zod (validação de formulário/schema)
- React Syntax Highlighter / highlight.js (para código)

Agente/Worker:
- JavaScript nativo (ou TypeScript compilado)
- Web Workers API
- BroadcastChannel (comunicação worker↔UI)

Persistência:
- IndexedDB (via idb-keyval ou Dexie.js)
- LocalStorage (para configs simples)
- SessionStorage (para sessões temporárias)

Build/Dev:
- Vite 5+ (dev server com HMR)
- esbuild (para bundles)
- TypeScript configurado para browser

Opcional (Backend Proxy):
- Hono (mantendo compatibilidade com o OpenCode original)
- DrizzleORM (se precisar de banco local)
```

---

## 5. Roteiro (Roadmap) Sugerido

1. **Fase 1 - MVP**: Interface básica de chat + agente simples rodando em Web Worker
2. **Fase 2 - Persistência**: IndexedDB para histórico e configurações
3. **Fase 3 - API Keys**: Input de chaves + storage criptografado no browser
4. **Fase 4 - Tools**: Implementação das principais ferramentas (read, edit, bash light)
5. **Fase 5 - Plugins/MCP**: Sistema de extensões browser-compatível
6. **Fase 6 - Deploy**: Opção de hospedagem própria ou usar Vercel/Netlify

---

## 6. Exemplos de Componentes Necessários

### 6.1 Agent Runner (simplificado)

```javascript
// worker-agent.js
self.onmessage = async (e) => {
  const { type, payload } = e.data;
  
  if (type === 'execute') {
    // Rodar o loop do agente build/plan
    const result = await runAgent(payload);
    self.postMessage({ type: 'result', data: result });
  }
};
```

### 6.2 UI Principal

```jsx
// App Browser
function OpenCodeBrowser() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  
  const send = async (text) => {
    setMessages([...messages, { role: 'user', content: text }]);
    setInput('');
    
    const resp = await fetch('/api/execute', {
      method: 'POST',
      body: JSON.stringify({ text }),
    });
    const { output } = await resp.json();
    
    setMessages([...messages, { role: 'assistant', content: output }]);
  };
  
  return (
    <div className="min-h-screen p-4 bg-background">
      <div className="h-96 overflow-y-auto space-y-4">
        {messages.map((m, i) => (
          <Message key={i} {...m} />
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim()) send(input);
          setInput('');
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="What do you want to build?"
          className="input-bordered flex-1"
        />
        <button type="submit" className="btn-primary">
          Send
        </button>
      </form>
    </div>
  );
}
```

---

## 7. Considerações Finais

### Vantagens da Versão Browser-Based:
- Zero instalação necessária para o usuário final
- Acessível de qualquer dispositivo (desktop/mobile)
- Atualizações instantâneas (deploy do frontend)
- Melhor para demonstrações e uso rápido

### Desafios:
- Segurança de chaves de API (resolvido com backend proxy ou chave única por usuário)
- Limitações de performance do browser vs máquina local
- Acesso restrito ao filesystem (necessita de Permissions API ou File System Access)
- Compatibilidade com todas as tools do OpenCode (bash, git, etc.)

### Quando fazer sentido:
- Projetos de demonstração / tutoriais
- Usuários que não querem instalar software
- Acesso rápido de dispositivos móveis
- Ambientes onde não é possível instalar (ex: computadores restritos)

---

**Para começar:** Dê uma olhada em `packages/web/` (já é um projeto Astro) e `packages/core/` (o cérebro do OpenCode) como ponto de partida. O maior trabalho é reescrever o loop do agente e as tools para rodarem no browser.

---
*Documento gerado baseado na análise do repositório anomalyco/opencode (dev branch, ~21k commits).*

---

# ANÁLISE SINCERA: O QUE O OPENCODE PODE AJUDAR O PROJETO DRIX

## Contexto do Projeto Drix

O **Drix** é um sistema de IA portátil em HD externo (F:\) que roda:
- **Offline**: Ollama local com modelos no HD (~18GB de modelos)
- **Python portável**: WinPython incluso (sem depender de instalação no PC hospedeiro)
- **Auto-detecção de hardware**: RAM/GPU → sugere modelo ideal
- **Zero instalação**: Plug-and-play em qualquer PC

Estrutura atual:
```
F:\
├── ia_system/          # Ollama + modelos + Python portável
├── scripts/            # start.py, service.py, terminal_client.py
├── config/             # config.yaml centralizado
├── api/                # API do sistema
├── core/               # Núcleo Python
├── ui/                 # Interface
└── .venv/              # Ambiente virtual
```

---

## O Que Vale a Pena Copiar/Adaptar do OpenCode (Top 5)

### 1. **Sistema de Agentes com Loop de Aprovação** (`packages/core/src/agent/`)
```
OpenCode tem:
- Agent build (pode editar, executar)
- Agent plan (só lê, planeja)
- Agent general (busca complexa)
- Subagents com profundidade controlada

Drix pode adaptar:
- Criar AgentBuild / AgentPlan em Python
- Loop: LLM → ToolCall → Aprovação → Execução → Repete
- Permission system: ask/allow/deny por ferramenta
```

### 2. **Configuração por Projeto + Variáveis** (`opencode.json` + `{env:}`, `{file:}`)
```
OpenCode:
{
  "model": "{env:OPENCODE_MODEL}",
  "provider": {
    "openai": { "options": { "apiKey": "{env:OPENAI_API_KEY}" } }
  }
}

Drix já tem config.yaml, mas pode adicionar:
- Config por projeto (./drix.json no projeto)
- Variáveis de ambiente para chaves
- Precedência: global < projeto < env var
```

### 3. **Gestão Segura de API Keys** (`auth.json` + `opencode auth login`)
```
OpenCode:
- Chaves em ~/.local/share/opencode/auth.json (criptografado)
- CLI: opencode auth login / list / logout
- Suporte a múltiplos provedores simultâneos

Drix pode implementar:
- drix auth add openai <key>
- drix auth list
- Chaves criptografadas no HD (Fernet/AES)
- Nunca em config.yaml em texto plano
```

### 4. **Tools com Permissão** (`packages/core/src/tool/`)
```
OpenCode tools:
- read, write, edit, bash, grep, glob, task
- Cada tool tem: description, parameters, permissions
- Sistema de "ask" antes de executar

Drix pode criar:
class Tool:
    name: str
    description: str
    parameters: Schema
    permission: "ask" | "allow" | "deny"
    execute(): Result
```

### 5. **Sistema de Snapshot/Rollback** (`packages/core/src/snapshot/`)
```
OpenCode:
- Git-based snapshots automáticos
- Undo de mudanças do agente
- Reserva de tokens para compaction

Drix pode implementar leve:
- Antes de write/edit: snapshot do arquivo
- Stack de snapshots em memória/disco
- Comando "undo" para reverter última ação
```

---

## O Que NÃO Vale a Pena (Porque já tem ou é incompatível)

| Componente | Por que não |
|------------|-------------|
| **Interface Web Astro/Starlight** | Stack totalmente diferente (Node/TypeScript vs Python). Sua UI web atual já roda. Melhor melhorar a sua. |
| **TUI (terminal UI)** | `packages/tui` é React-Ink (TypeScript). Drix usa terminal nativo Python. |
| **Core Runtime (TypeScript)** | 50k+ linhas TS. Reescrever em Python = meses de trabalho. Seu engine Python + Ollama já funciona. |
| **Hono Server** | Seu `service.py` + API já faz o papel. |
| **Plugin System** | Arquitetura TS específica. Melhor criar o seu simples em Python. |

---

## O Que o Drix Já Tem MELHOR Que o OpenCode

| Drix | OpenCode |
|------|----------|
| ✅ **Ollama nativo** (binário + modelos + GPU auto) | Precisa configurar provedor manualmente |
| ✅ **Python portável** (WinPython incluso) | Precisa Node.js instalado no PC |
| ✅ **Auto-detecção de hardware** (RAM/GPU/modelo) | Não tem - usuário escolhe manual |
| ✅ **Zero instalação no PC hospedeiro** | Precisa instalar OpenCode |
| ✅ **Modelos locais offline** | Focado em APIs cloud |

---

## Roadmap Prático: O Que Implementar no Drix (Prioridade)

### **Fase 1 - Rápida (1-2 semanas)**
```python
# 1. Config por projeto (drix.json)
# 2. Variáveis de ambiente para chaves ({env:OPENAI_KEY})
# 3. drix auth add/list/remove (CLI simples)
# 4. Criptografia das chaves no HD (cryptography.Fernet)
```

### **Fase 2 - Core (2-4 semanas)**
```python
# 5. Agent Base Class (build/plan)
# 6. Tool System com permissão (ask/allow/deny)
# 7. Loop de execução com aprovação
# 8. Snapshot simples antes de write/edit
```

### **Fase 3 - Avançado (futuro)**
```python
# 9. MCP Server client (conectar servidores externos)
# 10. Subagents (agent lança sub-agent)
# 11. Compaction de contexto inteligente
```

---

## O Que Copiar do Repo OpenCode (Arquivos Específicos)

Se quiser olhar código real para inspiração, estes arquivos valem a pena:

```
packages/core/src/agent/
  ├── agent.ts          # Base agent class
  ├── build-agent.ts    # Build agent
  ├── plan-agent.ts     # Plan agent
  └── loop.ts           # Execution loop

packages/core/src/tool/
  ├── tool.ts           # Tool base
  ├── bash-tool.ts      # Execução segura
  ├── edit-tool.ts      # Edição de arquivos
  └── permission.ts     # Sistema ask/allow/deny

packages/core/src/config/
  ├── config.ts         # Schema + validação
  └── variables.ts      # {env:}, {file:} resolution

packages/core/src/auth/
  └── auth-store.ts     # auth.json handling
```

---

# MODOS DE OPERAÇÃO: OFFLINE E ONLINE (NOVA ANÁLISE)

## 7.1 Modo Offline (Padrão Atual)
- **Como funciona**: Usa modelos locais (Ollama) rodando no HD externo.
- **Requisitos**:
  - Ollama rodando localmente no HD (binário + modelos)
  - Sem necessidade de internet
- **Vantagens**:
  - Privacidade total (dados não saem do HD)
  - Funciona em PCs sem internet
  - Menor latência de resposta
- **Configuração atual**:
  ```yaml
  mode: offline
  provider:
    offline:
      name: ollama
      base_url: http://localhost:11434/v1
  ```

## 7.2 Modo Online (Futuro)
- **Como funciona**: Usa APIs externas (OpenAI, Anthropic, etc.) com chaves de API.
- **Requisitos**:
  - Conexão com a internet
  - Chave de API válida para o provedor escolhido
  - Permissões de rede (firewall liberado para a API)
- **Configuração**:
  ```yaml
  mode: online
  provider:
    online:
      name: openai
      api_key: {env:OPENAI_API_KEY}
  ```
- **Vantagens**:
  - Modelos mais poderosos (GPT-4, Claude 3, etc.)
  - Atualizações automáticas dos modelos
  - Acesso a recursos avançados (multimodal, etc.)

## 7.3 Segurança e Privacidade

| Modo | Privacidade | Segurança das Chaves |
|------|-----------|----------------------|
| **Offline** | Total | Máxima - chaves não são usadas |
| **Online** | Parcial | Moderada - chaves devem ser armazenadas com segurança |

### Recomendações de Segurança
- **Modo Offline**: Máxima segurança - sem envio de dados externos, ideal para projetos sensíveis
- **Modo Online**: 
  - Use variáveis de ambiente para chaves sensíveis: `export OPENAI_API_KEY="sk-..."`
  - Nunca armazene chaves em texto plano no `config.yaml`
  - Prefira arquivos criptografados para chaves sensíveis

### Como Alternar Entre Modos
| Método | Como usar |
|--------|-----------|
| **Configuração** | Alterar `config.yaml` e reiniciar o sistema |
| **CLI** | `drix mode offline` ou `drix mode online` |
| **Automático** | Sistema detecta Ollama ativo → modo offline |

## 7.4 Alterações Necessárias no Código Drix

### Atualizar `config.yaml`:
```yaml
mode: offline  # ou "online"
provider:
  offline:
    name: ollama
    base_url: http://localhost:11434/v1
  online:
    name: openai
    api_key: {env:OPENAI_API_KEY}
```

### Implementar Sistema de Auth:
```python
# CLI: drix auth add openai <key>
# drix auth list
# Chaves criptografadas no HD (cryptography.Fernet)
```

### Provider Base Class:
```python
class Provider:
    def generate_text(self, prompt: str) -> str: ...
    def get_models(self) -> list: ...
```

### Loop de Agentes com Modo:
```python
def execute_task(self, task):
    if config.mode == "online":
        result = external_api.generate_text(prompt)
    else:
        result = ollama.generate_text(prompt)
```

## 7.5 Considerações de Compatibilidade
- **Offline**: Funciona mesmo sem internet
- **Online**: Requer conexão + chave válida + provedor configurado
- **Compatibilidade**: Modo offline continua funcionando mesmo com internet ativa

---

## Veredito Final

**Sim, tem coisas úteis no OpenCode para o Drix** - mas **não a arquitetura principal**.

O que vale a pena:
1. **Padrões de design** (agents, tools, config, auth)
2. **Lógica de permissão/segurança**
3. **Schema de configuração**
4. **Sistema de snapshot/undo**

O que **não** vale a pena:
- Reescrever em TypeScript
- Usar Astro/Hono/React
- Copiar o core runtime

**Seu Drix já resolve o problema principal melhor que o OpenCode**: roda 100% offline, portável, com modelos locais, sem instalar nada no PC hospedeiro.

---

## Próximos Passos Recomendados para o Drix

1. **Implementar modo offline como padrão** (já está pronto ✅)
2. **Desenvolver sistema de autenticação de API** (próximas 2 semanas)
3. **Testar com 2 provedores diferentes** (ex: Ollama + OpenAI)
4. **Adicionar documentação clara** para alternância de modos

### Como Implementar o Modo Online (Passo a Passo Rápido)
1. **Atualize o config.yaml** com seção `online` e `{env:OPENAI_API_KEY}`
2. **Defina a chave de API** via variável de ambiente
3. **Reinicie o sistema** com `./launcher.sh`
4. **Teste** com `drix run "Qual é a capital da França?"`

---

✅ **Próxima etapa recomendada**: Crie um branch `online-mode` no seu repositório do Drix e implemente o primeiro provedor (ex: OpenAI) com segurança básica. Teste com seu HD externo em outro PC para validar a portabilidade real.

Este caminho é viável, realista e alinhado com o que você já tem no projeto. Você está no caminho certo! 🚀