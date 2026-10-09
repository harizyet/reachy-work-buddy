"""Question phrasings for the selective-answering corpus (v4), in two banks written BEFORE the sub-claim scorer existed (2026-10-12).

Bank C (phrasings 0 and 1): design. Bank D (phrasings 2 and 3): unseen; hashed in `bank_d.sha256` at the moment of writing and used only by the acceptance set.
HELD_OUT relations (release_day, escalation_contact, approver) appear in every phrasing only in the acceptance set. Same-author caveat as before. {x} is the subject."""

BANKS: dict[str, list[str]] = {
    "owner": ["Who owns the {x}?", "Who is responsible for the {x}?", "Whose job is it to look after the {x}?", "Who is accountable for keeping the {x} running?"],
    "lead": ["Who leads {x}?", "Who is the {x} lead?", "Who is in charge of {x}?", "Who heads up {x}?"],
    "retry_limit": ["How many times does the {x} retry a failed job?", "What is the retry limit of the {x}?", "How often is a failed job on the {x} tried again before it is parked?", "How many attempts does a job get on the {x} before being parked?"],
    "default_model": ["Which model does {x} use by default?", "What is {x}'s default model?", "Which model is {x} running as its default?", "What model is the standard one for {x}?"],
    "runs_on": ["Where does {x} run?", "Which host serves {x}?", "On what hardware is {x} served?", "What machine is {x} deployed on?"],
    "rollback_window": ["What is the rollback window for {x}?", "How long do I have to roll back a failed {x} deploy?", "Within how many minutes must a {x} rollback happen?", "What is the time limit for undoing a bad {x} deploy?"],
    "support_hours": ["What are {x}'s support hours?", "When is {x} support open on weekdays?", "When can I reach {x}?", "What times is {x} staffed during the week?"],
    "decision": ["What was decided about {x}'s default model?", "Which model did {x} decide to keep?", "What did the {x} planning decide on the model?", "Which model did the {x} team agree to keep?"],
    "reviews": ["What is {x} reviewing?", "What does {x} review?", "What review is {x} responsible for?", "What is {x} supposed to look over?"],
    "on_call": ["Who is on call for {x}?", "Who has the on-call duty for {x}?", "Who covers {x} out of hours?", "Who gets paged when {x} breaks?"],
    "budget_through": ["Through when is the {x} budget approved?", "Until which month is {x} funded?", "How long does the {x} budget run?", "When does {x}'s funding end?"],
    "deadline": ["By when does {x} have to circulate the written summary?", "What is {x}'s deadline for the written summary?", "When must {x} send the written summary?", "When is {x}'s written summary due?"],
    "attends": ["Who attended the {x} planning meeting?", "Who was in the {x} planning meeting?", "Which people took part in the {x} planning?", "Who joined the {x} planning session?"],
    "test_fixer": ["Who is fixing the {x} rollback test?", "Who will fix the {x} rollback test?", "Whose task is the {x} rollback test?", "Who has taken on the {x} rollback test?"],
    "default_model_history": ["Which model did {x} use by default in March?", "What was {x}'s default model before October?", "Which model did {x} run as its default earlier this year?", "Before the switch, which model was {x}'s default?"],
    "retry_limit_history": ["How many retries did the archived {x} architecture allow?", "What was the old retry limit of the {x}?", "Before the change, how many times was a failed job on the {x} retried?", "What retry count did the first version of the {x} architecture state?"],
    # acceptance-only relations: all four phrasings unseen
    "release_day": ["On which weekday do {x} releases ship?", "Which day of the week does {x} release?", "When does {x} cut a release?", "What day are {x} deploys made?"],
    "escalation_contact": ["Who should I escalate {x} incidents to?", "Who is the escalation contact for {x}?", "Who do I call when a {x} incident gets serious?", "Who handles escalations for {x}?"],
    "staging_env": ["Does {x} have a staging environment?", "Is there a staging environment for {x}?", "Can {x} changes be tried out in staging first?", "Has {x} got somewhere to stage a release?"],
    "approver": ["Who approved the {x} release?", "Who signed off the {x} release?", "Whose approval did the {x} release get?", "Who gave the go-ahead for the {x} release?"],
    # recorded for nobody or only in a sensitive record
    "security_reviewer": ["Who is the security reviewer for {x}?", "Who signs off {x} security?", "Which person approves {x} security changes?", "Who vets {x} for security?"],
    "max_message_size": ["What is the maximum message size of the {s}?", "How large can a {s} message be?", "What size limit applies to {s} messages?", "How big may one {s} message get?"],
    "vacation": ["When is the {x} lead's next vacation?", "When will the {x} lead be away next?", "Which dates is the {x} lead on leave?", "When is the {x} lead out of office next?"],
    "incident_auditor": ["Who audits the {x} build logs?", "Who is going to audit the {x} build logs after the incident?", "Which person checks the {x} build logs?", "Who reviews the {x} build logs for the incident?"],
    # ordering questions over undated or conflicting records
    "order_figure": ["Which of the two memories about {x} is more recent?", "Was {x} updated in one memory after the other memory gave a different answer?", "Did one of the two memories about {x} replace the other?", "Which memory about {x} should I treat as the newer one?"],
    # two memories created on the same day that disagree: nothing in what is shown orders them
    "standup": ["What time is the {x} standup?", "When does the {x} standup start?", "At what hour does {x} hold its standup?", "When is {x}'s daily standup?"],
    "review_day": ["On which day are {x} design reviews held?", "Which day is the {x} design review?", "What weekday do {x} design reviews fall on?", "When does {x} hold its design review?"],
}
HELD_OUT = {"release_day", "escalation_contact", "approver"}
