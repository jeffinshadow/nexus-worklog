# Constituição do Nexus Worklog

A base de toda decisão de código, design ou funcionalidade. Vale para quem mantém o projeto e para todo agente de IA que
trabalhe nele (críticos e implementadores recebem este documento antes de começar).

## 1. Hierarquia de pilares

**Segurança e privacidade são piso inegociável.** Nenhum pilar abaixo justifica ficar sem o mínimo: dados protegidos,
isolamento entre pessoas, privacidade por padrão.

Acima do piso, a ordem é estrita, e um pilar inferior nunca compromete um superior:
**Simples > Seguro > Funcional > Elegante**

- **Simples:** código enxuto, arquitetura direta, zero burocracia de uso e manutenção trivial.
- **Seguro:** proteção nativa dos dados, isolamento adequado e privacidade por padrão — além do piso.
- **Funcional:** resolve o problema real de forma rápida, sem passos extras ou fricção. Funciona no celular e sem sinal,
  porque o trabalho real acontece no campo.
- **Elegante:** interface limpa, agradável e intuitiva, sem sacrificar desempenho ou simplicidade.

## 2. Propósito central — o que o Nexus é

O Nexus existe para devolver tempo ao profissional, nunca para tomar. Foi projetado para ambientes dinâmicos, com alto
volume de demandas simultâneas e poucos processos engessados.

- **Organizador de prioridades:** um ponto focal para saber o que fazer agora e nunca esquecer pendências.
- **Registro de trabalho e tempo:** fonte fiel e sem atrito sobre o esforço investido no dia a dia.
- **Base de conhecimento viva:** repositório orgânico de soluções práticas, construído a partir das tarefas resolvidas.
- **Ponte assíncrona para a liderança:** facilita delegar demandas e ver o progresso da equipe como um todo. A autonomia é
  sagrada: a gestão delega o *o quê*; a responsabilidade, o *como* e o *quando* pertencem ao colaborador.

## 3. Anti-objetivos — o que o Nexus nunca será

- **Não é Jira, ERP ou sistema de chamados (ITSM):** sem fluxos de aprovação, burocracia corporativa ou campos
  obrigatórios infinitos.
- **Não é vigilância nem microgerenciamento:** proibido criar métricas punitivas, monitoramento invasivo ou ferramentas
  para a gestão cobrar a pessoa. (Lembrar a própria pessoa de cobrar um terceiro — "Dia para cobrar" — é ferramenta dela,
  não vigilância.)
- **Não é ranqueador de pessoas:** jamais comparar a produtividade de indivíduos nem gerar leaderboards.
- **Não é pesado ou complexo:** rejeita dependências desnecessárias, alto consumo de recursos ou interfaces que exijam
  treinamento.

## 4. Regras de trabalho

- **Orçamento de complexidade:** toda opção nova precisa justificar por que não pode ser o comportamento padrão. Tirar vem
  antes de acrescentar. Recurso que não é usado sai.
- **Os dados são do usuário:** exportar tudo e excluir de verdade, a qualquer momento; nada de prender (sem lock-in); o
  Nexus pode ser hospedado por quem o usa.
- **Quem decide:** na dúvida, a escolha do dono do projeto e o uso real valem mais que a opinião de críticos ou agentes.
- **Compatibilidade:** quebra de API ou MCP só em versão major; o que é antigo continua funcionando, marcado como
  obsoleto, até a major seguinte (ver `docs/ADMIN.md` e `docs/API.md`).
