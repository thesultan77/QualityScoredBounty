# QualityScoredBounty

**Proportional-Payout Work Bounty with AI Quality Scoring on GenLayer**

A freelance bounty contract where payout isn't a binary "satisfied or not" —
a worker's deliverable is scored on a quality gradient against a reference,
and the poster's pool splits proportionally based on that score.

---

## What it does

1. A poster **funds a bounty** assigned to one specific worker address, with
   a task description, a reference URL (what good work should match or
   satisfy), and a deadline.
2. The assigned worker **submits a deliverable URL**.
3. The contract fetches both the reference and the deliverable content and
   asks an LLM to score the deliverable against the task, strictly from
   that evidence, on a **0–100 scale restricted to multiples of 10**
   (0, 10, 20, ... 100). GenLayer's validator consensus
   (`gl.eq_principle.prompt_comparative`) ensures multiple independent LLM
   runs agree on the exact discrete score before it's accepted on-chain.
4. Payout is **proportional**, not binary: the worker receives
   `pool * score / 100`, and the poster is refunded the remainder. A
   deliverable scored 80 pays the worker 80% of the pool and refunds the
   poster the other 20% — nobody has to argue about whether the work was
   "good enough," the gradient settles it automatically.
5. Safety exits: the poster can **cancel** before any deliverable is
   submitted, and anyone can trigger a **timeout refund** if the deadline
   passes with nothing submitted.

## Why this is different

Every other AI-judged escrow/bounty contract in this series (TaskMatchEscrow,
ReputationTaskMatch) pays out on a strict binary verdict — `SATISFIED` gets
everything, `UNSATISFIED` gets nothing. Real freelance work is rarely that
clean cut. QualityScoredBounty introduces a genuinely different payout
mechanic: a graded score that directly determines a proportional split,
without ever asking the LLM to generate a free-form continuous number
(which would be a much harder target for validator consensus). Restricting
the score to 11 discrete decile values keeps the consensus problem exactly
as tractable as a binary judgment, while making the payout itself far more
nuanced.

## Architecture

| Concern | Mechanism |
|---|---|
| Bounty state | Parallel `TreeMap[str, ...]` fields per bounty ID (poster, worker, description, URLs, pool, score, reasoning, status, deadline) |
| AI scoring | `gl.nondet.web.render` fetches both reference and deliverable content; `gl.nondet.exec_prompt` inside a closure, reconciled across validators via `gl.eq_principle.prompt_comparative` |
| Output safety | Scorer output is validated (JSON parse, structure, field presence, type, and domain restricted to the 11 allowed decile values) before any state mutation or fund transfer |
| Payout | Proportional — `worker_payout = pool * score // 100`, `poster_refund = pool - worker_payout`, pure integer `u256` arithmetic so every validator's computation is byte-identical |
| Fund safety | Funds only move on `submit_deliverable` (scored payout split), `cancel_bounty` (full refund, only before submission), or `claim_timeout_refund` (full refund, deadline passed with nothing submitted) |

Each bounty is assigned to one specific worker address at creation time
(the same single-assigned-worker pattern as TaskMatchEscrow and
ReputationTaskMatch) — only that address can submit a deliverable, and only
one submission is allowed per bounty.

## Contract methods

### Write

- **`post_bounty(task_description: str, reference_url: str, worker_address: str, minutes_until_deadline: int) -> str`** *(payable)*
  Poster funds the bounty pool and assigns it to a specific worker. Returns
  the new `bounty_id` (e.g. `"B0"`).
- **`submit_deliverable(bounty_id: str, deliverable_url: str) -> str`**
  Assigned worker submits their deliverable, triggering AI scoring,
  validator consensus, and the proportional payout split. Returns
  `"Scored <score>/100 - worker paid <x> wei, poster refunded <y> wei"`.
- **`cancel_bounty(bounty_id: str)`**
  Poster reclaims the full pool, but only before any deliverable has been
  submitted.
- **`claim_timeout_refund(bounty_id: str)`**
  Anyone can trigger a full refund to the poster once the deadline has
  passed with no deliverable submitted.

### View

- **`get_bounty(bounty_id: str) -> dict`**
  Full current state of a bounty (poster, worker, description, URLs, pool,
  status, score, reasoning, payout split, deadline).
- **`get_bounty_count() -> int`**

## Tested end-to-end in GenLayer Studio

- **Low-score path:** `post_bounty` funded with 2 GEN, deliverable submitted
  as an exact copy of the reference URL itself (not an actual summary) —
  the LLM correctly identified this didn't satisfy "summarize the key
  facts" and scored it **0/100**, with the full pool correctly refunded to
  the poster (`poster_refund: 2000000000000000000`, `worker_payout: 0`),
  `FINALIZED`/`SUCCESS`.
- **High-score path:** a second bounty funded with 2 GEN, deliverable
  submitted as a genuine, accurate summary (hosted as a raw GitHub Gist)
  — the LLM scored it **80/100**, correctly identifying it captured the
  key points but omitted some reference details (e.g. the language's
  creator). Payout split correctly to `worker_payout: 1600000000000000000`
  (1.6 GEN) and `poster_refund: 400000000000000000` (0.4 GEN) — exactly
  80%/20% as the formula specifies. `FINALIZED`/`SUCCESS` with full
  validator consensus.
- `get_bounty` confirmed correct final state for both bounties (status,
  score, reasoning, and payout amounts all matching the transaction
  output).
- Validator consensus observed reaching agreement through leader rotation
  in cases where individual validators' own independent LLM re-runs
  disagreed or hit non-JSON output — the contract's output-validation
  safety code correctly caused those validators to refuse rather than
  silently guess, with consensus settling once enough validators converged
  on the same discrete score.

## Deployment

```
# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

No VecDB/embeddings dependency needed for this contract. Constructor takes
no arguments. Deploy directly in GenLayer Studio or via `genlayer-js`
against Studionet / Bradbury testnet.

## Notes on GenVM quirks discovered while building this

- Restricting an LLM-judged numeric output to a small fixed set of
  discrete values (here, multiples of 10 from 0 to 100) keeps validator
  consensus just as tractable as a binary categorical judgment, while
  still allowing a much richer, proportional payout outcome than a
  binary verdict would.
- `isinstance(score, int) and not isinstance(score, bool)` is needed when
  validating a JSON-parsed numeric field — in Python, `bool` is a subclass
  of `int`, so a naive `isinstance(score, int)` check alone would silently
  accept `true`/`false` as valid scores.
- Proportional payout math (`pool * score // 100`) is done entirely in
  integer `u256` arithmetic — no floats anywhere in the payout path, so
  every validator's computation is byte-identical.

## Notes on design decisions

- The scorer's output is validated (JSON structure, field presence, type,
  and domain restricted to the 11 allowed decile values) before any state
  change or fund transfer — the same safety pattern applied proactively
  across every contract in this series after it was flagged as a required
  fix on an earlier contract (SemanticDisputeRouter).
- Each bounty is a 1:1 agreement between a poster and one pre-assigned
  worker rather than an open multi-submission board — this keeps the
  contract's fund-safety logic simple and matches the pattern already
  proven in TaskMatchEscrow and ReputationTaskMatch, while the proportional
  payout formula is what's genuinely new here.

## License

MIT
