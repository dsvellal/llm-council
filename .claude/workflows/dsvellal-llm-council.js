export const meta = {
  name: "dsvellal-llm-council",
  description: "Run the dsvellal LLM Council: parallel answers → anonymized peer review → Chairman synthesis",
  phases: [
    { title: "Stage 1", detail: "All council members answer independently in parallel" },
    { title: "Stage 2", detail: "All council members rank anonymized peer responses in parallel" },
    { title: "Stage 3", detail: "Chairman synthesizes a final answer from all responses and rankings" },
  ],
};

// ---------------------------------------------------------------------------
// CONFIG — edit these to change which models serve as council members or Chairman.
//
// Claude models on Bedrock (via native agent() model parameter):
//   claude-opus-4-8     — most capable, slowest, most expensive
//   claude-sonnet-4-6   — balanced speed / intelligence
//   claude-haiku-4-5    — fastest, cheapest
//
// Non-Claude models on Bedrock (via bedrock_query.py helper):
//   meta.llama3-70b-instruct-v1:0
//   meta.llama3-1-70b-instruct-v1:0
//   mistral.mistral-large-2402-v1:0
//   mistral.mixtral-8x7b-instruct-v0:1
//   amazon.titan-text-premier-v1:0
//   cohere.command-r-plus-v1:0
//
// Run `aws bedrock list-foundation-models` to verify which models are enabled
// in your account before adding them here.
// ---------------------------------------------------------------------------

const COUNCIL_MODELS = [
  { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6", type: "claude" },
  { id: "claude-haiku-4-5",  label: "Claude Haiku 4.5",  type: "claude" },
  { id: "meta.llama3-70b-instruct-v1:0", label: "Llama 3 70B", type: "bedrock" },
  { id: "mistral.mistral-large-2402-v1:0", label: "Mistral Large", type: "bedrock" },
];

const CHAIRMAN_MODEL = {
  id: "claude-opus-4-8",
  label: "Claude Opus 4.8",
  type: "claude",
};

// ---------------------------------------------------------------------------
// Helper: query a non-Claude Bedrock model via the shared Python script.
// ---------------------------------------------------------------------------
async function queryBedrockModel(modelId, prompt) {
  const escapedPrompt = prompt.replace(/'/g, "'\\''");
  return await agent(
    `Run this shell command and return ONLY the raw stdout output, nothing else:

python3 ~/.claude/scripts/bedrock_query.py --model '${modelId}' --prompt '${escapedPrompt}'

Return only the model's response text. Do not add commentary, do not reformat.`,
    { label: `bedrock:${modelId}` }
  );
}

// ---------------------------------------------------------------------------
// Helper: query any council member (Claude or Bedrock).
// ---------------------------------------------------------------------------
async function queryCouncilMember(member, prompt) {
  if (member.type === "claude") {
    return await agent(prompt, { label: member.label, model: member.id });
  }
  return await queryBedrockModel(member.id, prompt);
}

// ---------------------------------------------------------------------------
// PREREQUISITE CHECK — lightweight, runs on every invocation.
// Uses a 1-hour cache for the slow model-access checks.
// ---------------------------------------------------------------------------
phase("Prerequisites");

const preCheckResult = await agent(
  `Run this command and return the raw JSON output, nothing else:

python3 ~/.claude/scripts/dsvellal_council_setup.py --check`,
  { label: "prereq-check" }
);

let prereqs;
try {
  prereqs = JSON.parse(preCheckResult);
} catch (_) {
  prereqs = { ok: false, issues: ["Could not parse setup check output: " + preCheckResult] };
}

if (!prereqs.ok) {
  const issueList = prereqs.issues.join("\n  • ");
  log(`\n❌ Prerequisites not met:\n  • ${issueList}`);
  log("\nRun /dsvellal-llm-council-setup to fix these issues, then try again.");
  return { error: "Prerequisites failed", issues: prereqs.issues };
}

if (prereqs.warnings && prereqs.warnings.length > 0) {
  log(`\n⚠️  Warnings (some Bedrock models may be unavailable):`);
  prereqs.warnings.forEach(w => log(`  • ${w}`));
}

log(`✓ Prerequisites OK (AWS: ${prereqs.identity || "authenticated"}, region: ${prereqs.region || "detected"})`);

// ---------------------------------------------------------------------------
// Stage 1: each council member answers independently.
// ---------------------------------------------------------------------------
phase("Stage 1");
const userQuery = args;

log(`Question: ${userQuery}`);
log(`Council: ${COUNCIL_MODELS.map(m => m.label).join(", ")}`);

const stage1Results = await parallel(
  COUNCIL_MODELS.map(member => () =>
    queryCouncilMember(member, userQuery).then(response => ({
      model: member.label,
      response: response || "(no response)",
    }))
  )
);

const validStage1 = stage1Results.filter(Boolean);

log(`Stage 1 complete — ${validStage1.length}/${COUNCIL_MODELS.length} models responded`);

// Display each response as it comes in
for (const result of validStage1) {
  log(`\n--- ${result.model} ---\n${result.response}`);
}

if (validStage1.length === 0) {
  return { error: "All council members failed to respond." };
}

// ---------------------------------------------------------------------------
// Stage 2: anonymize responses, then each model ranks peers.
// ---------------------------------------------------------------------------
phase("Stage 2");

const labels = validStage1.map((_, i) => String.fromCharCode(65 + i)); // A, B, C...
const labelToModel = {};
labels.forEach((label, i) => {
  labelToModel[`Response ${label}`] = validStage1[i].model;
});

const anonymizedText = validStage1
  .map((r, i) => `Response ${labels[i]}:\n${r.response}`)
  .join("\n\n");

const rankingPrompt = `You are evaluating different responses to the following question:

Question: ${userQuery}

Here are the responses from different models (anonymized):

${anonymizedText}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example format:
FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:`;

log(`Collecting peer rankings from all ${validStage1.length} council members...`);

const stage2Results = await parallel(
  COUNCIL_MODELS.map(member => () =>
    queryCouncilMember(member, rankingPrompt).then(response => ({
      model: member.label,
      ranking: response || "(no response)",
    }))
  )
);

const validStage2 = stage2Results.filter(Boolean);

// Parse rankings and compute aggregate
function parseRanking(text) {
  if (!text || !text.includes("FINAL RANKING:")) return [];
  const section = text.split("FINAL RANKING:")[1];
  const numbered = section.match(/\d+\.\s*Response [A-Z]/g) || [];
  if (numbered.length > 0) {
    return numbered.map(m => m.match(/Response [A-Z]/)[0]);
  }
  return section.match(/Response [A-Z]/g) || [];
}

const modelPositions = {};
for (const ranking of validStage2) {
  const parsed = parseRanking(ranking.ranking);
  parsed.forEach((label, idx) => {
    const modelName = labelToModel[label];
    if (!modelName) return;
    if (!modelPositions[modelName]) modelPositions[modelName] = [];
    modelPositions[modelName].push(idx + 1);
  });
}

const aggregateRankings = Object.entries(modelPositions)
  .map(([model, positions]) => ({
    model,
    avgRank: (positions.reduce((a, b) => a + b, 0) / positions.length).toFixed(2),
    votes: positions.length,
  }))
  .sort((a, b) => parseFloat(a.avgRank) - parseFloat(b.avgRank));

// Display Stage 2 results
for (const result of validStage2) {
  log(`\n--- ${result.model}'s evaluation ---\n${result.ranking}`);
}

log("\n--- Aggregate Rankings (lower avg = better) ---");
aggregateRankings.forEach((r, i) => {
  log(`${i + 1}. ${r.model} — avg rank ${r.avgRank} (${r.votes} votes)`);
});

// ---------------------------------------------------------------------------
// Stage 3: Chairman synthesizes the final answer.
// ---------------------------------------------------------------------------
phase("Stage 3");

const stage1Text = validStage1
  .map(r => `Model: ${r.model}\nResponse: ${r.response}`)
  .join("\n\n");

const stage2Text = validStage2
  .map(r => `Model: ${r.model}\nRanking: ${r.ranking}`)
  .join("\n\n");

const chairmanPrompt = `You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: ${userQuery}

STAGE 1 - Individual Responses:
${stage1Text}

STAGE 2 - Peer Rankings:
${stage2Text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:`;

log(`\nChairman (${CHAIRMAN_MODEL.label}) synthesizing final answer...`);

const stage3Response = await queryCouncilMember(CHAIRMAN_MODEL, chairmanPrompt);

log(`\n${"=".repeat(60)}`);
log("CHAIRMAN'S FINAL ANSWER");
log("=".repeat(60));
log(stage3Response);

// ---------------------------------------------------------------------------
// Persist to JSON history
// ---------------------------------------------------------------------------
const historyDir = `${process.env.HOME}/.claude/dsvellal-council-history`;
const timestamp = new Date().toISOString().replace(/[:.]/g, "-");

const historyEntry = {
  timestamp,
  question: userQuery,
  stage1: validStage1,
  stage2: {
    rankings: validStage2.map(r => ({
      ...r,
      parsed: parseRanking(r.ranking),
    })),
    labelToModel,
    aggregateRankings,
  },
  stage3: {
    model: CHAIRMAN_MODEL.label,
    response: stage3Response,
  },
};

await agent(
  `Create the directory ${historyDir} if it does not exist, then write the following JSON to the file ${historyDir}/${timestamp}.json:

${JSON.stringify(historyEntry, null, 2)}

Confirm when done.`,
  { label: "save-history" }
);

log(`\nSession saved to ~/.claude/dsvellal-council-history/${timestamp}.json`);

return historyEntry;
