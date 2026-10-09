"""Question phrasings per relation, in two banks written BEFORE the revised relation lexicon existed (2026-10-12).

Bank A (phrasings 0 and 1) is the design bank: the revised lexicon may be developed against it. Bank B (phrasings 2 and 3) is the UNSEEN bank: it is hashed in `bank_b.sha256` at the moment of writing,
before any lexicon or matcher change, and it is used only by the acceptance set and the paraphrase-recall measurement on that set. The three relations in HELD_OUT (release_day, escalation_contact,
storage_limit) are new relations nobody has designed against; all four of their phrasings are unseen and they are used only for acceptance.

Honest limit: the same author wrote both banks, so 'unseen' means unseen by the lexicon, not written by an independent person. {x} is the subject."""

BANKS: dict[str, list[str]] = {
    "owner": ["Who owns the {x}?", "Who is responsible for the {x}?", "Whose job is it to look after the {x}?", "Who is accountable for keeping the {x} running?"],
    "lead": ["Who leads {x}?", "Who is the {x} lead?", "Who is in charge of {x}?", "Who heads up {x}?"],
    "retry_limit": ["How many times does the {x} retry a failed job?", "What is the retry limit of the {x}?", "How often is a failed job on the {x} tried again before it is parked?", "How many attempts does a job get on the {x} before being parked?"],
    "default_model": ["Which model does {x} use by default?", "What is {x}'s default model?", "Which model is {x} running as its default?", "What model is the standard one for {x}?"],
    "runs_on": ["Where does {x} run?", "Which host serves {x}?", "On what hardware is {x} served?", "What machine is {x} deployed on?"],
    "rollback_window": ["What is the rollback window for {x}?", "How long do I have to roll back a failed {x} deploy?", "Within how many minutes must a {x} rollback happen?", "What is the time limit for undoing a bad {x} deploy?"],
    "support_hours": ["What are {x}'s support hours?", "When is {x} support open on weekdays?", "When can I reach {x}?", "What times is {x} staffed during the week?"],
    "decision": ["What was decided about {x}'s default model?", "Which model did {x} decide to keep?", "What did the {x} planning decide on the model?", "Which model did the {x} team agree to keep?"],
    "attends": ["Who attended the {x} planning meeting?", "Who was in the {x} planning meeting?", "Which people took part in the {x} planning?", "Who joined the {x} planning session?"],
    "reviews": ["What is {x} reviewing?", "What does {x} review?", "What review is {x} responsible for?", "What is {x} supposed to look over?"],
    "on_call": ["Who is on call for {x}?", "Who has the on-call duty for {x}?", "Who covers {x} out of hours?", "Who gets paged when {x} breaks?"],
    "budget_through": ["Through when is the {x} budget approved?", "Until which month is {x} funded?", "How long does the {x} budget run?", "When does {x}'s funding end?"],
    "deadline": ["By when does {x} have to circulate the written summary?", "What is {x}'s deadline for the written summary?", "When must {x} send the written summary?", "When is {x}'s written summary due?"],
    # held out entirely: new relations, all four phrasings unseen
    "release_day": ["On which weekday do {x} releases ship?", "Which day of the week does {x} release?", "When does {x} cut a release?", "What day are {x} deploys made?"],
    "escalation_contact": ["Who should I escalate {x} incidents to?", "Who is the escalation contact for {x}?", "Who do I call when a {x} incident gets serious?", "Who handles escalations for {x}?"],
    "storage_limit": ["What is the storage limit of the {x}?", "How many GB per tenant does the {x} allow?", "How much space does each tenant get on the {x}?", "What is the per-tenant quota on the {x}?"],
}
HELD_OUT = {"release_day", "escalation_contact", "storage_limit"}
