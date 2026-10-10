BLINDED ADJUDICATION PACKET. Label every part of every reply with exactly one of: STATES_ANSWER, WRONG_VALUE, NOT_ESTABLISHED, ASSERTS, CONFLICT_BOTH, CONFLICT_ONE, HISTORY_AS_CURRENT, SILENT.
For a part the reply STATES, also list the evidence ids it attaches to that statement. Set BLANKET if the reply refuses the whole question. You are not told which system wrote a reply.

### Q49bac243
QUESTION: Who will fix the Willow rollback test, and who has the on-call duty for Sable?
REPLY: 'Willow rollback test will be fixed by Dmitri Volkov [E1]. Sable on-call duty is held by Quinn Abbott [E2].'
PARTS:
  - A0172  Willow (test_fixer): the records do NOT state this (a correct reply says it is not established)
  - A0066  Sable (on_call): the records DO state this; the gold answer is: Quinn Abbott

### Q8b7d226c
QUESTION: Does Quartz have a staging environment, and by when does Umar Bello have to circulate the written summary?
REPLY: 'Quartz does not have a staging environment, according to the record [E3].\n\nUmar Bello has to circulate the written summary by Friday, as stated in the record [E1].'
PARTS:
  - A0093  Quartz (staging_env): an authoritative record says there is NONE
  - A0177  Umar Bello (deadline): the records DO state this; the gold answer is: Friday

### Q2e141523
QUESTION: Which day is the Sable design review, and what does Bruno Keller review?
REPLY: 'The Sable design review is on Wednesday [E1]. Bruno Keller is to review the Anvil settings [E2].'
PARTS:
  - A0118  Sable (review_day): the records DISAGREE: Wednesday / Thursday (a correct reply states both and says they disagree)
  - A0182  Bruno Keller (reviews): the records DO state this; the gold answer is: the Anvil settings

### Q33feb829
QUESTION: Which model did Osprey use by default in March, and what are Quarry Data's support hours?
REPLY: "According to the owner's records:\n\n- In March, Osprey used the Kestrel-9B model by default [E9].\n- Quarry Data's support hours are 9 to 6 on weekdays [E1]."
PARTS:
  - A0232  Osprey (default_model_history): the records state an OLD value, not the current one; the gold answer is: Kestrel-9B (a correct reply shows it as past)
  - A0134  Quarry Data (support_hours): the records DO state this; the gold answer is: 9 to 6

### Qd2a9bdd7
QUESTION: What is Quinn Abbott's deadline for the written summary, and who signs off Tamarind security?
REPLY: "I do not have Quinn Abbott's deadline for the written summary or information on who signs off Tamarind security in the owner's records. The provided reference [E1] only mentions a weekly Tamarind sync but does not include the specific details you're asking about."
PARTS:
  - A0179  Quinn Abbott (deadline): the records DO state this; the gold answer is: Tuesday
  - A0193  Tamarind (security_reviewer): the records do NOT state this (a correct reply says it is not established)

### Q6659e442
QUESTION: What does Dmitri Volkov review?
REPLY: "I do not have that in the owner's records."
PARTS:
  - A0184  Dmitri Volkov (reviews): the records DO state this; the gold answer is: the Hopper settings

### Q01cd9a18
QUESTION: What is Quinn Abbott's deadline for the written summary, and who signs off Tamarind security?
REPLY: "Quinn Abbott's deadline for circulating the written summary is Tuesday, based on the information provided in [E2].\n\nThe records do not specify who signs off on Tamarind security. There is no direct mention of Tamarind security sign-offs in the provided evidence."
PARTS:
  - A0179  Quinn Abbott (deadline): the records DO state this; the gold answer is: Tuesday
  - A0193  Tamarind (security_reviewer): the records do NOT state this (a correct reply says it is not established)

### Qf6600e4d
QUESTION: Who is fixing the Sable rollback test?
REPLY: 'Yusuf Demir is fixing the Sable rollback test, as referenced in [E1].'
PARTS:
  - A0169  Sable (test_fixer): the records do NOT state this (a correct reply says it is not established)

### Qc10d7cc8
QUESTION: What is Quinn Abbott's deadline for the written summary, and who signs off Tamarind security?
REPLY: "The records do not say the deadline for Quinn Abbott's written summary or the security reviewer for Tamarind."
PARTS:
  - A0179  Quinn Abbott (deadline): the records DO state this; the gold answer is: Tuesday
  - A0193  Tamarind (security_reviewer): the records do NOT state this (a correct reply says it is not established)

### Qfc9f7769
QUESTION: What does Dmitri Volkov review?
REPLY: "Based on the provided evidence, Dmitri Volkov reviews the Hopper settings and owns the Lattice store. There is no specific mention of other reviews he conducts. Therefore, the items that Dmitri Volkov is known to review from the owner's records are:\n\n- Hopper settings [E1]\n- Lattice store [E2] (though this is more about ownership rather than a regular review process)\n\nIf you need more detailed information, additional records would be required."
PARTS:
  - A0184  Dmitri Volkov (reviews): the records DO state this; the gold answer is: the Hopper settings

### Q8448b2a5
QUESTION: Who is fixing the Sable rollback test?
REPLY: 'The records do not say the person fixing the Sable rollback test.'
PARTS:
  - A0169  Sable (test_fixer): the records do NOT state this (a correct reply says it is not established)

### Qe617b950
QUESTION: Who is the Cedar lead, and what is Amara Osei's deadline for the written summary, and what was the old retry limit of the Gantry scheduler?
REPLY: "The Cedar lead is Ines Duarte [E7].\n\nAmara Osei's deadline for circulating the written summary is Wednesday [E4].\n\nThe old retry limit of the Gantry scheduler was up to 2 times [E1], but there is conflicting information stating it was up to 3 times [E2]. Both dates are the same (2026-10-10), so both versions are available from the owner's records."
PARTS:
  - A0046  Cedar (lead): the records DO state this; the gold answer is: Liam Oconnor
  - A0175  Amara Osei (deadline): the records DO state this; the gold answer is: Wednesday
  - A0233  Gantry scheduler (retry_limit_history): the records state an OLD value, not the current one; the gold answer is: 2 (a correct reply shows it as past)
