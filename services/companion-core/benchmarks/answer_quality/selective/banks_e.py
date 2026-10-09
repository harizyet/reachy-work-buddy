"""Question paraphrase bank E (2026-10-15): two NEW phrasings per relation, written for the scorer-v3 validation worlds (corpus v5). Untouched: not used by banks C or D, by dev15, dev16, val17 or any
development probe, and written without running or reading scorer v3's output. Frozen by `bank_e.sha256` at the moment of writing, before any scorer-v3 evaluation. Same-author caveat as before (the author also
wrote the scorer): the contribution of a new bank is that the wording was never seen during development, not independence of authorship. {x} is the subject; {s} the system name where a relation uses one."""

BANK_E: dict[str, list[str]] = {
    "owner": ["Which person do I go to about the {x}?", "Remind me, whose is the {x}?"],
    "lead": ["Who is running {x} day to day?", "Name the person who leads {x}."],
    "retry_limit": ["Up to how many tries does the {x} give a failing job?", "What cap is there on retries for the {x}?"],
    "default_model": ["Which model does {x} fall back on unless told otherwise?", "Tell me {x}'s standard model."],
    "runs_on": ["Which box does {x} live on?", "What infrastructure hosts {x}?"],
    "rollback_window": ["After a bad {x} deploy, how many minutes do I have to back out?", "How long is the window for reverting {x}?"],
    "support_hours": ["Between which hours can {x} be reached on weekdays?", "What are the weekday opening hours for {x}?"],
    "decision": ["Which model came out of the {x} planning as the keeper?", "Where did {x} land on its default model?"],
    "reviews": ["What is on {x}'s review plate?", "Which review has {x} been given?"],
    "on_call": ["Who is carrying the pager for {x}?", "Whose turn is it to be on call for {x}?"],
    "budget_through": ["Up to which month is money set aside for {x}?", "How far ahead is {x} funded?"],
    "deadline": ["What date does {x} owe the written summary?", "By which day must {x} hand in the summary?"],
    "attends": ["Which people sat in on the {x} planning?", "Give me the attendee list for the {x} planning meeting."],
    "test_fixer": ["Who has picked up the {x} rollback test?", "Which person is responsible for repairing the {x} rollback test?"],
    "default_model_history": ["Back in March, which model was {x}'s default?", "Which model did {x} default to before the October change?"],
    "retry_limit_history": ["Under the archived {x} design, how many retries were allowed?", "How many retries used to apply to the {x}?"],
    "staging_env": ["Is a staging environment available for {x}?", "Does {x} stage changes anywhere before production?"],
    "security_reviewer": ["Who gives {x} its security sign-off?", "Which person is {x}'s security reviewer?"],
    "max_message_size": ["What is the largest message the {s} accepts?", "How big can a single {s} message be?"],
    "vacation": ["When does the {x} lead go on holiday next?", "What are the next days off for the {x} lead?"],
    "incident_auditor": ["Who goes through the {x} build logs after an incident?", "Which person audits the {x} logs once something breaks?"],
    "order_figure": ["Between the two memories on {x}, which is the later one?", "Does one memory about {x} come after and override the other?"],
    "standup": ["What time does {x}'s standup begin?", "At what time is the {x} daily standup?"],
    "review_day": ["On what weekday does {x} do its design review?", "Which weekday is {x}'s design review?"],
    # the four new existence-relation families
    "runbook": ["Is there a runbook for {x}?", "Does {x} have a runbook anyone can follow?"],
    "oncall_rotation": ["Does {x} run an on-call rotation?", "Is there a rotation of people on call for {x}?"],
    "escalation_channel": ["Is there an escalation channel for {x}?", "Does {x} have a channel for escalating incidents?"],
    "status_page": ["Does {x} publish a status page?", "Is there a status page for {x}?"],
}
