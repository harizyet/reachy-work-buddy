# I-2 follow-up: every dev15 sub-claim that is not an exact match, with the reply (T-new = question text only; the gold-spec arm differs only in the two not-understood questions)

Cause codes: `ambiguity` = an authorised record about this subject and relation holds two values in one sentence, so the single-valued answer is withheld by design; `no_admitted_record` = no sentence names the subject with the relation's cue (or the record is excluded as instruction-bearing); `not_typed` = the decomposer withheld the clause.

## False abstentions (27)

- D15-054 decision / Cedar (gold SUPPORTED ['keep Swift-20B as the default model']): got NOT_TYPED; cause `not_typed`  
  Q: What was decided about Cedar's default model, and who is the security reviewer for Sable?  
  reply: 'The records do not say the security reviewer for Sable.\nI could not work out one part of the question, so I have not answered it.'
- D15-059 default_model / Cedar (gold SUPPORTED ['Swift-20B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: What is Cedar's default model, and how large can a Sluice cache message be?  
  reply: 'The records on the default model of Cedar are unclear, so I will not pick an answer.\nThe records do not say the maximum message size of the Sluice cache.'
- D15-070 default_model / Sable (gold SUPPORTED ['Swift-20B']): got UNSUPPORTED; cause `no_admitted_record`  
  Q: Which model does Sable use by default, and when is the Vesper lead's next vacation?  
  reply: 'The records do not say the default model of Sable or the next days off for the Vesper lead.'
- D15-071 default_model_history / Cedar (gold HISTORICAL ['Merlin-2B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who is the Quartz lead, and which model did Tamarind decide to keep, and what was Cedar's default model before October?  
  reply: 'The lead of Quartz is Pablo Reyes [E57].\nThe planning decision for Tamarind is keep Kestrel-3B as the default model [E233].\nThe records on the default model of Cedar are unclear, so I will not pick an answer.'
- D15-072 default_model / Osprey (gold SUPPORTED ['Swift-6B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Which model does Osprey use by default, and by when does Elena Marsh have to circulate the written summary, and how many retries did the archived Hopper ingest service architecture allow?  
  reply: "The deadline for Elena Marsh's written summary is Tuesday [E131].\nPreviously, the retry limit of the Hopper ingest service was 6 retries [E175].\nThe records on the default model of Osprey are unclear, so I will not pick an answer."
- D15-074 decision / Quartz (gold SUPPORTED ['keep Merlin-2B as the default model']): got NOT_TYPED; cause `not_typed`  
  Q: What was decided about Quartz's default model, and who owns the Anvil builder, and how many retries did the archived Anvil builder architecture allow?  
  reply: 'The owner of the Anvil builder is Umar Bello [E10].\nPreviously, the retry limit of the Anvil builder was 5 retries [E173].\nI could not work out one part of the question, so I have not answered it.'
- D15-076 default_model_history / Marlin (gold HISTORICAL ['Kestrel-3B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who is on call for Sable, and where does Heron-12B run, and which model did Marlin use by default in March?  
  reply: 'The person on call for Sable is Quinn Abbott [E126].\nThe host running Heron-12B is the CPU host [E140] [E156].\nThe records on the default model of Marlin are unclear, so I will not pick an answer.'
- D15-081 default_model / Marlin (gold SUPPORTED ['Heron-12B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: What is Marlin's default model, and who is the Vesper lead, and who is going to audit the Quartz build logs after the incident?  
  reply: 'The lead of Vesper is Kavya Menon [E44].\nThe records on the default model of Marlin are unclear, so I will not pick an answer.\nThe records do not say the person who audits the Quartz build logs.'
- D15-082 default_model_history / Osprey (gold HISTORICAL ['Kestrel-9B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who is fixing the Vesper rollback test, and where does Kestrel-3B run, and which model did Osprey use by default in March?  
  reply: 'The person fixing the Vesper rollback test is Kavya Menon [E260].\nThe host running Kestrel-3B is the GPU host [E146].\nThe records on the default model of Osprey are unclear, so I will not pick an answer.'
- D15-083 default_model_history / Cedar (gold HISTORICAL ['Merlin-2B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: What is the retry limit of the Conduit stream, and when is Tidewater Pay support open on weekdays, and what was Cedar's default model before October?  
  reply: 'The retry limit of the Conduit stream is 4 retries [E152].\nThe weekday support hours of Tidewater Pay is 9 to 5 [E165].\nThe records on the default model of Cedar are unclear, so I will not pick an answer.'
- D15-085 support_hours / Quarry Data (gold SUPPORTED ['9 to 6']): got UNSUPPORTED; cause `no_admitted_record`  
  Q: Is there a staging environment for Cedar, and when is Quarry Data support open on weekdays, and how large can a Conduit stream message be?  
  reply: 'The records say there is a staging environment for Cedar [E4].\nThe records do not say the weekday support hours of Quarry Data or the maximum message size of the Conduit stream.'
- D15-087 default_model / Willow (gold SUPPORTED ['Swift-6B']): got UNSUPPORTED; cause `no_admitted_record`  
  Q: What is Willow's default model, and until which month is Quartz funded, and who signs off Willow security?  
  reply: 'The last funded month for Quartz is November [E280].\nThe records do not say the default model of Willow or the security reviewer for Willow.'
- D15-091 default_model_history / Marlin (gold HISTORICAL ['Kestrel-3B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Which model did Vesper decide to keep, and which host serves Swift-6B, and what was Marlin's default model before October?  
  reply: 'The planning decision for Vesper is keep Kestrel-9B as the default model [E245].\nThe host running Swift-6B is the edge host [E144] [E160].\nThe records on the default model of Marlin are unclear, so I will not pick an answer.'
- D15-094 default_model_history / Osprey (gold HISTORICAL ['Kestrel-9B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Through when is the Tamarind budget approved, and who owns the Ferry queue, and which model did Osprey use by default in March?  
  reply: 'The last funded month for Tamarind is August [E234].\nThe owner of the Ferry queue is Chiara Rossi [E64].\nThe records on the default model of Osprey are unclear, so I will not pick an answer.'
- D15-120 default_model / Cedar (gold SUPPORTED ['Swift-20B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who is fixing the Sable rollback test, and which model does Cedar use by default?  
  reply: 'The records on the default model of Cedar are unclear, so I will not pick an answer.\nThe records do not say the person fixing the Sable rollback test.'
- D15-125 default_model / Osprey (gold SUPPORTED ['Swift-6B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who will fix the Willow rollback test, and what is Osprey's default model?  
  reply: 'The records on the default model of Osprey are unclear, so I will not pick an answer.\nThe records do not say the person fixing the Willow rollback test.'
- D15-130 default_model / Osprey (gold SUPPORTED ['Swift-6B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who owns the Conduit stream, and which model does Osprey use by default?  
  reply: 'The records on the default model of Osprey are unclear, so I will not pick an answer.\nThe records do not say the owner of the Conduit stream.'
- D15-132 default_model / Marlin (gold SUPPORTED ['Heron-12B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who is fixing the Sable rollback test, and which model does Marlin use by default?  
  reply: 'The records on the default model of Marlin are unclear, so I will not pick an answer.\nThe records do not say the person fixing the Sable rollback test.'
- D15-139 default_model / Marlin (gold SUPPORTED ['Heron-12B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Who will fix the Quartz rollback test, and what is Marlin's default model?  
  reply: 'The records on the default model of Marlin are unclear, so I will not pick an answer.\nThe records do not say the person fixing the Quartz rollback test.'
- D15-153 default_model_history / Cedar (gold HISTORICAL ['Merlin-2B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: What was Cedar's default model before October?  
  reply: 'The records on the default model of Cedar are unclear, so I will not pick an answer.'
- D15-157 default_model_history / Marlin (gold HISTORICAL ['Kestrel-3B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: What was Marlin's default model before October, and what is the retry limit of the Conduit stream?  
  reply: 'The retry limit of the Conduit stream is 4 retries [E152].\nThe records on the default model of Marlin are unclear, so I will not pick an answer.'
- D15-160 default_model_history / Osprey (gold HISTORICAL ['Kestrel-9B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Which model did Osprey use by default in March, and which model does Quartz use by default?  
  reply: 'The default model of Quartz is Merlin-2B [E279].\nThe records on the default model of Osprey are unclear, so I will not pick an answer.'
- D15-164 default_model_history / Marlin (gold HISTORICAL ['Kestrel-3B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Which model did Marlin use by default in March, and who attended the Cedar planning meeting?  
  reply: 'The attendees of the Cedar planning meeting are Liam Oconnor and Ines Duarte [E292].\nThe records on the default model of Marlin are unclear, so I will not pick an answer.'
- D15-166 default_model_history / Osprey (gold HISTORICAL ['Kestrel-9B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Which model did Osprey use by default in March, and what are Quarry Data's support hours?  
  reply: 'The records on the default model of Osprey are unclear, so I will not pick an answer.\nThe records do not say the weekday support hours of Quarry Data.'
- D15-166 support_hours / Quarry Data (gold SUPPORTED ['9 to 6']): got UNSUPPORTED; cause `no_admitted_record`  
  Q: Which model did Osprey use by default in March, and what are Quarry Data's support hours?  
  reply: 'The records on the default model of Osprey are unclear, so I will not pick an answer.\nThe records do not say the weekday support hours of Quarry Data.'
- D15-170 default_model_history / Marlin (gold HISTORICAL ['Kestrel-3B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Which model did Marlin use by default in March, and through when is the Osprey budget approved?  
  reply: 'The last funded month for Osprey is July [E224].\nThe records on the default model of Marlin are unclear, so I will not pick an answer.'
- D15-172 default_model_history / Osprey (gold HISTORICAL ['Kestrel-9B']): got UNSUPPORTED; cause `ambiguity_on_requested_proposition`  
  Q: Which model did Osprey use by default in March, and through when is the Quartz budget approved?  
  reply: 'The last funded month for Quartz is November [E280].\nThe records on the default model of Osprey are unclear, so I will not pick an answer.'

## Other state mismatches (0)


## Questions with an untyped clause

- D15-054: What was decided about Cedar's default model, and who is the security reviewer for Sable?  → reasons ['ambiguous_relation']
- D15-074: What was decided about Quartz's default model, and who owns the Anvil builder, and how many retries did the archived Anvil builder architecture allow?  → reasons ['ambiguous_relation']
