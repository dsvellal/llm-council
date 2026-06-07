# dsvellal LLM Council

Run the dsvellal LLM Council deliberation system: multiple AI models answer your question independently, peer-review each other anonymously, and a Chairman synthesizes the final answer.

## Usage

```
/dsvellal-llm-council <your question>
```

Or just `/dsvellal-llm-council` with no args — you'll be prompted to enter your question.

## What it does

**Stage 1:** All council members answer your question simultaneously and independently, with no knowledge of each other's responses.

**Stage 2:** Each council member receives all Stage 1 responses, anonymized as "Response A", "Response B", etc. They evaluate and rank the responses without knowing which model wrote what. This prevents bias toward well-known models.

**Stage 3:** The Chairman (Claude Opus 4.8) receives everything — all answers and all peer rankings — and synthesizes a single final answer representing the council's collective wisdom.

Results are saved to `~/.claude/dsvellal-council-history/` as JSON files.

## Configuration

To change which models participate, edit `~/.claude/workflows/dsvellal-llm-council.js` — look for the `COUNCIL_MODELS` and `CHAIRMAN_MODEL` constants near the top of the file.

## Instructions

<skill>

When the user invokes `/dsvellal-llm-council`:

1. Read the args. If args are empty or missing, use AskUserQuestion to ask: "What would you like the council to deliberate on?" with a free-text option.

2. Once you have the question, run the workflow:

```javascript
Workflow({ name: "dsvellal-llm-council", args: "<the user's question>" })
```

3. While the workflow runs, do not add commentary — the workflow emits progressive output via log() that the user will see.

4. When the workflow completes, give a one-sentence summary: how many models participated and which model won the aggregate ranking.

</skill>
