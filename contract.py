# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import datetime
import json
from genlayer import *

@gl.evm.contract_interface
class _Recipient:
    class View:
        pass
    class Write:
        pass

class QualityScoredBounty(gl.Contract):
    poster_map: TreeMap[str, Address]
    worker_map: TreeMap[str, Address]
    description_map: TreeMap[str, str]
    reference_url_map: TreeMap[str, str]
    deliverable_url_map: TreeMap[str, str]
    pool_map: TreeMap[str, u256]
    worker_payout_map: TreeMap[str, u256]
    poster_refund_map: TreeMap[str, u256]
    score_map: TreeMap[str, u256]
    reasoning_map: TreeMap[str, str]
    status_map: TreeMap[str, str]
    deadline_map: TreeMap[str, str]
    bounty_counter: u256

    def __init__(self):
        self.bounty_counter = u256(0)

    @gl.public.write.payable
    def post_bounty(self, task_description: str, reference_url: str, worker_address: str, minutes_until_deadline: int) -> str:
        assert gl.message.value > u256(0), "You must fund the bounty with a positive amount"

        bounty_id = f"B{self.bounty_counter}"
        self.bounty_counter += u256(1)

        self.poster_map[bounty_id] = gl.message.sender_address
        self.worker_map[bounty_id] = Address(worker_address)
        self.description_map[bounty_id] = task_description
        self.reference_url_map[bounty_id] = reference_url
        self.deliverable_url_map[bounty_id] = ""
        self.pool_map[bounty_id] = gl.message.value
        self.worker_payout_map[bounty_id] = u256(0)
        self.poster_refund_map[bounty_id] = u256(0)
        self.score_map[bounty_id] = u256(0)
        self.reasoning_map[bounty_id] = ""
        self.status_map[bounty_id] = "OPEN"
        self.deadline_map[bounty_id] = str(datetime.datetime.now() + datetime.timedelta(minutes=minutes_until_deadline))

        return bounty_id

    @gl.public.write
    def cancel_bounty(self, bounty_id: str) -> None:
        assert gl.message.sender_address == self.poster_map[bounty_id], "Only the poster can cancel"
        assert self.status_map[bounty_id] == "OPEN", "Bounty not open"

        pool = self.pool_map[bounty_id]
        self.status_map[bounty_id] = "CANCELLED"
        self.poster_refund_map[bounty_id] = pool
        _Recipient(self.poster_map[bounty_id]).emit_transfer(value=pool)

    @gl.public.write
    def claim_timeout_refund(self, bounty_id: str) -> None:
        assert self.status_map[bounty_id] == "OPEN", "Bounty already scored or cancelled"
        assert str(datetime.datetime.now()) >= self.deadline_map[bounty_id], "Deadline has not passed yet"

        pool = self.pool_map[bounty_id]
        self.status_map[bounty_id] = "TIMED_OUT"
        self.poster_refund_map[bounty_id] = pool
        _Recipient(self.poster_map[bounty_id]).emit_transfer(value=pool)

    @gl.public.write
    def submit_deliverable(self, bounty_id: str, deliverable_url: str) -> str:
        assert self.status_map[bounty_id] == "OPEN", "Bounty not open"
        assert gl.message.sender_address == self.worker_map[bounty_id], "Only the assigned worker can submit"
        assert str(datetime.datetime.now()) < self.deadline_map[bounty_id], "Deadline has passed"

        self.deliverable_url_map[bounty_id] = deliverable_url
        description = self.description_map[bounty_id]
        reference_url = self.reference_url_map[bounty_id]

        def judge() -> str:
            reference_content = gl.nondet.web.render(reference_url, mode="text")
            deliverable_content = gl.nondet.web.render(deliverable_url, mode="text")
            prompt = f"""You are scoring the quality of submitted work against a task and a reference.

Task description:
\"\"\"{description}\"\"\"

Reference content (what the deliverable should match or satisfy):
\"\"\"{reference_content[:3000]}\"\"\"

Submitted deliverable content:
\"\"\"{deliverable_content[:3000]}\"\"\"

Score how well the deliverable satisfies the task, using the reference as your
standard. You must choose a score from exactly this set of values, no others:
0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100.

Respond with strict JSON only, no markdown, no extra text:
{{"score": 80, "reasoning": "<one sentence>"}}
"""
            return gl.nondet.exec_prompt(prompt)

        raw = gl.eq_principle.prompt_comparative(
            judge,
            "The score field must match exactly (one of 0, 10, 20, ..., 100). Reasoning wording may vary but must express the same underlying judgment.",
        )

        try:
            parsed = json.loads(raw)
        except Exception:
            raise Exception("Scorer output was not valid JSON; refusing to score.")

        assert isinstance(parsed, dict), "Scorer output was not a JSON object; refusing to score."
        assert "score" in parsed, "Scorer output missing 'score' field; refusing to score."
        score = parsed["score"]
        assert isinstance(score, int) and not isinstance(score, bool), "Scorer 'score' field was not an integer; refusing to score."
        assert score in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100), "Scorer 'score' was outside the allowed domain; refusing to score."

        reasoning = parsed.get("reasoning", "")
        assert isinstance(reasoning, str), "Scorer 'reasoning' field was not a string; refusing to score."

        pool = self.pool_map[bounty_id]
        worker_payout = (pool * u256(score)) // u256(100)
        poster_refund = pool - worker_payout

        self.score_map[bounty_id] = u256(score)
        self.reasoning_map[bounty_id] = reasoning
        self.worker_payout_map[bounty_id] = worker_payout
        self.poster_refund_map[bounty_id] = poster_refund
        self.status_map[bounty_id] = "SCORED"

        if worker_payout > u256(0):
            _Recipient(self.worker_map[bounty_id]).emit_transfer(value=worker_payout)
        if poster_refund > u256(0):
            _Recipient(self.poster_map[bounty_id]).emit_transfer(value=poster_refund)

        return f"Scored {score}/100 - worker paid {worker_payout} wei, poster refunded {poster_refund} wei"

    @gl.public.view
    def get_bounty(self, bounty_id: str) -> dict:
        return {
            "bounty_id": bounty_id,
            "poster": str(self.poster_map[bounty_id]),
            "worker": str(self.worker_map[bounty_id]),
            "description": self.description_map[bounty_id],
            "reference_url": self.reference_url_map[bounty_id],
            "deliverable_url": self.deliverable_url_map[bounty_id],
            "pool": str(self.pool_map[bounty_id]),
            "status": self.status_map[bounty_id],
            "score": str(self.score_map[bounty_id]),
            "reasoning": self.reasoning_map[bounty_id],
            "worker_payout": str(self.worker_payout_map[bounty_id]),
            "poster_refund": str(self.poster_refund_map[bounty_id]),
            "deadline": self.deadline_map[bounty_id],
        }

    @gl.public.view
    def get_bounty_count(self) -> int:
        return int(self.bounty_counter)
