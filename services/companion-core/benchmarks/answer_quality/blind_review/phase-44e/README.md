# Blind review of 21 Phase 44E answers: how to do it

1. **Read `sheet.md`.** Twenty-one answers in random order. You are not told which system produced which. For each, read the question, who was asking, the evidence the
   assistant was shown, and the answer. Judge from the evidence shown, not from what you know.
2. **Fill `ratings-template.csv`** (copy it to `ratings.csv`): one row per item `R01` to `R21`, columns `q1` to `q8` as listed at the top of the sheet. Every cell must be filled.
3. **Do not open `KEY-do-not-open-until-rated.json`.** It is deliberately not in git (it is ignored; `KEY.sha256` is committed as a seal so a later change is detectable) and it
   lives only in this folder on the machine that built the package.
4. **Unseal and compare** only when every cell is filled:
   `python benchmarks/answer_quality/blind_compare.py --dir benchmarks/answer_quality/blind_review/phase-44e --ratings ratings.csv --out comparison.md`
   It refuses to run on an incomplete ratings file, checks the key against its seal, and prints your correctness rating next to the automatic score per item.
5. Disagreements are findings about the scorer. They never change the consumed first-look scores; they feed the next scorer version and the 44H test plan.
