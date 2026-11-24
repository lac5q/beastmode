import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { appendFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

import {
  buildJevRequest,
  collectToolCalls,
  compact,
  compactMessages,
  messageChars,
  type CallAction,
  type JevAsker,
  type JevQuestions,
  type Message,
} from '../src/index.js';

const REQUEST_MODEL = 'jev-1.13.0';
const FIXTURE_GOAL = 'adversarial compaction fixture';
const REDACTED_FIXTURE_KEY = 'fixture-key-redacted';

type Fixture = {
  id: string;
  description: string;
  preserveRecentMessages: number;
  expected: Record<string, CallAction>;
  messages: () => Message[];
  requiredOutput?: { toolUseId: string; text: string };
};

type RunRecord = {
  id: string;
  historyHash: string;
  baselineChars: number;
  proposalChars: number;
  decisions: Array<{ id: string; toolUseId: string; action: CallAction; reason: string }>;
  requests: number;
  requestHashes: string[];
  changedFromBaseline: boolean;
  semantic: {
    pairedBlocksValid: boolean;
    requiredTextRetained?: boolean;
    middleMarkerRetained?: boolean;
  };
  status: 'passed' | 'failed';
  errors: string[];
};

type LiveRunRecord = RunRecord & {
  inputMessages: Message[];
  outputMessages: Message[];
};

type LiveReceipt = {
  sequence: number;
  fixture: string;
  requestHash: string;
  requestBody: unknown;
  status: number | null;
  ok: boolean;
  wallMs: number;
  responseText?: string;
  responseBodyHash?: string;
  usage?: unknown;
  error?: string;
};

function hash(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

function parseJsonOrText(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function message(role: Message['role'], text: string, extra: Partial<Message> = {}): Message {
  return { role, text, toolUses: [], ...extra };
}

function call(
  id: string,
  tool: string,
  input: Record<string, unknown>,
  text = 'tool completed',
): Message {
  return message('assistant', '', {
    toolUses: [{ tool_use_id: id, tool, input, text }],
  });
}

function result(id: string, text: string, isError = false): Message {
  return message('user', '', { toolResults: [{ tool_use_id: id, text, isError }] });
}

function longMiddleBody(marker: string): string {
  const prefix = 'head line\n'.repeat(90);
  const suffix = '\ntail line'.repeat(90);
  const fixedMarker = marker.padEnd(48, '_').slice(0, 48);
  const fillerLength = 2400 - prefix.length - fixedMarker.length - suffix.length;
  assert.ok(fillerLength > 0, 'long middle fixture must fit its marker');
  return `${prefix}${fixedMarker}${'x'.repeat(fillerLength)}${suffix}`;
}

const middleCritical = longMiddleBody('CRITICAL-MIDDLE-EVIDENCE::retain-this-line');
const middleBenign = longMiddleBody('BENIGN-MIDDLE-EVIDENCE::same-metadata');
assert.equal(middleCritical.length, middleBenign.length);

function requiredOldFailure(): Message[] {
  return [
    message('user', 'Repair the test and retain the failure receipt.'),
    call('failure-receipt', 'Bash', { command: 'npm test -- b.test.ts' }),
    result('failure-receipt', 'FAILURE_RECEIPT::expected 2 to be 3', true),
    message('assistant', 'Continue from the recorded failure.'),
    message('user', 'continue'),
  ];
}

function contradictoryEvidence(): Message[] {
  return [
    message('user', 'Resolve the configuration conflict using the old evidence.'),
    call('contradiction', 'Read', { file_path: 'config/runtime.json' }),
    result(
      'contradiction',
      'CONTRADICTION::old evidence says port=8080; a later note says port=9090.',
    ),
    message('assistant', 'The two historical observations disagree.'),
    message('user', 'keep enough evidence to resolve it'),
  ];
}

function approvalScopeConstraint(): Message[] {
  return [
    message('user', 'Work only inside the approved source scope.'),
    call('approval-scope', 'Read', { file_path: 'src/approved.ts' }),
    result(
      'approval-scope',
      'APPROVAL_SCOPE::approved paths are src/approved.ts and tests/; do not edit generated/.',
    ),
    message('assistant', 'The historical approval boundary is relevant.'),
    message('user', 'proceed within scope'),
  ];
}

function duplicateOutput(): Message[] {
  return [
    message('user', 'Inspect the repository status.'),
    call('duplicate-1', 'Bash', { command: 'git status --short' }),
    result('duplicate-1', 'clean\n'),
    call('duplicate-2', 'Bash', { command: 'git status --short' }),
    result('duplicate-2', 'clean\n'),
    message('assistant', 'The duplicate status output does not add evidence.'),
    message('user', 'continue'),
  ];
}

function longMiddleEvidence(body = middleCritical): Message[] {
  return [
    message('user', 'Review the old file output before deciding what can be shortened.'),
    call('middle-evidence', 'Read', { file_path: 'src/large-report.txt' }),
    result('middle-evidence', body),
    message('assistant', 'The important line may be in the middle of the old output.'),
    message('user', 'continue'),
  ];
}

function missingKeyErrorFallback(): Message[] {
  return [
    message('user', 'Exercise the fallback path without a configured provider key.'),
    call('fallback-call', 'Bash', { command: 'true' }),
    result('fallback-call', 'ok'),
    message('assistant', 'The fallback should preserve the original transcript.'),
    message('user', 'continue'),
  ];
}

function toolPairing(): Message[] {
  return [
    message('user', 'Drop one paired duplicate while preserving all unrelated blocks.'),
    call('paired-drop', 'Read', { file_path: 'src/duplicate.ts' }),
    result('paired-drop', 'duplicate output'),
    call('paired-keep', 'Bash', { command: 'npm test' }),
    result('paired-keep', 'required output'),
    call('unfinished-call', 'Read', { file_path: 'src/not-yet-returned.ts' }),
    result('orphan-result', 'pre-existing orphan result'),
    message('user', 'latest turn'),
  ];
}

function recentPin(): Message[] {
  return [
    message('user', 'The old call may be dropped, but the newest call is pinned.'),
    call('old-call', 'Read', { file_path: 'src/old.ts' }),
    result('old-call', 'old output'),
    message('assistant', 'new work starts here'),
    call('recent-call', 'Bash', { command: 'npm test -- recent.test.ts' }),
    result('recent-call', 'recent output'),
  ];
}

const FIXTURES: readonly Fixture[] = [
  {
    id: 'required-old-failure-receipt',
    description: 'An old error receipt is retained verbatim.',
    preserveRecentMessages: 1,
    expected: { 'failure-receipt': 'keep' },
    messages: requiredOldFailure,
    requiredOutput: { toolUseId: 'failure-receipt', text: 'FAILURE_RECEIPT::expected 2 to be 3' },
  },
  {
    id: 'contradictory-old-evidence',
    description: 'Conflicting historical evidence remains available for resolution.',
    preserveRecentMessages: 1,
    expected: { contradiction: 'keep' },
    messages: contradictoryEvidence,
    requiredOutput: { toolUseId: 'contradiction', text: 'CONTRADICTION::' },
  },
  {
    id: 'approval-scope-constraint',
    description: 'An old scope boundary is retained verbatim.',
    preserveRecentMessages: 1,
    expected: { 'approval-scope': 'keep' },
    messages: approvalScopeConstraint,
    requiredOutput: { toolUseId: 'approval-scope', text: 'APPROVAL_SCOPE::' },
  },
  {
    id: 'duplicate-output-safe-drop',
    description: 'A duplicate output is the only proposed full call drop.',
    preserveRecentMessages: 1,
    expected: { 'duplicate-1': 'keep', 'duplicate-2': 'drop_call' },
    messages: duplicateOutput,
  },
  {
    id: 'long-middle-evidence',
    description: 'A deterministic proposal truncates a result whose important marker is in the middle.',
    preserveRecentMessages: 1,
    expected: { 'middle-evidence': 'drop_result' },
    messages: () => longMiddleEvidence(),
  },
  {
    id: 'missingkey-error-fallback',
    description: 'Missing-key and provider-error paths fail closed to the caller.',
    preserveRecentMessages: 1,
    expected: { 'fallback-call': 'keep' },
    messages: missingKeyErrorFallback,
  },
  {
    id: 'tool-pairing',
    description: 'A paired drop removes both blocks while pre-existing unpaired blocks remain untouched.',
    preserveRecentMessages: 1,
    expected: { 'paired-drop': 'drop_call', 'paired-keep': 'keep' },
    messages: toolPairing,
  },
  {
    id: 'recent-pin',
    description: 'A recent paired call stays pinned even when its answer is zero.',
    preserveRecentMessages: 2,
    expected: { 'old-call': 'drop_call', 'recent-call': 'keep' },
    messages: recentPin,
  },
];

// Filled from the first deterministic run and checked on every normal run.
// A changed history or serialized request is a review signal, not a reason to
// silently refresh the fixture.
const FROZEN_HISTORY_HASHES: Record<string, string> = {
  'required-old-failure-receipt': 'cf3869a5abe46c29f93b15d034e080625cdda0abd6bf72206a9ad7a20abe7e9f',
  'contradictory-old-evidence': '046eee05f593949532f58e2454318decc5be31a521a86b2f05f1646ece217732',
  'approval-scope-constraint': 'a8c921db1bb34cd7c19898e426c25ad599d9cb7c4f8b8aa9a856a551b3018b94',
  'duplicate-output-safe-drop': '2c83726b8299827fdc063ae76b6f009db832c8438f0169e9e6ec57ee41a455da',
  'long-middle-evidence': '0883e68716e80cfadf3465656ffdb13caa6437dfa58aef6660c6f80b1c003be0',
  'missingkey-error-fallback': 'b98b8e20e244107bb199f748e0334f91bca3f66e1d6a7137460d6b7459650913',
  'tool-pairing': '0dcf70908c0c71551a67994cde1874903b8d1033bcb171dfa0b52527477fa97b',
  'recent-pin': 'aaa228a732baafa9a4c62c08f4bd4455a7daa5ae4fe3f6eda8996186a36455dc',
};

const FROZEN_BLINDNESS_HASHES = {
  criticalHistory: '0883e68716e80cfadf3465656ffdb13caa6437dfa58aef6660c6f80b1c003be0',
  benignHistory: '4c52fa7f3003527bed0d8e95a6ab4ac8d62b92c6f9a14a05703b88ec57494e2a',
  requestBody: '23edc1e62c9db601a763b1ac959f77234d507668ab08fd9b68ff121348a80438',
};

function optionsFor(fixture: Fixture) {
  return {
    goal: FIXTURE_GOAL,
    preserveRecentMessages: fixture.preserveRecentMessages,
    keepThreshold: 0.5,
    truncateHeadChars: 300,
  } as const;
}

function actionReason(action: CallAction): string {
  if (action === 'keep') return 'kept';
  if (action === 'drop_result') return 'result_dropped';
  return 'call_dropped';
}

function answerFor(action: CallAction, questionName: string): number {
  if (questionName.startsWith('call_')) return action === 'drop_call' ? 0.01 : 0.99;
  return action === 'keep' ? 0.99 : 0.01;
}

function makeFakeJev(
  expectedByInternalId: Map<string, CallAction>,
  requestHashes: string[],
): JevAsker {
  return {
    async ask(state, questions: JevQuestions) {
      const request = buildJevRequest(
        { apiKey: REDACTED_FIXTURE_KEY, model: REQUEST_MODEL },
        state,
        questions,
      );
      requestHashes.push(hash(request.body));
      const answers = Object.fromEntries(
        Object.keys(questions).map((name) => {
          const internalId = name.replace(/^(call|result)_/, '');
          const action = expectedByInternalId.get(internalId);
          assert.ok(action, `fake Jev received an unexpected question: ${name}`);
          return [name, { type: 'noul' as const, noul: answerFor(action, name) }];
        }),
      );
      return { answers };
    },
  };
}

function pairedBlockIds(messages: readonly Message[]): Set<string> {
  const uses = new Set(messages.flatMap((entry) => entry.toolUses.map((tool) => tool.tool_use_id)));
  const results = new Set(
    messages.flatMap((entry) => (entry.toolResults ?? []).map((item) => item.tool_use_id)),
  );
  return new Set([...uses].filter((id) => results.has(id)));
}

function blockById(messages: readonly Message[], id: string) {
  return {
    use: messages.flatMap((entry) => entry.toolUses).find((tool) => tool.tool_use_id === id),
    result: messages
      .flatMap((entry) => entry.toolResults ?? [])
      .find((item) => item.tool_use_id === id),
  };
}

function assertPairInvariants(
  original: readonly Message[],
  proposal: readonly Message[],
  calls: ReturnType<typeof collectToolCalls>,
  actions: Map<string, CallAction>,
): void {
  const proposalPaired = pairedBlockIds(proposal);
  const candidateIds = new Set(calls.map((call) => call.tool_use_id));
  const originalUses = new Map(original.flatMap((entry) => entry.toolUses).map((tool) => [tool.tool_use_id, tool]));
  const originalResults = new Map(
    original.flatMap((entry) => entry.toolResults ?? []).map((item) => [item.tool_use_id, item]),
  );
  for (const tool of proposal.flatMap((entry) => entry.toolUses)) {
    assert.ok(originalUses.has(tool.tool_use_id), `proposal invented tool ${tool.tool_use_id}`);
  }
  for (const item of proposal.flatMap((entry) => entry.toolResults ?? [])) {
    assert.ok(originalResults.has(item.tool_use_id), `proposal invented result ${item.tool_use_id}`);
  }
  for (const call of calls) {
    const originalBlocks = blockById(original, call.tool_use_id);
    const proposalBlocks = blockById(proposal, call.tool_use_id);
    assert.ok(originalBlocks.use && originalBlocks.result, `${call.tool_use_id} must be paired in input`);
    const action = actions.get(call.id);
    assert.ok(action, `missing action for ${call.id}`);
    if (action === 'drop_call') {
      assert.equal(proposalBlocks.use, undefined, `${call.tool_use_id} call was not dropped`);
      assert.equal(proposalBlocks.result, undefined, `${call.tool_use_id} result was not dropped`);
    } else {
      assert.ok(proposalBlocks.use, `${call.tool_use_id} call became an orphan`);
      assert.ok(proposalBlocks.result, `${call.tool_use_id} result became an orphan`);
      assert.equal(proposalBlocks.use.tool, originalBlocks.use.tool, `${call.tool_use_id} tool changed`);
      assert.deepEqual(proposalBlocks.use.input, originalBlocks.use.input, `${call.tool_use_id} input changed`);
      assert.equal(
        proposalPaired.has(call.tool_use_id),
        true,
        `${call.tool_use_id} must remain paired`,
      );
    }
  }
  for (const [id, tool] of originalUses) {
    if (!candidateIds.has(id)) assert.deepEqual(blockById(proposal, id).use, tool);
  }
  for (const [id, item] of originalResults) {
    if (!candidateIds.has(id)) assert.deepEqual(blockById(proposal, id).result, item);
  }
}

function assertTextMessagesPreserved(original: readonly Message[], proposal: readonly Message[]): void {
  const originalText = original.filter((entry) => entry.text.length > 0).map((entry) => entry.text);
  const proposalText = proposal.filter((entry) => entry.text.length > 0).map((entry) => entry.text);
  assert.deepEqual(proposalText, originalText, 'text messages must remain verbatim and ordered');
}

async function runFixture(fixture: Fixture, checkFreeze: boolean): Promise<RunRecord> {
  const original = fixture.messages();
  const originalSnapshot = structuredClone(original);
  const historyHash = hash(JSON.stringify(original));
  if (checkFreeze) assert.equal(historyHash, FROZEN_HISTORY_HASHES[fixture.id], `${fixture.id} history drifted`);

  const calls = collectToolCalls(original, fixture.preserveRecentMessages);
  assert.deepEqual(
    new Set(calls.map((call) => call.tool_use_id)),
    new Set(Object.keys(fixture.expected)),
    `${fixture.id} expected call set drifted`,
  );
  const expectedByInternalId = new Map(
    calls.map((call) => [call.id, fixture.expected[call.tool_use_id]!]),
  );
  const requestHashes: string[] = [];
  const proposal = await compact(original, makeFakeJev(expectedByInternalId, requestHashes), optionsFor(fixture));
  assert.deepEqual(original, originalSnapshot, `${fixture.id} mutated its source history`);

  const actionByInternalId = new Map(proposal.decisions.map((decision) => [decision.id, decision.action]));
  assert.deepEqual(
    proposal.decisions.map((decision) => ({
      id: decision.id,
      toolUseId: calls.find((call) => call.id === decision.id)?.tool_use_id,
      action: decision.action,
      reason: decision.reason,
    })),
    calls.map((call) => ({
      id: call.id,
      toolUseId: call.tool_use_id,
      action: fixture.expected[call.tool_use_id],
      reason: call.pinned ? 'pinned' : actionReason(fixture.expected[call.tool_use_id]!),
    })),
    `${fixture.id} decision semantics changed`,
  );
  assertPairInvariants(original, proposal.messages, calls, actionByInternalId);
  assertTextMessagesPreserved(original, proposal.messages);

  if (fixture.requiredOutput) {
    const outputBlock = blockById(proposal.messages, fixture.requiredOutput.toolUseId).result;
    assert.ok(outputBlock, `${fixture.id} required result disappeared`);
    assert.ok(outputBlock.text.includes(fixture.requiredOutput.text), `${fixture.id} required evidence disappeared`);
  }
  const outputMiddle = blockById(proposal.messages, 'middle-evidence').result?.text;

  const baselineChars = original.reduce((sum, entry) => sum + messageChars(entry), 0);
  const proposalChars = proposal.messages.reduce((sum, entry) => sum + messageChars(entry), 0);
  return {
    id: fixture.id,
    historyHash,
    baselineChars,
    proposalChars,
    decisions: proposal.decisions.map((decision) => ({
      id: decision.id,
      toolUseId: calls.find((call) => call.id === decision.id)?.tool_use_id ?? '',
      action: decision.action,
      reason: decision.reason,
    })),
    requests: proposal.stats.requests,
    requestHashes,
    changedFromBaseline: JSON.stringify(proposal.messages) !== JSON.stringify(original),
    semantic: {
      pairedBlocksValid: true,
      ...(fixture.requiredOutput
        ? {
            requiredTextRetained: blockById(proposal.messages, fixture.requiredOutput.toolUseId).result?.text.includes(
              fixture.requiredOutput.text,
            ),
          }
        : {}),
      ...(fixture.id === 'long-middle-evidence'
        ? { middleMarkerRetained: outputMiddle?.includes('CRITICAL-MIDDLE-EVIDENCE') ?? false }
        : {}),
    },
    status: 'passed',
    errors: [],
  };
}

async function runFallbackChecks(fixture: Fixture): Promise<{ missingKey: string; providerError: string }> {
  let fetchCalled = false;
  await assert.rejects(
    compactMessages(fixture.messages(), {
      ...optionsFor(fixture),
      apiKey: '',
      fetch: async () => {
        fetchCalled = true;
        throw new Error('network must not be reached for missing key');
      },
    }),
    /TYPESAFE_API_KEY/,
  );
  assert.equal(fetchCalled, false, 'missing-key path must fail before fetch');

  await assert.rejects(
    compactMessages(fixture.messages(), {
      ...optionsFor(fixture),
      apiKey: 'fixture-key',
      fetch: (async () => new Response('fixture upstream failure', { status: 503 })) as typeof fetch,
    }),
    /503/,
  );
  return { missingKey: 'passed', providerError: 'passed' };
}

async function runBlindnessPair(checkFreeze: boolean): Promise<{
  criticalHistory: string;
  benignHistory: string;
  requestHashes: string[];
  identicalRequestBodies: boolean;
}> {
  const fixture = FIXTURES.find((candidate) => candidate.id === 'long-middle-evidence')!;
  const histories = [longMiddleEvidence(middleCritical), longMiddleEvidence(middleBenign)];
  const requestHashes: string[] = [];
  const historyHashes = histories.map((history) => hash(JSON.stringify(history)));
  for (const history of histories) {
    const historySnapshot = structuredClone(history);
    const calls = collectToolCalls(history, fixture.preserveRecentMessages);
    const expected = new Map(calls.map((call) => [call.id, fixture.expected[call.tool_use_id]!])) as Map<
      string,
      CallAction
    >;
    const output = await compact(history, makeFakeJev(expected, requestHashes), optionsFor(fixture));
    assert.equal(output.decisions[0]?.action, 'drop_result');
    assert.deepEqual(history, historySnapshot, 'blindness fixture source changed');
  }
  const identicalRequestBodies = requestHashes.length === 2 && requestHashes[0] === requestHashes[1];
  assert.equal(identicalRequestBodies, true, 'result-body-only change must not change Jev request body');
  if (checkFreeze) {
    assert.deepEqual(historyHashes, [FROZEN_BLINDNESS_HASHES.criticalHistory, FROZEN_BLINDNESS_HASHES.benignHistory]);
    assert.equal(requestHashes[0], FROZEN_BLINDNESS_HASHES.requestBody);
  }
  return {
    criticalHistory: historyHashes[0]!,
    benignHistory: historyHashes[1]!,
    requestHashes,
    identicalRequestBodies,
  };
}

async function runLiveHistory(
  fixture: Fixture,
  original: Message[],
  apiKey: string,
  receiptPath: string,
  receipts: LiveReceipt[],
  receiptLabel = fixture.id,
): Promise<LiveRunRecord> {
  const originalSnapshot = structuredClone(original);
  const calls = collectToolCalls(original, fixture.preserveRecentMessages);
  const bodyHashes: string[] = [];
  const errors: string[] = [];
  const fetcher: typeof fetch = async (input, init) => {
    const started = Date.now();
    const requestText = String(init?.body ?? '');
    const requestHash = hash(requestText);
    const requestBody = parseJsonOrText(requestText);
    bodyHashes.push(requestHash);
    try {
      const response = await globalThis.fetch(input, init);
      const responseText = await response.clone().text();
      const receipt: LiveReceipt = {
        sequence: receipts.length + 1,
        fixture: receiptLabel,
        requestHash,
        requestBody,
        status: response.status,
        ok: response.ok,
        wallMs: Date.now() - started,
        responseText,
        responseBodyHash: hash(responseText),
      };
      try {
        const parsed: unknown = JSON.parse(responseText);
        if (parsed && typeof parsed === 'object' && 'usage' in parsed) {
          receipt.usage = (parsed as { usage?: unknown }).usage;
        }
      } catch {
        // JevClient will preserve the malformed-body error after this receipt.
      }
      receipts.push(receipt);
      const line = JSON.stringify(receipt);
      await appendFile(receiptPath, `${line}\n`, 'utf8');
      console.error(line);
      return response;
    } catch (error) {
      const receipt: LiveReceipt = {
        sequence: receipts.length + 1,
        fixture: receiptLabel,
        requestHash,
        requestBody,
        status: null,
        ok: false,
        wallMs: Date.now() - started,
        error: error instanceof Error ? error.message : String(error),
      };
      receipts.push(receipt);
      const line = JSON.stringify(receipt);
      await appendFile(receiptPath, `${line}\n`, 'utf8');
      console.error(line);
      throw error;
    }
  };
  const output = await compactMessages(original, {
    ...optionsFor(fixture),
    apiKey,
    model: REQUEST_MODEL,
    fetch: fetcher,
  });
  assert.deepEqual(original, originalSnapshot, `${fixture.id} live run mutated its source history`);
  assertPairInvariants(
    original,
    output.messages,
    calls,
    new Map(output.decisions.map((decision) => [decision.id, decision.action])),
  );
  assertTextMessagesPreserved(original, output.messages);
  const outputMiddle = blockById(output.messages, 'middle-evidence').result?.text;
  const requiredTextRetained = fixture.requiredOutput
    ? blockById(output.messages, fixture.requiredOutput.toolUseId).result?.text.includes(fixture.requiredOutput.text) ?? false
    : undefined;
  if (requiredTextRetained === false) errors.push('requiredTextRetained=false');
  const inputHasCriticalMarker = blockById(original, 'middle-evidence').result?.text.includes('CRITICAL-MIDDLE-EVIDENCE') ?? false;
  const middleMarkerRetained = inputHasCriticalMarker
    ? outputMiddle?.includes('CRITICAL-MIDDLE-EVIDENCE') ?? false
    : undefined;
  if (middleMarkerRetained === false) errors.push('middleMarkerRetained=false');
  return {
    id: fixture.id,
    historyHash: hash(JSON.stringify(original)),
    baselineChars: original.reduce((sum, entry) => sum + messageChars(entry), 0),
    proposalChars: output.messages.reduce((sum, entry) => sum + messageChars(entry), 0),
    decisions: output.decisions.map((decision) => ({
      id: decision.id,
      toolUseId: calls.find((call) => call.id === decision.id)?.tool_use_id ?? '',
      action: decision.action,
      reason: decision.reason,
    })),
    requests: output.stats.requests,
    requestHashes: bodyHashes,
    changedFromBaseline: JSON.stringify(output.messages) !== JSON.stringify(original),
    semantic: {
      pairedBlocksValid: true,
      ...(requiredTextRetained === undefined ? {} : { requiredTextRetained }),
      ...(middleMarkerRetained === undefined ? {} : { middleMarkerRetained }),
    },
    status: errors.length === 0 ? 'passed' : 'failed',
    errors,
    inputMessages: originalSnapshot,
    outputMessages: structuredClone(output.messages),
  };
}

async function runLive(
  fixture: Fixture,
  apiKey: string,
  receiptPath: string,
  receipts: LiveReceipt[],
): Promise<LiveRunRecord> {
  const original = fixture.messages();
  assert.equal(
    hash(JSON.stringify(original)),
    FROZEN_HISTORY_HASHES[fixture.id],
    `${fixture.id} live history is not the frozen history`,
  );
  return runLiveHistory(fixture, original, apiKey, receiptPath, receipts);
}

async function appendCaseAudit(
  auditPath: string,
  fixtureId: string,
  inputMessages: Message[],
  run: LiveRunRecord | undefined,
  error?: string,
): Promise<void> {
  const line = JSON.stringify({
    fixture: fixtureId,
    status: run?.status ?? 'failed',
    errors: run?.errors ?? (error ? [error] : []),
    inputMessages,
    outputMessages: run?.outputMessages ?? null,
    semantic: run?.semantic ?? { pairedBlocksValid: false },
    decisions: run?.decisions ?? [],
  });
  await appendFile(auditPath, `${line}\n`, 'utf8');
}

function liveSummary(run: LiveRunRecord): RunRecord {
  const { inputMessages: _input, outputMessages: _output, ...summary } = run;
  return summary;
}

async function main(): Promise<void> {
  const live = process.argv.includes('--live');
  const printFreezes = process.argv.includes('--print-freezes');
  const fixtureRuns: RunRecord[] = [];
  for (const fixture of FIXTURES) fixtureRuns.push(await runFixture(fixture, !printFreezes));
  const blindness = await runBlindnessPair(!printFreezes);

  if (printFreezes) {
    console.log(JSON.stringify({
      historyHashes: Object.fromEntries(fixtureRuns.map((run) => [run.id, run.historyHash])),
      blindness: {
        criticalHistory: blindness.criticalHistory,
        benignHistory: blindness.benignHistory,
        requestBody: blindness.requestHashes[0],
      },
    }, null, 2));
    return;
  }

  const fallbackFixture = FIXTURES.find((fixture) => fixture.id === 'missingkey-error-fallback')!;
  const fallback = await runFallbackChecks(fallbackFixture);
  const report: Record<string, unknown> = {
    status: 'passed',
    requested_model: 'gpt-5.6-luna max',
    actual_backend: 'unverified',
    package: 'fast-jev-compaction@0.2.0',
    pinned_commit: 'e3f262a7f4d42bd8dd32ced30d26176f7cb545b0',
    mode: live ? 'fake-plus-live' : 'fake-only',
    fixture_count: FIXTURES.length,
    conservative_baseline: 'keep every paired call and full result; proposals are advisory prompt views',
    fallback,
    full_output_blindness: blindness,
    fixtures: fixtureRuns,
  };

  if (live) {
    const apiKey = process.env.TYPESAFE_API_KEY;
    if (!apiKey) throw new Error('--live requires TYPESAFE_API_KEY; no live request was made');
    const receiptPath = join(process.cwd(), 'spikes', 'compaction-live-receipts.jsonl');
    const auditPath = join(process.cwd(), 'spikes', 'compaction-live-cases.jsonl');
    await writeFile(receiptPath, '', 'utf8');
    await writeFile(auditPath, '', 'utf8');
    const receipts: LiveReceipt[] = [];
    const liveRuns: LiveRunRecord[] = [];
    const caseFailures: Array<{ id: string; error: string; errors?: string[] }> = [];
    for (const fixture of FIXTURES) {
      const inputMessages = fixture.messages();
      try {
        const run = await runLive(fixture, apiKey, receiptPath, receipts);
        liveRuns.push(run);
        await appendCaseAudit(auditPath, fixture.id, inputMessages, run);
        if (run.status === 'failed') caseFailures.push({ id: fixture.id, error: 'semantic check failed', errors: run.errors });
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        caseFailures.push({ id: fixture.id, error: detail });
        const failedRun: LiveRunRecord = {
          id: fixture.id,
          historyHash: FROZEN_HISTORY_HASHES[fixture.id]!,
          baselineChars: 0,
          proposalChars: 0,
          decisions: [],
          requests: 0,
          requestHashes: [],
          changedFromBaseline: false,
          semantic: { pairedBlocksValid: false },
          status: 'failed',
          errors: [detail],
          inputMessages: structuredClone(inputMessages),
          outputMessages: [],
        };
        liveRuns.push(failedRun);
        await appendCaseAudit(auditPath, fixture.id, inputMessages, failedRun, detail);
      }
    }
    const longFixture = FIXTURES.find((fixture) => fixture.id === 'long-middle-evidence')!;
    let liveBenign: LiveRunRecord | undefined;
    const benignInput = longMiddleEvidence(middleBenign);
    try {
      liveBenign = await runLiveHistory(
        longFixture,
        benignInput,
        apiKey,
        receiptPath,
        receipts,
        'long-middle-evidence-benign-body',
      );
      await appendCaseAudit(auditPath, 'long-middle-evidence-benign-body', benignInput, liveBenign);
      if (liveBenign.status === 'failed') {
        caseFailures.push({ id: 'long-middle-evidence-benign-body', error: 'semantic check failed', errors: liveBenign.errors });
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      caseFailures.push({ id: 'long-middle-evidence-benign-body', error: detail });
      await appendCaseAudit(auditPath, 'long-middle-evidence-benign-body', benignInput, undefined, detail);
    }
    const liveCritical = liveRuns.find((run) => run.id === longFixture.id)!;
    const liveBlindness = {
      criticalRequestHash: liveCritical.requestHashes[0],
      benignRequestHash: liveBenign?.requestHashes[0],
      identicalRequestBodies:
        Boolean(liveCritical.requestHashes[0]) &&
        Boolean(liveBenign?.requestHashes[0]) &&
        liveCritical.requestHashes[0] === liveBenign?.requestHashes[0],
    };
    if (!liveBlindness.identicalRequestBodies) {
      caseFailures.push({
        id: 'live-full-output-blindness',
        error: 'result-body-only histories produced different serialized requests',
      });
    }
    if (liveCritical.requestHashes[0] && liveCritical.requestHashes[0] !== FROZEN_BLINDNESS_HASHES.requestBody) {
      caseFailures.push({
        id: 'live-frozen-request-hash',
        error: 'live critical request did not match the frozen request hash',
      });
    }
    report.live = {
      model: REQUEST_MODEL,
      status: caseFailures.length === 0 ? 'passed' : 'failed',
      case_failures: caseFailures,
      case_failure_count: caseFailures.length,
      receipts_path: receiptPath,
      case_audit_path: auditPath,
      receipt_count: receipts.length,
      runs: liveRuns.map(liveSummary),
      full_output_blindness: {
        ...liveBlindness,
      },
      note: 'Live decisions are proposals only; frozen fake expectations remain the comparison baseline.',
    };
    report.status = caseFailures.length === 0 ? 'passed' : 'failed';
  }

  console.log(JSON.stringify(report, null, 2));
}

main().catch((error: unknown) => {
  console.error(JSON.stringify({
    status: 'failed',
    error: error instanceof Error ? error.message : String(error),
  }, null, 2));
  process.exitCode = 1;
});
