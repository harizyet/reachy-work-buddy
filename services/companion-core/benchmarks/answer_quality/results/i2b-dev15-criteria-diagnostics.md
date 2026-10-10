# dev15 criteria diagnostics for the final candidate (T-new). Design set; an explanation, not a verdict.

## Criterion 4: mixed questions that are not fully correct

26 of 30 fully correct.

- D15-045: What is Tamarind's default model, and when will the Vesper lead be away next?  
  reply: 'The records do not say the default model of Tamarind. A record says Kestrel-3B was decided on for the default model of Tamarind, but the records do not say it is in place [E233].\nThe records do not say the next time away for the Vesper lead.'  
  why: default_model/Tamarind gold SUPPORTED: not ok false abstention
- D15-054: What was decided about Cedar's default model, and who is the security reviewer for Sable?  
  reply: 'I could not work out one part of the question, so I have not answered it.\nThe records do not say the security reviewer for Sable.'  
  why: decision/Cedar gold SUPPORTED: not ok false abstention
- D15-059: What is Cedar's default model, and how large can a Sluice cache message be?  
  reply: 'The default model of Cedar is Swift-20B [E100].\nThe records do not say the maximum message size of the Sluice cache.'  
  why: default_model/Cedar gold SUPPORTED:  unsupported citation
- D15-070: Which model does Sable use by default, and when is the Vesper lead's next vacation?  
  reply: 'The records do not say the default model of Sable or the next time away for the Vesper lead.'  
  why: default_model/Sable gold SUPPORTED: not ok false abstention

## Criterion 6: cited claims whose cited ids do not all support the claim

183 of 191 cited claims supported (95.8%); 8 not.

- D15-059 default_model/Cedar (SUPPORTED): cites {'E100': 'memory:m100'}; the case registers ['document:doc-cedar-arch']  
  reply: 'The default model of Cedar is Swift-20B [E100].\nThe records do not say the maximum message size of the Sluice cache.'
- D15-072 default_model/Osprey (SUPPORTED): cites {'E106': 'memory:m106'}; the case registers ['document:doc-osprey-arch']  
  reply: "The default model of Osprey is Swift-6B [E106].\nThe deadline for Elena Marsh's written summary is Tuesday [E131].\nPreviously, the retry limit of the Hopper ingest service was 6 retries [E175]."
- D15-081 default_model/Marlin (SUPPORTED): cites {'E102': 'memory:m102'}; the case registers ['document:doc-marlin-arch']  
  reply: 'The default model of Marlin is Heron-12B [E102].\nThe lead of Vesper is Kavya Menon [E44].\nThe records do not say the person who audits the Quartz build logs.'
- D15-120 default_model/Cedar (SUPPORTED): cites {'E100': 'memory:m100'}; the case registers ['document:doc-cedar-arch']  
  reply: 'The records do not say the person fixing the Sable rollback test.\nThe default model of Cedar is Swift-20B [E100].'
- D15-125 default_model/Osprey (SUPPORTED): cites {'E106': 'memory:m106'}; the case registers ['document:doc-osprey-arch']  
  reply: 'The records do not say the person fixing the Willow rollback test.\nThe default model of Osprey is Swift-6B [E106].'
- D15-130 default_model/Osprey (SUPPORTED): cites {'E106': 'memory:m106'}; the case registers ['document:doc-osprey-arch']  
  reply: 'The records do not say the owner of the Conduit stream.\nThe default model of Osprey is Swift-6B [E106].'
- D15-132 default_model/Marlin (SUPPORTED): cites {'E102': 'memory:m102'}; the case registers ['document:doc-marlin-arch']  
  reply: 'The records do not say the person fixing the Sable rollback test.\nThe default model of Marlin is Heron-12B [E102].'
- D15-139 default_model/Marlin (SUPPORTED): cites {'E102': 'memory:m102'}; the case registers ['document:doc-marlin-arch']  
  reply: 'The records do not say the person fixing the Quartz rollback test.\nThe default model of Marlin is Heron-12B [E102].'
